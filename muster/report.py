"""
Audit Report Generator for Muster.
Exports audit outcomes into CSV, JSON, and formatted Markdown compliance summaries.
"""

from __future__ import annotations
import csv
import io
import json
from pathlib import Path
from typing import Union

from muster.models import AuditJob, AuditSummary


def _sanitize_csv_cell(val: Any) -> Any:
    """Neutralizes formula injection triggers (=, +, -, @) in CSV cell export."""
    if isinstance(val, str) and val:
        trimmed = val.lstrip(" \t\r\n")
        if val[0] in ("\t", "\r", "\n") or (trimmed and trimmed[0] in ("=", "+", "-", "@")):
            return f"'{val}"
    return val


def generate_csv_report(job: AuditJob) -> str:
    """Produces a clean CSV string of the audit outcomes with cited evidence."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Entry ID",
        "Entity Name",
        "Phone",
        "Verdict",
        "Confidence",
        "Confidence Score",
        "Reason / Summary",
        "Cited Evidence Quote",
        "CALL-E Status",
        "Duration (s)",
        "Timestamp",
    ])

    for outcome in job.outcomes:
        cited_quote = " | ".join(outcome.evidence_quotes) if outcome.evidence_quotes else ""
        row = [
            outcome.entry_id,
            outcome.entry_name,
            outcome.phone,
            outcome.verdict.value,
            outcome.confidence.value,
            f"{outcome.confidence_score:.2f}",
            outcome.stated_reason,
            cited_quote,
            outcome.calle_status,
            f"{outcome.duration_seconds:.1f}",
            outcome.timestamp,
        ]
        writer.writerow([_sanitize_csv_cell(c) for c in row])

    return output.getvalue()


def generate_json_report(job: AuditJob) -> str:
    """Produces indented JSON string of the audit job and complete outcome transcripts."""
    return json.dumps(job.model_dump(), indent=2)


def generate_markdown_report(job: AuditJob) -> str:
    """Produces an executive Markdown audit report with methodology, stats, and evidence."""
    s = job.summary or AuditSummary()
    
    md_lines = [
        f"# 📋 MUSTER DIRECTORY AUDIT REPORT",
        f"> **Auditor**: Muster (Autonomous Agent Skill powered by CALL-E)  ",
        f"> **Job ID**: `{job.job_id}` | **Mode**: `{job.mode.upper()}` | **Timestamp**: `{job.finished_at or job.created_at}`",
        "",
        "## 1. Executive Summary",
        f"**Headline**: **{s.headline}**",
        "",
        f"Muster batch-audited **{s.total} listings** from the target institutional directory by placing real verification phone calls via CALL-E. Each listing was queried with a benign qualifying question to certify active operations and empanelment.",
        "",
        "| Metric | Count | Percentage |",
        "| :--- | :--- | :--- |",
        f"| **Total Directory Listings** | **{s.total}** | 100.0% |",
        f"| **Audited Completed** | **{s.completed}** | {(s.completed/s.total*100):.1f}% |",
        f"| 🚨 **Confirmed GHOST Listings** | **{s.ghost_count}** | **{s.ghost_rate_pct}%** |",
        f"| ✅ **Verified PRESENT Listings** | **{s.present_count}** | **{s.verified_rate_pct}%** |",
        f"| ⚠️ **Unreachable / No Answer** | **{s.unreachable_count}** | {((s.unreachable_count/s.completed*100) if s.completed else 0):.1f}% |",
        f"| ❓ **Uncertain / Interrupted** | **{s.uncertain_count}** | {((s.uncertain_count/s.completed*100) if s.completed else 0):.1f}% |",
        "",
        "## 2. Directory Audit Ledger",
        "",
        "| ID | Entity Name | Phone | Verdict | Confidence | Cited Evidence / Proof |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for o in job.outcomes:
        badge = "✅ **PRESENT**" if o.verdict.value == "PRESENT" else ("🚨 **GHOST**" if o.verdict.value == "GHOST" else f"⚠️ {o.verdict.value}")
        quote = o.evidence_quotes[0] if o.evidence_quotes else o.stated_reason
        # Escape pipe in quote
        quote_safe = quote.replace("|", "/")
        md_lines.append(f"| `{o.entry_id}` | **{o.entry_name}** | `{o.phone}` | {badge} | {o.confidence.value} ({o.confidence_score:.0%}) | *\"{quote_safe}\"* |")

    md_lines.extend([
        "",
        "## 3. Methodology & Verification Standards",
        "- **Tooling**: Voice qualification executed using CALL-E phone agent with structured schema extraction (`reached_human`, `accepts_scheme`, `admitting_patients`).",
        "- **Classification Standard**:",
        "  - **PRESENT**: Verified human respondent confirmed active status and patient admissions.",
        "  - **GHOST**: Respondent explicitly stated they withdrew/stopped taking the scheme, dead carrier line, or wrong entity reached.",
        "  - **UNREACHABLE**: No response after standard ring cycles or automated answering loop.",
        "- **Zero Secrets**: No sensitive patient data or case details requested. Purely non-invasive directory integrity check.",
        "",
        "---",
        "*Report certified by Muster Audit Engine.*",
    ])

    return "\n".join(md_lines)


def save_reports(job: AuditJob, output_dir: Union[str, Path]) -> dict[str, Path]:
    """Saves CSV, JSON, and MD reports to the specified directory."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    csv_file = out_path / f"muster_audit_{job.job_id}.csv"
    json_file = out_path / f"muster_audit_{job.job_id}.json"
    md_file = out_path / f"muster_audit_{job.job_id}.md"

    csv_file.write_text(generate_csv_report(job), encoding="utf-8")
    json_file.write_text(generate_json_report(job), encoding="utf-8")
    md_file.write_text(generate_markdown_report(job), encoding="utf-8")

    return {
        "csv": csv_file,
        "json": json_file,
        "md": md_file,
    }
