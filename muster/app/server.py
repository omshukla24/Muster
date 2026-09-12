"""
FastAPI Server for Muster Audit Ledger.
Provides REST and Server-Sent Events (SSE) endpoints for real-time audit streaming and report downloads.
"""

from __future__ import annotations
import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from muster.models import (
    DirectoryEntry,
    AuditJob,
    AuditSummary,
    CallOutcome,
    AuditProgressEvent,
    Sector,
)
from muster.parser import parse_directory, parse_directory_data
from muster.engine import AuditEngine
from muster.calle_client import CalleClient, MockCalleClient
from muster.report import generate_csv_report, generate_json_report, generate_markdown_report


app = FastAPI(
    title="Muster Audit Ledger API",
    description="Backend API powering the Muster real-time directory ghost-rate auditor.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"

# In-memory job state & event streams
ACTIVE_JOBS: Dict[str, AuditJob] = {}
JOB_EVENT_QUEUES: Dict[str, asyncio.Queue] = {}


class StartAuditRequest(BaseModel):
    entries: List[DirectoryEntry]
    mode: str = "mock"  # "mock" | "live"
    goal: Optional[str] = None
    concurrency: int = 2
    language: str = "en"
    sector: Sector = Sector.US_INSURER


@app.get("/api/auth/status")
def get_auth_status():
    """Checks CALL-E authentication status and credit note."""
    try:
        import subprocess
        proc = subprocess.run(["calle", "auth", "status", "--json"], capture_output=True, text=True, check=False)
        out = proc.stdout.strip()
        data = json.loads(out)
        usable = bool(data.get("usable", False))
        expires = data.get("expires_at", "")
        return {
            "authenticated": usable,
            "status_text": "Authenticated & Ready" if usable else "CLI session expired",
            "expires_at": expires,
            "credits_note": "CALL-E authenticated. Live calls consume credits from your metered quota (~34 credits/min).",
            "raw": data,
        }
    except Exception as exc:
        return {
            "authenticated": False,
            "status_text": "CALL-E CLI unavailable",
            "credits_note": "Mock mode active (0 credits).",
            "error": str(exc),
        }


@app.get("/api/presets")
def get_presets():
    """Lists available sample directories for instant one-click demo runs."""
    return [
        {
            "id": "us_insurer_network",
            "name": "US Health Insurer In-Network Providers (Hero)",
            "count": 12,
            "category": "Healthcare In-Network Providers",
            "sector": "US_INSURER",
            "filename": "us_insurer_network.json",
            "default_goal": "Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients?"
        },
        {
            "id": "marketplace_sellers",
            "name": "Verified Marketplace Merchants",
            "count": 6,
            "category": "E-Commerce Registry",
            "sector": "MARKETPLACE_SELLER",
            "filename": "marketplace_sellers.json",
            "default_goal": "Hello, calling for merchant directory verification. Are you currently operational and fulfilling orders?"
        },
        {
            "id": "therapists_network",
            "name": "Mental Health In-Network Providers",
            "count": 8,
            "category": "Insurer Provider Network",
            "sector": "US_INSURER",
            "filename": "therapists_network.json",
            "default_goal": "Hello, calling to verify your in-network provider listing. Are you currently accepting new insurance patients for therapy?"
        }
    ]


@app.get("/api/presets/{preset_id}")
def load_preset(preset_id: str):
    """Loads directory entries for a chosen preset."""
    file_map = {
        "us_insurer_network": SAMPLE_DATA_DIR / "us_insurer_network.json",
        "marketplace_sellers": SAMPLE_DATA_DIR / "marketplace_sellers.json",
        "therapists_network": SAMPLE_DATA_DIR / "therapists_network.json",
    }
    target = file_map.get(preset_id)
    if not target or not target.exists():
        raise HTTPException(status_code=404, detail="Preset not found.")
    return parse_directory(target)


@app.post("/api/upload")
async def upload_directory(file: UploadFile = File(...)):
    """Uploads and parses arbitrary CSV or JSON directory files."""
    content_bytes = await file.read()
    try:
        content_str = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content_str = content_bytes.decode("latin-1")

    is_csv = file.filename.lower().endswith(".csv") if file.filename else False
    entries = parse_directory_data(content_str, is_csv=is_csv)
    if not entries:
        raise HTTPException(status_code=400, detail="Could not parse any valid directory entries from file.")
    return entries


async def _run_audit_background(
    job_id: str,
    entries: List[DirectoryEntry],
    mode: str,
    goal: Optional[str],
    concurrency: int,
    language: str,
    sector: Sector = Sector.US_INSURER,
):
    queue = JOB_EVENT_QUEUES.get(job_id)
    if not queue:
        return

    is_live = (mode.lower() == "live")
    client = CalleClient() if is_live else MockCalleClient(artificial_delay_sec=0.8)
    engine = AuditEngine(
        client=client,
        concurrency=concurrency,
        language=language,
        sector=sector,
    )

    job = ACTIVE_JOBS[job_id]
    job.status = "RUNNING"

    try:
        async for event in engine.run_audit_stream(entries, job_id=job_id, goal=goal):
            if event.event_type == "row_resolved" and event.outcome:
                job.outcomes.append(event.outcome)
                job.completed_entries = len(job.outcomes)
                job.summary = event.summary
            elif event.event_type == "complete":
                job.status = "COMPLETED"
                job.finished_at = datetime.now().strftime("%H:%M:%S")
                job.summary = event.summary

            await queue.put(event)
    except Exception as exc:
        job.status = "FAILED"
        err_event = AuditProgressEvent(
            job_id=job_id,
            event_type="error",
            message=f"Audit execution crashed: {str(exc)}",
        )
        await queue.put(err_event)
    finally:
        # Signal queue termination
        await queue.put(None)


@app.post("/api/audit/start")
async def start_audit(req: StartAuditRequest, background_tasks: BackgroundTasks):
    """Initializes a new audit job and queues background execution."""
    if not req.entries:
        raise HTTPException(status_code=400, detail="Directory contains zero entries.")

    job_id = f"job-{uuid.uuid4().hex[:6]}"
    queue = asyncio.Queue()
    JOB_EVENT_QUEUES[job_id] = queue

    job = AuditJob(
        job_id=job_id,
        name=f"Audit Job {job_id}",
        mode=req.mode,
        status="PENDING",
        sector=req.sector,
        total_entries=len(req.entries),
        completed_entries=0,
        summary=AuditSummary(total=len(req.entries), sector=req.sector),
        outcomes=[],
        created_at=datetime.now().strftime("%H:%M:%S"),
    )
    ACTIVE_JOBS[job_id] = job

    background_tasks.add_task(
        _run_audit_background,
        job_id=job_id,
        entries=req.entries,
        mode=req.mode,
        goal=req.goal,
        concurrency=req.concurrency,
        language=req.language,
        sector=req.sector,
    )

    return {"job_id": job_id, "mode": req.mode, "total_entries": len(req.entries), "sector": req.sector}


@app.get("/api/audit/events/{job_id}")
async def stream_audit_events(job_id: str):
    """Streams real-time audit progression via Server-Sent Events."""
    queue = JOB_EVENT_QUEUES.get(job_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Job not found or expired.")

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                # End of stream marker
                yield {
                    "event": "done",
                    "data": json.dumps({"status": "done"})
                }
                break
            
            yield {
                "event": "message",
                "data": json.dumps(event.model_dump())
            }

    return EventSourceResponse(event_generator())


@app.get("/api/audit/job/{job_id}")
def get_job(job_id: str):
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/api/audit/report/{job_id}/{fmt}")
def download_report(job_id: str, fmt: str):
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    fmt_lower = fmt.lower()
    if fmt_lower == "csv":
        data = generate_csv_report(job)
        return Response(
            content=data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=muster_audit_{job_id}.csv"}
        )
    elif fmt_lower == "json":
        data = generate_json_report(job)
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=muster_audit_{job_id}.json"}
        )
    elif fmt_lower in ["md", "markdown"]:
        data = generate_markdown_report(job)
        return Response(
            content=data,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=muster_audit_{job_id}.md"}
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Choose csv, json, or md.")


# Mount static directory if it exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "<h1>Muster API Ready</h1><p>Static frontend not built yet.</p>"
