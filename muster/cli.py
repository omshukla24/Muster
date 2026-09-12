"""
Command-line interface for Muster directory auditor.
Usage:
  muster audit sample_data/hospitals_pmjay.json --mode mock
  muster ui --port 8000
"""

from __future__ import annotations
import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from muster.parser import parse_directory
from muster.engine import AuditEngine
from muster.calle_client import CalleClient, MockCalleClient
from muster.report import save_reports
from muster.models import Verdict, Sector


console = Console()


async def run_cli_audit(args):
    path = Path(args.directory)
    if not path.exists():
        console.print(f"[bold red]Error:[/] File not found: {args.directory}")
        sys.exit(1)

    entries = parse_directory(path)
    if not entries:
        console.print(f"[bold red]Error:[/] No valid directory entries found in {args.directory}")
        sys.exit(1)

    job_id = f"job-{uuid.uuid4().hex[:6]}"
    is_live = (args.mode.lower() == "live")
    sector = Sector(args.sector)

    if is_live and not getattr(args, "confirm_live", False):
        console.print("\n[bold red]⚠️  CREDIT GUARD — LIVE CALL-E MODE[/]")
        console.print(f"This will place real telephone calls to [bold]{len(entries)}[/] listings and consume metered credits (~34 credits/min).")
        confirm = console.input("[bold yellow]Type 'LIVE' to confirm and place real calls (or press Enter to cancel): [/]")
        if confirm.strip().upper() != "LIVE":
            console.print("[dim]Aborted live audit. Re-run with --mode mock for zero-cost simulated audit.[/]")
            sys.exit(0)

    client = CalleClient() if is_live else MockCalleClient(artificial_delay_sec=0.2)
    engine = AuditEngine(
        client=client,
        concurrency=args.concurrency,
        default_goal=args.goal,
        sector=sector,
    )

    console.print(Panel.fit(
        f"[bold cyan]Muster Directory Auditor[/] — [yellow]{len(entries)} entries[/]\n"
        f"Mode: [bold {'red' if is_live else 'green'}]{'LIVE CALL-E' if is_live else 'MOCK SIMULATION'}[/] | Job ID: [dim]{job_id}[/]\n"
        f"Target: [bold white]{path.name}[/]",
        border_style="cyan"
    ))

    table = Table(title="Live Audit Ledger", show_lines=True)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Entity Name", style="bold white", width=26)
    table.add_column("Phone", style="cyan", width=15)
    table.add_column("Verdict", width=14)
    table.add_column("Conf.", width=8)
    table.add_column("Cited Evidence", style="italic")

    outcomes = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[yellow]Auditing directory listings...", total=len(entries))

        async for event in engine.run_audit_stream(entries, job_id=job_id, goal=args.goal):
            if event.event_type == "row_resolved" and event.outcome:
                outcomes.append(event.outcome)
                o = event.outcome
                progress.advance(task)

                # Format verdict
                if o.verdict == Verdict.PRESENT:
                    v_str = "[bold green]PRESENT[/]"
                elif o.verdict == Verdict.GHOST:
                    v_str = "[bold red]GHOST[/]"
                elif o.verdict == Verdict.UNREACHABLE:
                    v_str = "[bold yellow]UNREACHABLE[/]"
                else:
                    v_str = "[dim]UNCERTAIN[/]"

                evidence = o.evidence_quotes[0] if o.evidence_quotes else o.stated_reason
                table.add_row(
                    o.entry_id,
                    o.entry_name[:24],
                    o.phone,
                    v_str,
                    f"{o.confidence.value[0]} ({int(o.confidence_score*100)}%)",
                    f'"{evidence[:50]}..."' if len(evidence) > 50 else f'"{evidence}"',
                )

    console.print(table)

    summary = engine.calculate_summary(outcomes, len(entries))
    job = (await engine.run_audit(entries, job_id=job_id, goal=args.goal))
    job.outcomes = outcomes
    job.summary = summary

    # Summary Panel
    console.print(Panel(
        f"[bold]HEADLINE:[/] [bold {'red' if summary.ghost_rate_pct > 30 else 'yellow'}]{summary.headline}[/]\n\n"
        f"  Total Audited: [bold]{summary.total}[/]\n"
        f"  Verified Present: [bold green]{summary.present_count}[/] ({summary.verified_rate_pct}%)\n"
        f"  Confirmed Ghosts: [bold red]{summary.ghost_count}[/] ({summary.ghost_rate_pct}%)\n"
        f"  Unreachable / Dead: [bold yellow]{summary.unreachable_count}[/]\n"
        f"  Uncertain: [bold dim]{summary.uncertain_count}[/]",
        title="[bold green]Audit Summary[/]",
        border_style="green"
    ))

    # Save reports
    saved = save_reports(job, args.out)
    console.print(f"\n[bold green][SUCCESS] Reports saved to:[/] [dim]{args.out}[/]")
    console.print(f"  - CSV:  {saved['csv'].name}")
    console.print(f"  - JSON: {saved['json'].name}")
    console.print(f"  - MD:   {saved['md'].name}\n")


def main():
    parser = argparse.ArgumentParser(description="Muster — Directory Ghost-Rate Auditor powered by CALL-E")
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to run")

    # audit subcommand
    audit_parser = subparsers.add_parser("audit", help="Audit a directory file")
    audit_parser.add_argument("directory", help="Path to CSV or JSON directory file")
    audit_parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="Execution mode (default: mock)")
    audit_parser.add_argument("--out", default="reports", help="Output directory for reports")
    audit_parser.add_argument("--concurrency", type=int, default=2, help="Max parallel calls")
    audit_parser.add_argument("--sector", choices=["US_INSURER", "MARKETPLACE_SELLER"], default="US_INSURER", help="Sector archetype")
    audit_parser.add_argument("--goal", default=None, help="Custom verification question/goal")
    audit_parser.add_argument("--confirm-live", action="store_true", help="Bypass interactive credit-guard confirmation for scripted live runs")

    # ui subcommand
    ui_parser = subparsers.add_parser("ui", help="Launch the web audit ledger dashboard")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host address")
    ui_parser.add_argument("--port", type=int, default=8000, help="Port to bind")

    args = parser.parse_args()

    if args.subcommand == "ui":
        import uvicorn
        console.print(f"[bold cyan]Launching Muster Web Ledger on http://{args.host}:{args.port}...[/]")
        uvicorn.run("muster.app.server:app", host=args.host, port=args.port, reload=False)
    elif args.subcommand == "audit":
        asyncio.run(run_cli_audit(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
