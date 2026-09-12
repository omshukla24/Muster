"""
Unit tests for full batch audit engine orchestration and event streaming.
"""

import pytest
import tempfile
from pathlib import Path

from muster.engine import AuditEngine
from muster.calle_client import MockCalleClient
from muster.parser import parse_directory_data
from muster.models import Verdict
from muster.report import generate_csv_report, generate_markdown_report, save_reports


@pytest.mark.asyncio
async def test_engine_run_audit_stream_order():
    raw_csv = """name,phone,claimed_status
Apex Hospital,+919876543201,Empanelled
Defunct Clinic,+919876543200,Empanelled
"""
    entries = parse_directory_data(raw_csv, is_csv=True)
    mock_client = MockCalleClient(artificial_delay_sec=0.0)
    engine = AuditEngine(client=mock_client, concurrency=2)

    events = []
    async for event in engine.run_audit_stream(entries, job_id="test-job-001"):
        events.append(event)

    # Verify event sequencing
    assert len(events) >= 3
    assert events[0].event_type == "start"
    assert events[-1].event_type == "complete"

    resolved_events = [e for e in events if e.event_type == "row_resolved"]
    assert len(resolved_events) == 2

    # Check that summary aggregates
    final_event = events[-1]
    assert final_event.summary is not None
    assert final_event.summary.total == 2
    assert final_event.summary.completed == 2


@pytest.mark.asyncio
async def test_engine_run_audit_and_reports():
    raw_json = """[
        {"name": "Hospital One", "phone": "+919876543201", "claimed_status": "Empanelled"},
        {"name": "Hospital Two", "phone": "+919876543200", "claimed_status": "Empanelled"}
    ]"""
    entries = parse_directory_data(raw_json)
    mock_client = MockCalleClient(artificial_delay_sec=0.0)
    engine = AuditEngine(client=mock_client)

    job = await engine.run_audit(entries, job_id="job-test-reports")
    assert job.status == "COMPLETED"
    assert len(job.outcomes) == 2

    csv_out = generate_csv_report(job)
    assert "Entry ID" in csv_out
    assert "Hospital One" in csv_out

    md_out = generate_markdown_report(job)
    assert "# 📋 MUSTER DIRECTORY AUDIT REPORT" in md_out
    assert "Executive Summary" in md_out

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved = save_reports(job, tmp_dir)
        assert Path(saved["csv"]).exists()
        assert Path(saved["json"]).exists()
        assert Path(saved["md"]).exists()
