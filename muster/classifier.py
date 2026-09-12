"""
Evidence & Verdict Classifier for Muster.
Supports US_INSURER and MARKETPLACE_SELLER sectors.
Transforms CALL-E extraction schemas, status codes, and call transcripts
into definitive audit verdicts (PRESENT, GHOST, UNREACHABLE, UNCERTAIN) with cited proof.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional
from muster.models import Verdict, Confidence, CallOutcome, Sector


GHOST_PHRASES = [
    # English Healthcare / Insurer
    r"wrong number",
    r"wrong person",
    r"not in service",
    r"does not exist",
    r"disconnected",
    r"not accepting",
    r"don'?t accept",
    r"stopped accepting",
    r"no longer in[- ]network",
    r"out[- ]of[- ]network",
    r"self[- ]pay only",
    r"not taking new patients",
    r"retired",
    r"no longer practicing",
    r"left the network",
    r"left the clinic",
    r"permanently closed",
    r"closed down",
    r"refused",
    r"not a doctor",
    r"not a clinic",
    # English Marketplace
    r"store is closed",
    r"out of business",
    r"no longer sell",
    r"don'?t sell",
    r"not associated with",
    r"no store here",
    # Hindi / Regional (preserved for backward compatibility)
    r"nahi lete",
    r"band (ho gaya|kar diya|hai)",
    r"band",
    r"galat number",
    r"koi hospital nahi",
    r"not a hospital",
    r"de-empanelled",
]

PRESENT_PHRASES = [
    # English Healthcare / Insurer
    r"in[- ]network",
    r"accepting new patients",
    r"taking new patients",
    r"yes.*accept",
    r"accepting new",
    r"we take (that|your) insurance",
    r"active provider",
    r"schedule an intake",
    r"intake appointment",
    r"currently accepting",
    r"open for new",
    # English Marketplace
    r"store is open",
    r"actively fulfilling",
    r"yes.*in stock",
    r"currently operational",
    r"open regular hours",
    # Hindi / Regional
    r"ha.*admit",
    r"haan.*ayushman",
    r"admitting patients",
    r"aap aa sakte hain",
    r"card leke aao",
]


def extract_cited_quotes(transcript: str, phrases: List[str], max_quotes: int = 2) -> List[str]:
    """Finds the most relevant cited sentences from the transcript matching key audit signals."""
    if not transcript:
        return []

    # Split transcript into sentences or dialog turns
    turns = re.split(r"[\n\r]+|[.!?]\s+", transcript)
    matching_quotes: List[str] = []

    for turn in turns:
        clean_turn = turn.strip()
        if len(clean_turn) < 8:
            continue
        for pattern in phrases:
            if re.search(pattern, clean_turn, re.IGNORECASE):
                if clean_turn not in matching_quotes:
                    matching_quotes.append(clean_turn)
                break
        if len(matching_quotes) >= max_quotes:
            break

    return matching_quotes


def classify_outcome(
    entry_id: str,
    entry_name: str,
    phone: str,
    run_id: str,
    calle_status: str,
    extracted: Dict[str, Any],
    transcript: str = "",
    evidence_provided: List[str] = None,
    duration_seconds: float = 0.0,
    timestamp: str = "",
    sector: Sector = Sector.US_INSURER,
) -> CallOutcome:
    """
    Evaluates raw CALL-E run data and classifies into a CallOutcome.
    Handles US_INSURER, MARKETPLACE_SELLER, and legacy directories resiliently.
    """
    evidence_quotes: List[str] = list(evidence_provided or [])
    stated_reason = extracted.get("stated_reason", "")
    status_upper = calle_status.upper().strip()

    # Check for dead/unallocated carrier indicators
    is_dead_carrier = (
        status_upper in ["INVALID_NUMBER", "UNALLOCATED_NUMBER", "DISCONNECTED"]
        or "does not exist" in transcript.lower()
        or "out of service" in transcript.lower()
        or any("out of service" in str(q).lower() or "does not exist" in str(q).lower() or "disconnected" in str(q).lower() for q in evidence_quotes)
    )

    # Rule 1: No Answer / Busy / Timeout / ByCallee / Delivery Failure -> UNREACHABLE
    if not is_dead_carrier and (
        status_upper in [
            "NO ANSWER", "NO_ANSWER", "BUSY", "TIMEOUT", "UNANSWERED",
            "BYCALLEE", "CANCELLED", "CANCELED", "FAILED", "ERROR"
        ]
        or (duration_seconds == 0.0 and status_upper != "COMPLETED")
    ):
        quotes = evidence_quotes or ["No answer after multiple rings / line busy or unreachable."]
        return CallOutcome(
            entry_id=entry_id,
            entry_name=entry_name,
            phone=phone,
            run_id=run_id,
            calle_status=status_upper,
            verdict=Verdict.UNREACHABLE,
            confidence=Confidence.HIGH,
            confidence_score=0.95,
            evidence_quotes=quotes,
            stated_reason=stated_reason or "Subscriber did not answer after standard ring cycle / line unreachable.",
            extracted=extracted,
            transcript=transcript,
            duration_seconds=duration_seconds,
            timestamp=timestamp,
            sector=sector,
        )

    # Rule 2: Dead Number / Disconnected / Carrier Network Error -> GHOST
    if status_upper in ["INVALID_NUMBER", "UNALLOCATED_NUMBER", "DISCONNECTED"] or is_dead_carrier:
        quotes = evidence_quotes or ["Carrier reported unallocated, invalid, or disconnected phone line."]
        return CallOutcome(
            entry_id=entry_id,
            entry_name=entry_name,
            phone=phone,
            run_id=run_id,
            calle_status=status_upper,
            verdict=Verdict.GHOST,
            confidence=Confidence.HIGH,
            confidence_score=0.98,
            evidence_quotes=quotes,
            stated_reason=stated_reason or "Dead / disconnected phone line listed in public directory.",
            extracted=extracted,
            transcript=transcript,
            duration_seconds=duration_seconds,
            timestamp=timestamp,
            sector=sector,
        )

    reached_human = bool(extracted.get("reached_human", False) or extracted.get("reachable", False))
    operating_status = str(extracted.get("operating_status", "")).lower()

    # Sector specific fields
    # US_INSURER
    in_network = extracted.get("in_network")
    if in_network is None:
        in_network = extracted.get("accepts_scheme")  # alias

    accepting_new_patients = extracted.get("accepting_new_patients")
    if accepting_new_patients is None:
        accepting_new_patients = extracted.get("admitting_patients")  # alias

    # MARKETPLACE_SELLER
    operational = extracted.get("operational")
    sells_product = extracted.get("sells_claimed_product")

    # Check transcript for ghost & present citations
    ghost_citations = extract_cited_quotes(transcript, GHOST_PHRASES)
    present_citations = extract_cited_quotes(transcript, PRESENT_PHRASES)

    # Rule 3: Explicit Wrong Number or Closed -> GHOST
    if operating_status in ["wrong_number", "closed", "permanently_closed", "left_network", "left_scheme", "disconnected"]:
        all_quotes = list(dict.fromkeys(evidence_quotes + ghost_citations))
        reason = stated_reason or f"Entity status reported as '{operating_status}'."
        return CallOutcome(
            entry_id=entry_id,
            entry_name=entry_name,
            phone=phone,
            run_id=run_id,
            calle_status=status_upper,
            verdict=Verdict.GHOST,
            confidence=Confidence.HIGH,
            confidence_score=0.95,
            evidence_quotes=all_quotes or [reason],
            stated_reason=reason,
            extracted=extracted,
            transcript=transcript,
            duration_seconds=duration_seconds,
            timestamp=timestamp,
            sector=sector,
        )

    # Sector 1: US_INSURER evaluation
    if sector == Sector.US_INSURER:
        if in_network is False or accepting_new_patients is False:
            all_quotes = list(dict.fromkeys(evidence_quotes + ghost_citations))
            reason = stated_reason or "Provider explicitly denied being in-network or taking new patients."
            return CallOutcome(
                entry_id=entry_id,
                entry_name=entry_name,
                phone=phone,
                run_id=run_id,
                calle_status=status_upper,
                verdict=Verdict.GHOST,
                confidence=Confidence.HIGH,
                confidence_score=0.95,
                evidence_quotes=all_quotes or [reason],
                stated_reason=reason,
                extracted=extracted,
                transcript=transcript,
                duration_seconds=duration_seconds,
                timestamp=timestamp,
                sector=sector,
            )

        if reached_human and (in_network is True or present_citations) and accepting_new_patients is not False:
            all_quotes = list(dict.fromkeys(evidence_quotes + present_citations))
            return CallOutcome(
                entry_id=entry_id,
                entry_name=entry_name,
                phone=phone,
                run_id=run_id,
                calle_status=status_upper,
                verdict=Verdict.PRESENT,
                confidence=Confidence.HIGH if in_network is True else Confidence.MEDIUM,
                confidence_score=0.96 if in_network is True else 0.85,
                evidence_quotes=all_quotes or ["Reception confirmed in-network status and active patient intake."],
                stated_reason=stated_reason or "Verified: Provider confirms active in-network participation.",
                extracted=extracted,
                transcript=transcript,
                duration_seconds=duration_seconds,
                timestamp=timestamp,
                sector=sector,
            )

    # Sector 2: MARKETPLACE_SELLER evaluation
    if sector == Sector.MARKETPLACE_SELLER:
        if operational is False or sells_product is False:
            all_quotes = list(dict.fromkeys(evidence_quotes + ghost_citations))
            reason = stated_reason or "Merchant stated store is closed or does not sell claimed products."
            return CallOutcome(
                entry_id=entry_id,
                entry_name=entry_name,
                phone=phone,
                run_id=run_id,
                calle_status=status_upper,
                verdict=Verdict.GHOST,
                confidence=Confidence.HIGH,
                confidence_score=0.94,
                evidence_quotes=all_quotes or [reason],
                stated_reason=reason,
                extracted=extracted,
                transcript=transcript,
                duration_seconds=duration_seconds,
                timestamp=timestamp,
                sector=sector,
            )

        if reached_human and (operational is True or present_citations) and sells_product is not False:
            all_quotes = list(dict.fromkeys(evidence_quotes + present_citations))
            return CallOutcome(
                entry_id=entry_id,
                entry_name=entry_name,
                phone=phone,
                run_id=run_id,
                calle_status=status_upper,
                verdict=Verdict.PRESENT,
                confidence=Confidence.HIGH,
                confidence_score=0.95,
                evidence_quotes=all_quotes or ["Merchant confirmed store is open and orders are fulfilling."],
                stated_reason=stated_reason or "Verified: Active merchant operations confirmed.",
                extracted=extracted,
                transcript=transcript,
                duration_seconds=duration_seconds,
                timestamp=timestamp,
                sector=sector,
            )

    # Rule 4: Transcript has explicit ghost citations and no affirmative confirmation
    if ghost_citations and not present_citations and in_network is not True:
        all_quotes = list(dict.fromkeys(evidence_quotes + ghost_citations))
        return CallOutcome(
            entry_id=entry_id,
            entry_name=entry_name,
            phone=phone,
            run_id=run_id,
            calle_status=status_upper,
            verdict=Verdict.GHOST,
            confidence=Confidence.HIGH,
            confidence_score=0.92,
            evidence_quotes=all_quotes,
            stated_reason=stated_reason or "Transcript contains explicit refusal / closure citations.",
            extracted=extracted,
            transcript=transcript,
            duration_seconds=duration_seconds,
            timestamp=timestamp,
            sector=sector,
        )

    # Rule 5: Connected but human wasn't reached (IVR/Voicemail/Machine) -> UNREACHABLE
    if not reached_human and status_upper == "COMPLETED":
        return CallOutcome(
            entry_id=entry_id,
            entry_name=entry_name,
            phone=phone,
            run_id=run_id,
            calle_status=status_upper,
            verdict=Verdict.UNREACHABLE,
            confidence=Confidence.MEDIUM,
            confidence_score=0.75,
            evidence_quotes=evidence_quotes or ["Automated voicemail or answering machine reached."],
            stated_reason=stated_reason or "Call answered by machine without authorized human responder.",
            extracted=extracted,
            transcript=transcript,
            duration_seconds=duration_seconds,
            timestamp=timestamp,
            sector=sector,
        )

    # Fallback: Inconclusive -> UNCERTAIN
    return CallOutcome(
        entry_id=entry_id,
        entry_name=entry_name,
        phone=phone,
        run_id=run_id,
        calle_status=status_upper,
        verdict=Verdict.UNCERTAIN,
        confidence=Confidence.LOW,
        confidence_score=0.50,
        evidence_quotes=evidence_quotes or ["Call ended without definitive confirmation or denial."],
        stated_reason=stated_reason or "Inconclusive dialogue turn or premature disconnection.",
        extracted=extracted,
        transcript=transcript,
        duration_seconds=duration_seconds,
        timestamp=timestamp,
        sector=sector,
    )
