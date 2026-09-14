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


def test_assistant_prompt_not_cited_as_present_and_operator_hangup_is_uncertain():
    """Verify that assistant questions in transcripts are never cited as proof,
    and an operator who hung up before answering is classified as UNCERTAIN, NOT PRESENT."""
    transcript = (
        "[ASSISTANT]: Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients?\n"
        "[ASSISTANT]: Can you hear me?\n"
        "[USER]: To continue in English, press 1. For all other languages, press 9.\n"
        "[ASSISTANT]: [DTMF]1\n"
        "[ASSISTANT]: Okay.\n"
        "[USER]: Please hold while I connect you to an operator.\n"
        "[ASSISTANT]: I'll hold.\n"
        "[ASSISTANT]: No rush.\n"
        "[USER]: Mass General. Can I help you?\n"
        "[ASSISTANT]: Hi, I’m calling to verify directory network status and need to confirm whether you are currently in-network and accepting new patients."
    )
    # The assistant asked about in-network, but the user/callee never confirmed it
    quotes = extract_cited_quotes(transcript, PRESENT_PHRASES)
    assert quotes == [], f"Expected empty present quotes, got: {quotes}"

    outcome = classify_outcome(
        entry_id="LIVE-002",
        entry_name="Massachusetts General Hospital (Main Campus)",
        phone="+16177262000",
        run_id="run-live-002",
        calle_status="COMPLETED",
        extracted={"reached_human": True},
        transcript=transcript,
        evidence_provided=[],
        duration_seconds=42.0,
    )
    # Must NOT be marked PRESENT!
    assert outcome.verdict == Verdict.UNCERTAIN
    assert outcome.confidence == Confidence.LOW
    assert outcome.confidence_score == 0.50
    assert "Mass General" in outcome.stated_reason
    assert any("Mass General" in q for q in outcome.evidence_quotes)


def test_operator_affirmative_answer_is_present():
    """Verify that when the human callee explicitly confirms in-network and intake, verdict is PRESENT."""
    transcript = (
        "[ASSISTANT]: Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients?\n"
        "[USER]: Yes, we are currently in-network and accepting new patients for primary care."
    )
    quotes = extract_cited_quotes(transcript, PRESENT_PHRASES)
    assert len(quotes) > 0
    assert "in-network" in quotes[0]

    outcome = classify_outcome(
        entry_id="LIVE-002",
        entry_name="Massachusetts General Hospital",
        phone="+16177262000",
        run_id="run-live-002",
        calle_status="COMPLETED",
        extracted={"reached_human": True},
        transcript=transcript,
        evidence_provided=[],
        duration_seconds=25.0,
    )
    assert outcome.verdict == Verdict.PRESENT
    assert outcome.confidence_score >= 0.85


def test_citymd_shania_transcript_is_present():
    """Verify that Shania's responses at CityMD ('Yes. We do accept new patients.') resolve as PRESENT with citation."""
    transcript = (
        "[ASSISTANT]: Hello, I am calling to verify directory network status. Are ... [interrupted]\n"
        "[USER]: Thank you for calling CityMD of East 37th Street. For medical questions, please press 1.\n"
        "[ASSISTANT]: [DTMF]1\n"
        "[USER]: Good morning. This is City MD on East 37th Street. My name is Shania. How may I assist you?\n"
        "[ASSISTANT]: Good morning, Shania. I'm calling to verify directory network status; can you tell me whether you are currently in-network?\n"
        "[USER]: Yes. Is this is this an insurance company?\n"
        "[ASSISTANT]: No, I'm calling to verify directory network status. Are you currently accepting new patients?\n"
        "[USER]: Yes. We do accept new patients.\n"
        "[ASSISTANT]: Thank you, I have that information. Is there anything else I should capture regarding your network status?\n"
        "[USER]: No.\n"
        "[ASSISTANT]: Thank you, bye. <dialog-end>"
    )
    quotes = extract_cited_quotes(transcript, PRESENT_PHRASES)
    assert len(quotes) > 0
    assert any("accept new patients" in q.lower() for q in quotes)

    outcome = classify_outcome(
        entry_id="LIVE-001",
        entry_name="CityMD Urgent Care (Midtown East)",
        phone="+12127294668",
        run_id="run-live-001",
        calle_status="COMPLETED",
        extracted={"reached_human": True},
        transcript=transcript,
        evidence_provided=[],
        duration_seconds=55.0,
    )
    assert outcome.verdict == Verdict.PRESENT
    assert outcome.confidence_score >= 0.85
    assert any("accept new patients" in q for q in outcome.evidence_quotes)
