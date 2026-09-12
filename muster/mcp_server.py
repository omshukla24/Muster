"""
FastMCP Server for Muster.
Exposes a single tool `audit_directory` so any external LLM or agent can invoke Muster
to verify directory entries, discover ghost listings, and generate certified evidence.
"""

from __future__ import annotations
import uuid
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from muster.parser import parse_directory
from muster.models import Sector, Verdict
from muster.engine import AuditEngine
from muster.calle_client import CalleClient, MockCalleClient
from muster.report import save_reports

# Initialize FastMCP Server
mcp = FastMCP(
    name="muster",
)


@mcp.tool()
async def audit_directory(
    file_path: str,
    sector: str = "US_INSURER",
    mode: str = "mock",
    goal: Optional[str] = None,
    out_dir: str = "reports",
) -> str:
    """
    Audits a claimed public directory (CSV or JSON) to detect ghost listings and calculate ghost rates.

    Args:
        file_path: Absolute or relative path to CSV or JSON directory file.
        sector: Archetype: 'US_INSURER' (in-network provider) or 'MARKETPLACE_SELLER' (merchant).
        mode: Execution mode: 'mock' (zero-cost simulated rehearsal) or 'live' (real CALL-E calls).
        goal: Optional benign verification question to ask reception.
        out_dir: Directory where compliance reports (CSV, JSON, Markdown) are written.

    Returns:
        A human-readable audit ledger report with headline ghost rate and cited evidence.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: Directory file not found at '{file_path}'"

    entries = parse_directory(path)
    if not entries:
        return f"Error: No valid directory entries could be parsed from '{file_path}'"

    # Validate Sector
    try:
        sec = Sector(sector.upper())
    except Exception:
        sec = Sector.US_INSURER

    is_live = (mode.lower() == "live")
    client = CalleClient() if is_live else MockCalleClient(artificial_delay_sec=0.1)
    engine = AuditEngine(
        client=client,
        concurrency=2,
        default_goal=goal,
        sector=sec,
    )

    job_id = f"mcp-{uuid.uuid4().hex[:6]}"
    job = await engine.run_audit(entries, job_id=job_id, goal=goal)

    # Save reports
    saved = save_reports(job, output_dir=out_dir)

    summary = job.summary
    total = summary.total
    ghosts = summary.ghost_count
    present = summary.present_count
    unreach = summary.unreachable_count
    rate = summary.ghost_rate_pct

    # Derived patient call ratio
    non_ghost_ratio = (total - ghosts) / total if total > 0 else 1
    call_ratio = f"{1 / non_ghost_ratio:.1f}" if non_ghost_ratio > 0 else "∞"
    tier = "DEFECTIVE" if rate > 50 else ("HIGH-RISK" if rate > 25 else ("COMPROMISED" if rate > 10 else "PRIME"))

    # Format result markdown
    lines = [
        f"# Muster Audit Report — {path.name}",
        f"**Headline**: {ghosts} of {total} listings = GHOST ({rate}%)",
        f"**Access Metric**: A patient/customer must contact ~{call_ratio} listings to reach 1 active entity ({tier}).",
        f"**Execution Mode**: {'LIVE CALL-E' if is_live else 'MOCK REHEARSAL'} (Job ID: `{job_id}`)",
        "",
        "## Summary Breakdown",
        f"- Verified Present: **{present}** ({summary.verified_rate_pct}%)",
        f"- Confirmed Ghosts: **{ghosts}** ({summary.ghost_rate_pct}%)",
        f"- Unreachable / Busy: **{unreach}**",
        f"- Uncertain / Inconclusive: **{summary.uncertain_count}**",
        "",
        "## Verified Ledger",
        "| ID | Entity Name | Phone | Verdict | Conf. | Spoken Evidence Quote |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for outcome in job.outcomes:
        quote = outcome.evidence_quotes[0] if outcome.evidence_quotes else outcome.stated_reason
        cleaned_quote = quote.replace("|", "-").replace("\n", " ")
        conf = f"{outcome.confidence.value} ({int(outcome.confidence_score * 100)}%)"
        lines.append(f"| {outcome.entry_id} | {outcome.entry_name} | {outcome.phone} | **{outcome.verdict.value}** | {conf} | \"{cleaned_quote}\" |")

    lines.extend([
        "",
        "## Saved Audit Artifacts",
        f"- CSV: `{saved['csv']}`",
        f"- JSON: `{saved['json']}`",
        f"- Markdown Certificate: `{saved['md']}`",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
