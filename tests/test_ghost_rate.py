"""
Unit tests for Ghost-Rate statistical calculations and summary metric precision.
"""

import pytest
from muster.models import CallOutcome, Verdict, Confidence
from muster.engine import AuditEngine


def _make_outcome(verdict: Verdict, duration: float = 10.0) -> CallOutcome:
    return CallOutcome(
        entry_id="test-id",
        entry_name="Test Entity",
        phone="+919876543200",
        run_id="run-1",
        calle_status="COMPLETED",
        verdict=verdict,
        confidence=Confidence.HIGH,
        confidence_score=0.9,
        duration_seconds=duration,
    )


def test_ghost_rate_typical_distribution():
    engine = AuditEngine()
    outcomes = [
        _make_outcome(Verdict.PRESENT),
        _make_outcome(Verdict.PRESENT),
        _make_outcome(Verdict.PRESENT),
        _make_outcome(Verdict.PRESENT),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.GHOST),  # 8 ghosts out of 12
    ]
    summary = engine.calculate_summary(outcomes, total_entries=12)
    assert summary.total == 12
    assert summary.completed == 12
    assert summary.ghost_count == 8
    assert summary.present_count == 4
    assert summary.ghost_rate_pct == 66.7
    assert summary.verified_rate_pct == 33.3
    assert "8 of 12 audited = GHOST (66.7%)" in summary.headline


def test_ghost_rate_all_ghosts():
    engine = AuditEngine()
    outcomes = [_make_outcome(Verdict.GHOST) for _ in range(5)]
    summary = engine.calculate_summary(outcomes, total_entries=5)
    assert summary.ghost_count == 5
    assert summary.ghost_rate_pct == 100.0
    assert summary.verified_rate_pct == 0.0


def test_ghost_rate_zero_ghosts():
    engine = AuditEngine()
    outcomes = [_make_outcome(Verdict.PRESENT) for _ in range(4)]
    summary = engine.calculate_summary(outcomes, total_entries=4)
    assert summary.ghost_count == 0
    assert summary.ghost_rate_pct == 0.0
    assert summary.verified_rate_pct == 100.0


def test_ghost_rate_empty_outcomes():
    engine = AuditEngine()
    summary = engine.calculate_summary([], total_entries=10)
    assert summary.completed == 0
    assert summary.ghost_rate_pct == 0.0
    assert summary.verified_rate_pct == 0.0
    assert "in progress" in summary.headline.lower()


def test_ghost_rate_unreachable_inclusion():
    engine = AuditEngine()
    outcomes = [
        _make_outcome(Verdict.PRESENT),
        _make_outcome(Verdict.GHOST),
        _make_outcome(Verdict.UNREACHABLE),
        _make_outcome(Verdict.UNCERTAIN),
    ]
    summary = engine.calculate_summary(outcomes, total_entries=4)
    assert summary.completed == 4
    assert summary.unreachable_count == 1
    assert summary.uncertain_count == 1
    assert summary.ghost_count == 1
    assert summary.ghost_rate_pct == 25.0
