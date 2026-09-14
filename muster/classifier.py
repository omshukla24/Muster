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
    r"\bin[- ]network\b",
    r"\b(we\s+do|we\s+are|we)?\s*accept(ing)?\s+(new\s+)?patients\b",
    r"\btak(e|ing)\s+new\s+patients\b",
    r"\b(do|we)\s+accept\b",
    r"\bwe\s+take\b",
    r"\b(yes|yeah|yep|sure|correct)\b.*accept",
    r"\b(yes|yeah|yep|sure|correct)\b.*in[- ]network",
    r"\baccept(ing)?\s+new\b",
    r"\bwalk[- ]ins?\s+(are\s+)?welcome\b",
    r"we take (that|your) insurance",
    r"active provider",
    r"schedule an intake",
    r"intake appointment",
    r"currently accepting",
    r"open for new",
    r"\bwe\s+(do|are)\b",
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


ASSISTANT_PREFIX_RE = re.compile(
    r"^\s*\[?(assistant|agent|call[- ]?e|bot|caller|ai)\]?[:\s]",
    re.IGNORECASE,
)

CALLEE_PREFIX_RE = re.compile(
    r"^\s*\[?(user|callee|reception|receptionist|respondent|operator|doctor|clinic|staff|merchant|seller)\]?[:\s]*",
    re.IGNORECASE,
)

PROMPT_BOILERPLATE_RE = re.compile(
    r"(calling to verify|need to confirm|are you currently|can you hear me|directory network status|directory verification|taking new patients\?|in-network\?)",
    re.IGNORECASE,
)


def get_callee_turns(transcript: str) -> List[str]:
    """Extracts only dialogue turns or statements spoken by the callee (user/receptionist/operator).
    Strictly filters out assistant/agent questions, DTMF tones, and caller prompts."""
    if not transcript:
        return []

    lines = re.split(r"[\r\n]+", transcript)
    callee_turns: List[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue

        # Skip DTMF tones like [DTMF]1
        if re.search(r"\[DTMF\]", line, re.IGNORECASE):
            continue

        # Handle inline dialog transitions like "Agent: ... Reception: ..."
        segments = re.split(
            r"(?=(?:\[?(?:assistant|agent|call[- ]?e|bot|caller|ai|user|callee|reception|receptionist|respondent|operator)\]?[:\s]))",
            line,
            flags=re.IGNORECASE,
        )

        for seg in segments:
            clean_seg = seg.strip()
            if not clean_seg:
                continue

            # If spoken by assistant/agent, discard immediately
            if ASSISTANT_PREFIX_RE.match(clean_seg):
                continue

            # Strip callee prefix
            stripped = CALLEE_PREFIX_RE.sub("", clean_seg).strip()

            # Discard if it contains caller audit boilerplate
            if PROMPT_BOILERPLATE_RE.search(stripped):
                continue

            if len(stripped) >= 4:
                callee_turns.append(stripped)

    return callee_turns


def extract_cited_quotes(transcript: str, phrases: List[str], max_quotes: int = 2) -> List[str]:
    """Finds the most relevant cited sentences from the callee's speech in the transcript."""
    if not transcript:
        return []

    callee_turns = get_callee_turns(transcript)
    matching_quotes: List[str] = []

    for turn in callee_turns:
        clean_turn = turn.strip()
        if not clean_turn or PROMPT_BOILERPLATE_RE.search(clean_turn):
            continue

        # 1. Test the complete callee turn first (preserves context like "Yes. We do accept new patients.")
        matched_in_turn = False
        for pattern in phrases:
            if re.search(pattern, clean_turn, re.IGNORECASE):
                if clean_turn not in matching_quotes:
                    matching_quotes.append(clean_turn)
                matched_in_turn = True
                break
        if matched_in_turn:
            if len(matching_quotes) >= max_quotes:
                return matching_quotes
            continue

        # 2. If turn didn't match as a whole, test individual clauses
        sentences = re.split(r"[.!?]\s+", clean_turn)
        for sent in sentences:
            clean_sent = sent.strip()
            if len(clean_sent) < 4:
                continue
            if PROMPT_BOILERPLATE_RE.search(clean_sent):
                continue
            for pattern in phrases:
                if re.search(pattern, clean_sent, re.IGNORECASE):
                    if clean_sent not in matching_quotes:
                        matching_quotes.append(clean_sent)
                    break
            if len(matching_quotes) >= max_quotes:
                return matching_quotes

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
    # Sanitize evidence quotes so assistant prompt questions are never cited as proof
    evidence_quotes: List[str] = [
        str(q) for q in (evidence_provided or [])
        if not PROMPT_BOILERPLATE_RE.search(str(q)) and not ASSISTANT_PREFIX_RE.search(str(q))
    ]
    stated_reason = extracted.get("stated_reason", "")
    status_upper = calle_status.upper().strip()

    # Coerce string booleans from LLM extraction schemas
    def _coerce_bool(val: Any) -> Optional[bool]:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            v_low = val.strip().lower()
            if v_low in ("true", "yes", "1"):
                return True
            if v_low in ("false", "no", "0"):
                return False
        return None

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
    in_network = _coerce_bool(extracted.get("in_network"))
    if in_network is None:
        in_network = _coerce_bool(extracted.get("accepts_scheme"))  # alias

    accepting_new_patients = _coerce_bool(extracted.get("accepting_new_patients"))
    if accepting_new_patients is None:
        accepting_new_patients = _coerce_bool(extracted.get("admitting_patients"))  # alias

    # MARKETPLACE_SELLER
    operational = _coerce_bool(extracted.get("operational"))
    sells_product = _coerce_bool(extracted.get("sells_claimed_product"))

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
    # Human or operator answered, but conversation ended before verification was confirmed
    callee_turns = get_callee_turns(transcript)
    informative_callee_turns = [
        t for t in callee_turns
        if not re.search(r"press \d|for English|please hold|to continue|all other languages", t, re.IGNORECASE)
    ]
    greet_quote = informative_callee_turns[0] if informative_callee_turns else (callee_turns[0] if callee_turns else "")

    if reached_human and greet_quote:
        reason = f"Operator answered ('{greet_quote}'), but disconnected before confirming in-network participation."
        quotes = evidence_quotes or [f'Operator answered: "{greet_quote}" — call disconnected before verification.']
    elif reached_human:
        reason = stated_reason or "Call answered by operator or receptionist, but disconnected before question was answered."
        quotes = evidence_quotes or ["Operator answered, but call ended before in-network verification was provided."]
    else:
        reason = stated_reason or "Inconclusive dialogue turn or premature disconnection."
        quotes = evidence_quotes or ["Call ended without definitive confirmation or denial."]

    return CallOutcome(
        entry_id=entry_id,
        entry_name=entry_name,
        phone=phone,
        run_id=run_id,
        calle_status=status_upper,
        verdict=Verdict.UNCERTAIN,
        confidence=Confidence.LOW,
        confidence_score=0.50,
        evidence_quotes=quotes,
        stated_reason=reason,
        extracted=extracted,
        transcript=transcript,
        duration_seconds=duration_seconds,
        timestamp=timestamp,
        sector=sector,
    )
