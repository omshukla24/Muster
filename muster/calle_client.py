"""
CALL-E integration client for Muster.
Provides:
  1. CalleClient: Subprocess execution of the `calle` CLI (call start -> poll call status).
  2. MockCalleClient: Deterministic simulated test harness for zero-cost testing and UI demo rehearsals in English and Hindi.
"""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import time
from typing import Dict, Any, Optional
from muster.models import Sector


def infer_region_from_phone(phone: str) -> str:
    """Infers standard 2-letter ISO region from phone prefix for CALL-E."""
    if not phone:
        return "US"
    clean = phone.strip()
    if clean.startswith("+1"):
        return "US"
    if clean.startswith("+91"):
        return "IN"
    if clean.startswith("+44"):
        return "GB"
    if clean.startswith("+65"):
        return "SG"
    if clean.startswith("+61"):
        return "AU"
    return "US"


class CalleClient:
    """Production runtime caller interfacing with local `calle` CLI via `call start`."""

    def __init__(
        self,
        source: str = "skills_sh",
        integration: str = "skills_sh_skill",
        integration_version: str = "0.1.0",
        poll_interval: float = 2.0,
        max_poll_seconds: float = 120.0,
    ):
        self.source = source
        self.integration = integration
        self.integration_version = integration_version
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds

    def _get_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["CALLE_SOURCE"] = self.source
        env["CALLE_INTEGRATION"] = self.integration
        env["CALLE_INTEGRATION_VERSION"] = self.integration_version
        return env

    def _run_cli(self, args: list[str]) -> Dict[str, Any]:
        """Runs the calle CLI synchronously and returns parsed JSON output."""
        cmd = ["calle"] + args + ["--json"]
        proc = subprocess.run(
            cmd,
            env=self._get_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"calle CLI error (code {proc.returncode}): {err}")

        stdout_raw = proc.stdout.strip()
        try:
            return json.loads(stdout_raw)
        except json.JSONDecodeError:
            # Search from end for the last valid JSON block
            lines = stdout_raw.splitlines()
            for i in range(len(lines)):
                sub = "\n".join(lines[i:])
                try:
                    return json.loads(sub)
                except Exception:
                    continue
            raise RuntimeError(f"Failed to parse JSON output from calle CLI: {stdout_raw}")

    async def execute_call_audit(
        self,
        phone: str,
        goal: str,
        language: str = "en",
        region: Optional[str] = None,
        sector: Sector = Sector.US_INSURER,
    ) -> Dict[str, Any]:
        """
        Executes a single end-to-end CALL-E audit call:
        1. calle call start --to-phone <phone> --goal <goal> --language en
        2. poll calle call status --run-id <run_id> until terminal
        Returns normalized dictionary resilient to delivery / network failures.
        """
        start_time = time.time()
        target_region = region or infer_region_from_phone(phone)

        # Step 1: Start Call
        start_args = [
            "call", "start",
            "--to-phone", phone,
            "--goal", goal,
            "--language", language or "en",
            "--region", target_region,
        ]

        try:
            start_res = await asyncio.to_thread(self._run_cli, start_args)
        except Exception as exc:
            # Resilient fallback: return cleanly as UNREACHABLE / failed delivery rather than crashing
            err_msg = str(exc)
            duration = time.time() - start_time
            return {
                "run_id": f"err-{int(start_time)}",
                "status": "UNREACHABLE",
                "extracted": {"reached_human": False, "stated_reason": f"Dispatch error: {err_msg}"},
                "evidence": [f"Delivery failure: {err_msg}"],
                "transcript": f"[Carrier/Delivery error: {err_msg}]",
                "duration_seconds": round(duration, 2),
                "raw": {},
            }

        run_id = start_res.get("run_id") or start_res.get("id")
        if not run_id and "result" in start_res:
            res_obj = start_res["result"]
            run_id = res_obj.get("run_id") or res_obj.get("id")

        if not run_id:
            # Fallback if plan output returned instead
            plan_id = start_res.get("plan_id") or start_res.get("result", {}).get("plan_id")
            confirm_token = start_res.get("confirm_token") or start_res.get("result", {}).get("confirm_token")
            if plan_id and confirm_token:
                run_res = await asyncio.to_thread(
                    self._run_cli,
                    ["call", "run", "--plan-id", str(plan_id), "--confirm-token", str(confirm_token)]
                )
                run_id = run_res.get("run_id") or run_res.get("result", {}).get("run_id")

        if not run_id:
            return {
                "run_id": f"unconfirmed-{int(start_time)}",
                "status": "UNREACHABLE",
                "extracted": {"reached_human": False, "stated_reason": "No run_id returned by CALL-E"},
                "evidence": ["CALL-E call start did not return run_id"],
                "transcript": "[Delivery incomplete]",
                "duration_seconds": round(time.time() - start_time, 2),
                "raw": start_res,
            }

        # Step 2: Poll status
        elapsed = 0.0
        terminal_statuses = {
            "COMPLETED", "FAILED", "NO ANSWER", "NO_ANSWER",
            "DECLINED", "BUSY", "CANCELED", "CANCELLED", "BYCALLEE"
        }

        latest_run_data: Dict[str, Any] = {}

        while elapsed < self.max_poll_seconds:
            await asyncio.sleep(self.poll_interval)
            elapsed = time.time() - start_time

            try:
                status_res = await asyncio.to_thread(
                    self._run_cli, ["call", "status", "--run-id", str(run_id)]
                )
                latest_run_data = status_res

                curr_status = str(status_res.get("status", "")).upper()
                if not curr_status and "result" in status_res:
                    curr_status = str(status_res["result"].get("status", "")).upper()

                if curr_status in terminal_statuses:
                    break
            except Exception:
                # Retry on brief socket error during polling
                continue

        duration = time.time() - start_time
        return self._normalize_calle_result(latest_run_data, run_id, duration)

    def _normalize_calle_result(self, raw: Dict[str, Any], run_id: str, duration: float) -> Dict[str, Any]:
        """Normalizes CALL-E result into a uniform dict for the classifier."""
        res_node = raw.get("result", raw)
        status = res_node.get("status", raw.get("status", "COMPLETED")).upper()

        outcome_node = res_node.get("outcome", {}) or {}
        extracted = res_node.get("extracted") or outcome_node.get("extracted") or {}
        evidence = outcome_node.get("evidence") or res_node.get("evidence") or []
        transcript = res_node.get("transcript") or outcome_node.get("transcript") or ""

        # Handle ByCallee / cancelled / 0s failures cleanly as UNREACHABLE
        if status in ["BYCALLEE", "NO_ANSWER", "NO ANSWER", "BUSY", "CANCELED", "CANCELLED", "DECLINED"] or (duration < 1.0 and status == "FAILED"):
            status = "NO ANSWER"

        return {
            "run_id": run_id,
            "status": status,
            "extracted": extracted,
            "evidence": evidence,
            "transcript": transcript,
            "duration_seconds": round(duration, 2),
            "raw": raw,
        }


class MockCalleClient:
    """
    Deterministic simulated CALL-E client for automated testing and offline demos.
    Supports US_INSURER and MARKETPLACE_SELLER sectors in English with zero credit consumption.
    """

    def __init__(self, artificial_delay_sec: float = 0.4):
        self.delay = artificial_delay_sec

    async def execute_call_audit(
        self,
        phone: str,
        goal: str,
        language: str = "en",
        region: Optional[str] = None,
        mock_scenario: Optional[str] = None,
        entity_name: str = "",
        sector: Sector = Sector.US_INSURER,
    ) -> Dict[str, Any]:
        """Simulates an audit call with deterministic scenarios based on phone or name."""
        if self.delay > 0:
            await asyncio.sleep(self.delay)

        scenario = mock_scenario or self._infer_scenario(phone, entity_name)
        run_id = f"mock-run-{abs(hash(phone + entity_name)) % 1000000:06d}"

        # ------------------------------------------------------------------
        # Sector 1: US_INSURER (Hero Demo, English) & General Healthcare
        # ------------------------------------------------------------------
        if sector == Sector.US_INSURER:
            if scenario == "PRESENT":
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "extracted": {
                        "reached_human": True,
                        "in_network": True,
                        "accepting_new_patients": True,
                        "accepts_scheme": True,
                        "admitting_patients": True,
                        "operating_status": "active",
                        "stated_reason": "Reception confirmed active in-network participation and intake availability.",
                    },
                    "evidence": [
                        f"Yes, {entity_name or 'our clinic'} is currently in-network and accepting new patients.",
                        "We have new patient intake openings available next Tuesday."
                    ],
                    "transcript": (
                        f"Agent: Hello, I'm calling to verify directory network status for {entity_name or 'the clinic'}. Are you currently in-network and accepting new patients?\n"
                        f"Reception: Yes, absolutely. We are in-network and currently accepting new patients for both telehealth and in-person visits.\n"
                        f"Agent: Great, thank you so much for confirming!\n"
                        f"Reception: You're welcome, have a good day."
                    ),
                    "duration_seconds": 18.2,
                    "raw": {},
                }

            elif scenario == "GHOST_REFUSED":
                op_status = "left_scheme" if phone.startswith("+91") else "left_network"
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "extracted": {
                        "reached_human": True,
                        "in_network": False,
                        "accepting_new_patients": False,
                        "accepts_scheme": False,
                        "admitting_patients": False,
                        "operating_status": op_status,
                        "stated_reason": "Provider withdrew from the insurance network over 6 months ago; strictly self-pay.",
                    },
                    "evidence": [
                        "We left that insurance network last year due to reimbursement disputes.",
                        "We are strictly out-of-network and do not take new insurance patients."
                    ],
                    "transcript": (
                        f"Agent: Hello, I'm calling to verify in-network coverage for {entity_name or 'Dr. Chen'}.\n"
                        f"Reception: I'm sorry, we left that insurance network over six months ago. The directory is outdated.\n"
                        f"Agent: Are you accepting any patients under that plan?\n"
                        f"Reception: No, we are strictly self-pay or out-of-network now.\n"
                        f"Agent: Understood, thank you for the clarification."
                    ),
                    "duration_seconds": 21.5,
                    "raw": {},
                }

            elif scenario == "GHOST_WRONG_NUMBER":
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "extracted": {
                        "reached_human": True,
                        "in_network": False,
                        "accepting_new_patients": False,
                        "accepts_scheme": False,
                        "admitting_patients": False,
                        "operating_status": "wrong_number",
                        "stated_reason": "Personal or unrelated commercial line answered; no medical practice.",
                    },
                    "evidence": [
                        "You have the wrong number, this is an auto body repair shop.",
                        "There is no doctor or clinic at this number."
                    ],
                    "transcript": (
                        f"Agent: Hello, is this {entity_name or 'the healthcare practice'}?\n"
                        f"Respondent: No, you've got the wrong number. This is an auto repair shop in Austin.\n"
                        f"Agent: The online insurance portal lists this number for medical services.\n"
                        f"Respondent: Well that's completely wrong, I've had this line for seven years. Please remove it.\n"
                        f"Agent: We apologize for the inconvenience, goodbye."
                    ),
                    "duration_seconds": 14.7,
                    "raw": {},
                }

            elif scenario == "GHOST_DEAD_LINE":
                return {
                    "run_id": run_id,
                    "status": "FAILED",
                    "extracted": {
                        "reached_human": False,
                        "in_network": False,
                        "accepting_new_patients": False,
                        "accepts_scheme": False,
                        "admitting_patients": False,
                        "operating_status": "disconnected",
                        "stated_reason": "Carrier network intercept: Number does not exist or is no longer in service.",
                    },
                    "evidence": [
                        "Carrier intercept: The number you dialed does not exist or has been disconnected."
                    ],
                    "transcript": "[Telecom Intercept: We're sorry, the number you dialed does not exist or has been disconnected. Please check the number and dial again.]",
                    "duration_seconds": 5.4,
                    "raw": {},
                }

            elif scenario == "UNREACHABLE_NO_ANSWER":
                return {
                    "run_id": run_id,
                    "status": "NO ANSWER",
                    "extracted": {
                        "reached_human": False,
                        "in_network": None,
                        "accepting_new_patients": None,
                        "accepts_scheme": None,
                        "admitting_patients": None,
                        "operating_status": "unanswered",
                        "stated_reason": "Line rang continuously for 45s without answer.",
                    },
                    "evidence": ["Call rang for 45 seconds with zero answer."],
                    "transcript": "[Ring tone... Ring tone... Call timed out without response]",
                    "duration_seconds": 45.0,
                    "raw": {},
                }

        # ------------------------------------------------------------------
        # Sector 2: MARKETPLACE_SELLER
        # ------------------------------------------------------------------
        if sector == Sector.MARKETPLACE_SELLER:
            if scenario == "PRESENT":
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "extracted": {
                        "reachable": True,
                        "operational": True,
                        "sells_claimed_product": True,
                        "stated_reason": "Merchant confirmed physical store is open and actively fulfilling orders.",
                    },
                    "evidence": [
                        f"Yes, this is {entity_name or 'our store'}, we are open and fulfilling orders daily.",
                        "All listed items are in stock."
                    ],
                    "transcript": (
                        f"Agent: Hello, calling for merchant verification. Are you currently operational and fulfilling orders?\n"
                        f"Merchant: Yes, our retail store is open regular hours and we fulfill orders every day.\n"
                        f"Agent: Thank you for confirming!"
                    ),
                    "duration_seconds": 15.0,
                    "raw": {},
                }
            else:
                return {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "extracted": {
                        "reachable": True,
                        "operational": False,
                        "sells_claimed_product": False,
                        "stated_reason": "Store permanently closed down.",
                    },
                    "evidence": ["We permanently closed this business 6 months ago."],
                    "transcript": "Respondent: That business was dissolved six months ago. We don't operate anymore.",
                    "duration_seconds": 12.0,
                    "raw": {},
                }

        # Fallback / General
        return {
            "run_id": run_id,
            "status": "COMPLETED",
            "extracted": {
                "reached_human": True,
                "in_network": True,
                "accepting_new_patients": True,
                "stated_reason": "Provider affirmed active status.",
            },
            "evidence": ["Confirmed active provider."],
            "transcript": "Agent: Directory check. Reception: Yes, active.",
            "duration_seconds": 12.0,
            "raw": {},
        }

    def _infer_scenario(self, phone: str, name: str) -> str:
        """Determines scenario from phone or name for realistic sample runs."""
        combined = (phone + name).lower()
        if "dead" in combined or "0000" in phone or phone.endswith("09") or phone.endswith("00"):
            return "GHOST_DEAD_LINE"
        if "wrong" in combined or "9999" in phone or phone.endswith("03") or phone.endswith("07"):
            return "GHOST_WRONG_NUMBER"
        if "refuse" in combined or "closed" in combined or phone.endswith("02") or phone.endswith("05") or phone.endswith("10"):
            return "GHOST_REFUSED"
        if "busy" in combined or "unreachable" in combined or phone.endswith("06") or phone.endswith("11"):
            return "UNREACHABLE_NO_ANSWER"
        # Remaining: ~40% present, ~40% ghost, ~20% unreachable
        last_digit = int(phone[-1]) if phone and phone[-1].isdigit() else 1
        if last_digit in [1, 4, 8]:
            return "PRESENT"
        elif last_digit in [2, 5, 0, 7]:
            return "GHOST_REFUSED"
        elif last_digit in [3, 9]:
            return "GHOST_DEAD_LINE"
        else:
            return "UNREACHABLE_NO_ANSWER"
