"""
Batch Audit Engine for Muster.
Coordinates parallel execution, event streaming, progress tracking, and statistical aggregation.
"""

from __future__ import annotations
import asyncio
from datetime import datetime
import time
from typing import List, AsyncGenerator, Optional, Union

from muster.models import (
    DirectoryEntry,
    CallOutcome,
    AuditSummary,
    AuditJob,
    AuditProgressEvent,
    Verdict,
    Confidence,
    Sector,
    SECTOR_DEFAULTS,
)
from muster.classifier import classify_outcome
from muster.calle_client import CalleClient, MockCalleClient


DEFAULT_GOAL = (
    "Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients? "
    "If asked who is calling or if this is an insurance company, politely state that you are calling for routine directory verification to confirm active provider network status."
)


class AuditEngine:
    """Core batch audit executor."""

    def __init__(
        self,
        client: Optional[Union[CalleClient, MockCalleClient]] = None,
        concurrency: int = 2,
        default_goal: Optional[str] = None,
        language: str = "en",
        sector: Sector = Sector.US_INSURER,
    ):
        self.client = client or MockCalleClient()
        is_live = isinstance(self.client, CalleClient)
        # Real CALL-E calls must run sequentially (concurrency=1) to avoid SIP line collision
        self.concurrency = 1 if is_live else max(1, concurrency)
        self.sector = sector
        sector_cfg = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS[Sector.US_INSURER])
        self.default_goal = default_goal or sector_cfg.get("default_goal", DEFAULT_GOAL)
        self.language = language or sector_cfg.get("language", "en")

    def calculate_summary(self, outcomes: List[CallOutcome], total_entries: int) -> AuditSummary:
        """Computes statistical ghost-rate and verification metrics."""
        completed = len(outcomes)
        present = sum(1 for o in outcomes if o.verdict == Verdict.PRESENT)
        ghost = sum(1 for o in outcomes if o.verdict == Verdict.GHOST)
        unreachable = sum(1 for o in outcomes if o.verdict == Verdict.UNREACHABLE)
        uncertain = sum(1 for o in outcomes if o.verdict == Verdict.UNCERTAIN)

        ghost_rate = round((ghost / completed * 100), 1) if completed > 0 else 0.0
        verified_rate = round((present / completed * 100), 1) if completed > 0 else 0.0
        avg_dur = round(sum(o.duration_seconds for o in outcomes) / completed, 1) if completed > 0 else 0.0

        if completed == 0:
            headline = "Audit in progress..."
        elif present == 0 and ghost == 0:
            headline = f"{unreachable + uncertain} of {completed} could not be verified"
        else:
            headline = f"{ghost} of {completed} audited = GHOST ({ghost_rate}%)"

        return AuditSummary(
            total=total_entries,
            completed=completed,
            present_count=present,
            ghost_count=ghost,
            unreachable_count=unreachable,
            uncertain_count=uncertain,
            ghost_rate_pct=ghost_rate,
            verified_rate_pct=verified_rate,
            avg_duration_sec=avg_dur,
            headline=headline,
            sector=self.sector,
        )

    async def run_audit_stream(
        self,
        entries: List[DirectoryEntry],
        job_id: str,
        goal: Optional[str] = None,
    ) -> AsyncGenerator[AuditProgressEvent, None]:
        """
        Executes directory audit and streams progress events in real-time.
        """
        total = len(entries)
        outcomes: List[CallOutcome] = []
        active_goal = goal or self.default_goal

        yield AuditProgressEvent(
            job_id=job_id,
            event_type="start",
            message=f"Starting audit job {job_id} on {total} entries.",
            progress_pct=0.0,
            summary=self.calculate_summary([], total),
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        loop = asyncio.get_event_loop()
        event_queue: asyncio.Queue[AuditProgressEvent] = asyncio.Queue()

        async def audit_single_entry(entry: DirectoryEntry):
            entry_sector = entry.sector or self.sector
            async with semaphore:
                await event_queue.put(
                    AuditProgressEvent(
                        job_id=job_id,
                        event_type="row_calling",
                        entry_id=entry.id,
                        message=f"Calling {entry.name} ({entry.phone})...",
                    )
                )

                try:
                    is_mock = isinstance(self.client, MockCalleClient)
                    if is_mock:
                        res = await self.client.execute_call_audit(
                            phone=entry.phone,
                            goal=active_goal,
                            language=self.language,
                            entity_name=entry.name,
                            sector=entry_sector,
                        )
                    else:
                        res = await self.client.execute_call_audit(
                            phone=entry.phone,
                            goal=active_goal,
                            language=self.language,
                            sector=entry_sector,
                        )

                    await event_queue.put(
                        AuditProgressEvent(
                            job_id=job_id,
                            event_type="row_analyzing",
                            entry_id=entry.id,
                            message=f"Analyzing transcript & extract schema for {entry.name}...",
                        )
                    )

                    outcome = classify_outcome(
                        entry_id=entry.id,
                        entry_name=entry.name,
                        phone=entry.phone,
                        run_id=res.get("run_id", f"run-{entry.id}"),
                        calle_status=res.get("status", "COMPLETED"),
                        extracted=res.get("extracted", {}),
                        transcript=res.get("transcript", ""),
                        evidence_provided=res.get("evidence", []),
                        duration_seconds=res.get("duration_seconds", 0.0),
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                        sector=entry_sector,
                    )

                except Exception as exc:
                    outcome = CallOutcome(
                        entry_id=entry.id,
                        entry_name=entry.name,
                        phone=entry.phone,
                        run_id=f"err-{entry.id}",
                        calle_status="ERROR",
                        verdict=Verdict.UNREACHABLE,
                        confidence_score=0.90,
                        confidence=Confidence.HIGH,
                        evidence_quotes=["The call could not be completed (system error)."],
                        stated_reason="The call could not be completed due to a system error.",
                        extracted={"reached_human": False,
                                   "stated_reason": "The call could not be completed due to a system error.",
                                   "error_detail": str(exc)},
                        transcript="",
                        duration_seconds=0.0,
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                        sector=entry_sector,
                    )

                outcomes.append(outcome)
                current_summary = self.calculate_summary(outcomes, total)
                pct = round((len(outcomes) / total) * 100, 1)

                await event_queue.put(
                    AuditProgressEvent(
                        job_id=job_id,
                        event_type="row_resolved",
                        entry_id=entry.id,
                        outcome=outcome,
                        summary=current_summary,
                        message=f"{entry.name} resolved as {outcome.verdict.value} ({outcome.confidence.value} confidence)",
                        progress_pct=pct,
                    )
                )

                if not is_mock:
                    # Carrier SIP trunk line release cooldown
                    await asyncio.sleep(4.0)

        tasks = [asyncio.create_task(audit_single_entry(entry)) for entry in entries]
        
        # Stream events until all tasks finish
        completed_tasks = 0
        while completed_tasks < total:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                yield event
                if event.event_type == "row_resolved":
                    completed_tasks += 1
            except asyncio.TimeoutError:
                # Check if tasks are done
                if all(t.done() for t in tasks) and event_queue.empty():
                    break

        # Flush any remaining items in queue
        while not event_queue.empty():
            yield event_queue.get_nowait()

        final_summary = self.calculate_summary(outcomes, total)
        yield AuditProgressEvent(
            job_id=job_id,
            event_type="complete",
            summary=final_summary,
            message=f"Audit finished: {final_summary.headline}",
            progress_pct=100.0,
        )

    async def run_audit(
        self,
        entries: List[DirectoryEntry],
        job_id: str,
        goal: Optional[str] = None,
    ) -> AuditJob:
        """Convenience method running full audit and returning populated AuditJob."""
        outcomes: List[CallOutcome] = []
        async for event in self.run_audit_stream(entries, job_id, goal):
            if event.event_type == "row_resolved" and event.outcome:
                outcomes.append(event.outcome)

        summary = self.calculate_summary(outcomes, len(entries))
        return AuditJob(
            job_id=job_id,
            name=f"Audit Job {job_id}",
            mode="mock" if isinstance(self.client, MockCalleClient) else "live",
            status="COMPLETED",
            total_entries=len(entries),
            completed_entries=len(outcomes),
            summary=summary,
            outcomes=outcomes,
            created_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
        )
