"""
Unit tests for Muster verdict classification and evidence quote extraction.
"""

import pytest
from muster.classifier import classify_outcome, extract_cited_quotes, GHOST_PHRASES, PRESENT_PHRASES
from muster.models import Verdict, Confidence


def test_classify_present_clear():
    outcome = classify_outcome(
        entry_id="H-01",
        entry_name="Apex Hospital",
        phone="+919876543201",
        run_id="run-001",
        calle_status="COMPLETED",
        extracted={
            "reached_human": True,
            "accepts_scheme": True,
            "admitting_patients": True,
            "stated_reason": "Confirmed active Ayushman empanelment and patient admissions."
        },
        transcript="Reception: Haanji, hamara hospital Ayushman Bharat panel pe hai aur abhi patients admit ho rahe hain.",
        evidence_provided=["Haanji, hamara hospital Ayushman Bharat panel pe hai"],
    )
    assert outcome.verdict == Verdict.PRESENT
    assert outcome.confidence == Confidence.HIGH
    assert outcome.confidence_score >= 0.90
    assert len(outcome.evidence_quotes) > 0


def test_classify_ghost_refused_scheme():
    outcome = classify_outcome(
        entry_id="H-02",
        entry_name="City Clinic",
        phone="+919876543202",
        run_id="run-002",
        calle_status="COMPLETED",
        extracted={
            "reached_human": True,
            "accepts_scheme": False,
            "admitting_patients": False,
            "stated_reason": "Facility withdrew from scheme 6 months ago."
        },
        transcript="Reception: Humne 6 mahine pehle hi Ayushman Bharat band kar diya hai, payment clear nahi hota.",
        evidence_provided=["Humne 6 mahine pehle hi Ayushman Bharat band kar diya hai"],
    )
    assert outcome.verdict == Verdict.GHOST
    assert outcome.confidence == Confidence.HIGH
    assert outcome.confidence_score >= 0.90


def test_classify_ghost_wrong_number():
    outcome = classify_outcome(
        entry_id="H-03",
        entry_name="Metro Healthcare",
        phone="+919876543203",
        run_id="run-003",
        calle_status="COMPLETED",
        extracted={
            "reached_human": True,
            "operating_status": "wrong_number",
            "stated_reason": "Personal mobile subscriber answered; no hospital."
        },
        transcript="Respondent: Bhai yeh galat number hai, koi hospital nahi hai yeh.",
        evidence_provided=[],
    )
    assert outcome.verdict == Verdict.GHOST
    assert outcome.confidence == Confidence.HIGH


def test_classify_ghost_dead_carrier_line():
    outcome = classify_outcome(
        entry_id="H-04",
        entry_name="Sunrise Hospital",
        phone="+919876543204",
        run_id="run-004",
        calle_status="FAILED",
        extracted={"reached_human": False},
        transcript="[The number you dialed does not exist]",
        evidence_provided=["Number out of service"],
    )
    assert outcome.verdict == Verdict.GHOST
    assert outcome.confidence == Confidence.HIGH


def test_classify_unreachable_no_answer():
    outcome = classify_outcome(
        entry_id="H-05",
        entry_name="Lotus Medical",
        phone="+919876543205",
        run_id="run-005",
        calle_status="NO ANSWER",
        extracted={"reached_human": False},
        transcript="[Ringing timed out after 45s]",
        evidence_provided=[],
    )
    assert outcome.verdict == Verdict.UNREACHABLE
    assert outcome.confidence == Confidence.HIGH


def test_classify_unreachable_ivr_loop():
    outcome = classify_outcome(
        entry_id="H-06",
        entry_name="National Institute",
        phone="+919876543206",
        run_id="run-006",
        calle_status="COMPLETED",
        extracted={"reached_human": False},
        transcript="[Automated IVR: Press 1 for English, Press 2 for Hindi...]",
        evidence_provided=[],
    )
    assert outcome.verdict == Verdict.UNREACHABLE
    assert outcome.confidence == Confidence.MEDIUM


def test_extract_cited_quotes_matching():
    transcript = "Namaste. Hospital reception here. Humne pichle saal hi band kar diya tha. Please call another centre."
    quotes = extract_cited_quotes(transcript, GHOST_PHRASES)
    assert len(quotes) > 0
    assert "band kar diya" in quotes[0]
