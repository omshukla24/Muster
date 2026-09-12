"""
Targeted tests for Milestones 1–4:
1. US_INSURER and MARKETPLACE_SELLER classification & extract schemas.
2. E.164 phone normalization (+1 US, +91 India).
3. Resilient failure mapping (FAILED, NO ANSWER, ByCallee, 0s duration -> UNREACHABLE).
4. Ghost-rate calculations & derived patient access ratio edge cases (0%, 100%, empty).
5. Zero-live-call guarantee (ensures testing suite never places real calls).
"""

import pytest
from unittest.mock import patch, MagicMock

from muster.models import Sector, Verdict, Confidence, DirectoryEntry, CallOutcome
from muster.classifier import classify_outcome
from muster.parser import normalize_phone, parse_directory_data
from muster.engine import AuditEngine
from muster.calle_client import MockCalleClient, CalleClient


def test_us_insurer_classification_present():
    outcome = classify_outcome(
        entry_id="PROV-101",
        entry_name="Dr. Sarah Jenkins, MD",
        phone="+15552340101",
        run_id="run-test-1",
        calle_status="COMPLETED",
        extracted={
            "reached_human": True,
            "in_network": True,
            "accepting_new_patients": True,
            "stated_reason": "Confirmed active in-network provider taking new patients.",
        },
        transcript="Reception: Yes, we are currently in-network and accepting new patients.",
        evidence_provided=["Yes, we are currently in-network and accepting new patients."],
        duration_seconds=18.0,
        sector=Sector.US_INSURER,
    )
    assert outcome.verdict == Verdict.PRESENT
    assert outcome.confidence == Confidence.HIGH
    assert outcome.confidence_score >= 0.90
    assert "in-network" in outcome.evidence_quotes[0].lower()


def test_us_insurer_classification_refused_or_left_network():
    outcome = classify_outcome(
        entry_id="PROV-102",
        entry_name="Summit Psychological Associates",
        phone="+15552340102",
        run_id="run-test-2",
        calle_status="COMPLETED",
        extracted={
            "reached_human": True,
            "in_network": False,
            "accepting_new_patients": False,
            "stated_reason": "Left the network 6 months ago; strictly self-pay.",
        },
        transcript="Reception: I am sorry, we left that network last year. The directory is outdated.",
        evidence_provided=["We left that network last year."],
        duration_seconds=22.0,
        sector=Sector.US_INSURER,
    )
    assert outcome.verdict == Verdict.GHOST
    assert outcome.confidence == Confidence.HIGH
    assert outcome.confidence_score >= 0.90


def test_marketplace_seller_classification():
    # Present seller
    present_outcome = classify_outcome(
        entry_id="SELL-001",
        entry_name="Vintage Watch Exchange",
        phone="+15553010001",
        run_id="run-test-3",
        calle_status="COMPLETED",
        extracted={
            "reachable": True,
            "operational": True,
            "sells_claimed_product": True,
            "stated_reason": "Store open regular hours and orders fulfilling daily.",
        },
        transcript="Merchant: Yes, our retail shop is open and we fulfill all orders.",
        sector=Sector.MARKETPLACE_SELLER,
    )
    assert present_outcome.verdict == Verdict.PRESENT

    # Defunct ghost seller
    ghost_outcome = classify_outcome(
        entry_id="SELL-002",
        entry_name="Defunct Electronics",
        phone="+15553010002",
        run_id="run-test-4",
        calle_status="COMPLETED",
        extracted={
            "reachable": True,
            "operational": False,
            "sells_claimed_product": False,
            "stated_reason": "Store permanently closed down.",
        },
        transcript="Respondent: We dissolved that business six months ago.",
        sector=Sector.MARKETPLACE_SELLER,
    )
    assert ghost_outcome.verdict == Verdict.GHOST


def test_e164_parsing_us_and_india():
    # US Numbers (+1)
    assert normalize_phone("+1 (555) 234-0101") == "+15552340101"
    assert normalize_phone("(555) 234-0101", default_country_code="+1") == "+15552340101"
    assert normalize_phone("+1 555-234-0102") == "+15552340102"
    assert normalize_phone("5552340103", default_country_code="+1") == "+15552340103"
    assert normalize_phone("+15552340104") == "+15552340104"

    # India Numbers (+91)
    assert normalize_phone("9876543201") == "+919876543201"
    assert normalize_phone("+91 98765 43202") == "+919876543202"
    assert normalize_phone("09876543203") == "+919876543203"


def test_failed_and_no_answer_to_unreachable_mapping():
    # Standard no-answer
    res_no_ans = classify_outcome(
        entry_id="PROV-001",
        entry_name="Test Clinic",
        phone="+15550001111",
        run_id="run-fail-1",
        calle_status="NO ANSWER",
        extracted={"reached_human": False},
        duration_seconds=45.0,
    )
    assert res_no_ans.verdict == Verdict.UNREACHABLE

    # ByCallee reject
    res_bycallee = classify_outcome(
        entry_id="PROV-002",
        entry_name="Test Clinic 2",
        phone="+15550002222",
        run_id="run-fail-2",
        calle_status="BYCALLEE",
        extracted={"reached_human": False},
        duration_seconds=1.2,
    )
    assert res_bycallee.verdict == Verdict.UNREACHABLE

    # 0s carrier failure
    res_zero = classify_outcome(
        entry_id="PROV-003",
        entry_name="Test Clinic 3",
        phone="+15550003333",
        run_id="run-fail-3",
        calle_status="FAILED",
        extracted={"reached_human": False},
        duration_seconds=0.0,
    )
    assert res_zero.verdict == Verdict.UNREACHABLE


def test_ghost_rate_and_access_ratio_edge_cases():
    engine = AuditEngine(client=MockCalleClient())

    # Empty outcomes
    empty_sum = engine.calculate_summary([], total_entries=10)
    assert empty_sum.ghost_rate_pct == 0.0
    assert empty_sum.completed == 0

    # 100% Ghost outcomes
    ghosts = [
        CallOutcome(
            entry_id=f"E-{i}",
            entry_name=f"Ghost {i}",
            phone="+15550000000",
            run_id=f"r-{i}",
            calle_status="COMPLETED",
            verdict=Verdict.GHOST,
            confidence=Confidence.HIGH,
            confidence_score=0.95,
        )
        for i in range(5)
    ]
    all_ghost_sum = engine.calculate_summary(ghosts, total_entries=5)
    assert all_ghost_sum.ghost_rate_pct == 100.0
    assert all_ghost_sum.present_count == 0

    # 0% Ghost outcomes (100% Present)
    presents = [
        CallOutcome(
            entry_id=f"P-{i}",
            entry_name=f"Present {i}",
            phone="+15550000001",
            run_id=f"rp-{i}",
            calle_status="COMPLETED",
            verdict=Verdict.PRESENT,
            confidence=Confidence.HIGH,
            confidence_score=0.95,
        )
        for i in range(4)
    ]
    zero_ghost_sum = engine.calculate_summary(presents, total_entries=4)
    assert zero_ghost_sum.ghost_rate_pct == 0.0
    assert zero_ghost_sum.verified_rate_pct == 100.0


@pytest.mark.asyncio
async def test_zero_live_calls_guarantee():
    """
    CRITICAL SAFETY TEST:
    Asserts that tests and MockCalleClient audits NEVER call subprocess 'calle call start',
    spends zero credits, and executes 100% offline.
    """
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.side_effect = RuntimeError("Subprocess execution forbidden in test suite!")

        client = MockCalleClient(artificial_delay_sec=0.0)
        res = await client.execute_call_audit(
            phone="+15552340101",
            goal="Test audit inquiry",
            sector=Sector.US_INSURER,
        )

        assert res["status"] == "COMPLETED"
        assert res["extracted"]["reached_human"] is True
        assert res["extracted"]["in_network"] is True
        # Verify subprocess was never touched
        mock_subproc.assert_not_called()


def test_formula_injection_sanitization():
    from muster.parser import sanitize_formula_injection
    from muster.report import _sanitize_csv_cell

    dangerous_payloads = [
        "=cmd|' /C calc'!A0",
        "+12345678",
        "-5+5",
        "@SUM(A1:A10)",
        "\tmalicious_tab",
    ]

    for p in dangerous_payloads:
        sanitized = sanitize_formula_injection(p)
        assert sanitized.startswith("'"), f"Failed to neutralize import formula: {p}"
        sanitized_cell = _sanitize_csv_cell(p)
        assert sanitized_cell.startswith("'"), f"Failed to neutralize export formula: {p}"

    # Benign string unchanged
    assert sanitize_formula_injection("Dr. Sarah Jenkins") == "Dr. Sarah Jenkins"
    assert _sanitize_csv_cell("In-Network - BlueCross") == "In-Network - BlueCross"


def test_pre_call_phone_sanity_check():
    from muster.parser import pre_call_phone_sanity_check

    entries = [
        DirectoryEntry(id="E1", name="Valid Clinic", phone="+15552340101"),
        DirectoryEntry(id="E2", name="Dummy Number Clinic", phone="+15555555555"),
        DirectoryEntry(id="E3", name="Short Phone Clinic", phone="+1555123"),
        DirectoryEntry(id="E4", name="Clinic A (Shared)", phone="+15552340109"),
        DirectoryEntry(id="E5", name="Clinic B (Shared)", phone="+15552340109"),
    ]

    anomalies = pre_call_phone_sanity_check(entries)
    issues = [a["issue"] for a in anomalies]

    assert "DUMMY_PATTERN" in issues
    assert "INVALID_LENGTH" in issues
    assert "DUPLICATE_CROSS_ENTITY" in issues

