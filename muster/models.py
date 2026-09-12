"""
Domain models and schemas for Muster audit engine.
Supports two focused sector archetypes: US_INSURER and MARKETPLACE_SELLER.
"""

from __future__ import annotations
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class Sector(str, Enum):
    US_INSURER = "US_INSURER"
    MARKETPLACE_SELLER = "MARKETPLACE_SELLER"


class Verdict(str, Enum):
    PRESENT = "PRESENT"
    GHOST = "GHOST"
    UNREACHABLE = "UNREACHABLE"
    UNCERTAIN = "UNCERTAIN"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DirectoryEntry(BaseModel):
    id: str = Field(..., description="Unique entry ID")
    name: str = Field(..., description="Entity name (e.g. Doctor, Clinic, or Merchant)")
    phone: str = Field(..., description="Destination phone number in E.164 format")
    claimed_status: str = Field("In-Network", description="Status claimed by the directory")
    category: Optional[str] = Field("Healthcare", description="Entity category/specialty")
    address: Optional[str] = Field("", description="Claimed physical location or city")
    sector: Sector = Field(Sector.US_INSURER, description="Sector archetype")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary attributes")


# Generic extract schema covering both US_INSURER and MARKETPLACE_SELLER
class ExtractSchema(BaseModel):
    # Common
    reached_human: bool = Field(False, description="Whether an authorized human responder was reached")
    stated_reason: Optional[str] = Field(None, description="Explanation or quote from responder")

    # US_INSURER specific
    in_network: Optional[bool] = Field(None, description="Whether provider confirms being in-network")
    accepting_new_patients: Optional[bool] = Field(None, description="Whether provider is accepting new patients")

    # MARKETPLACE_SELLER specific
    reachable: Optional[bool] = Field(None, description="Whether merchant is reachable")
    operational: Optional[bool] = Field(None, description="Whether merchant is actively operational")
    sells_claimed_product: Optional[bool] = Field(None, description="Whether merchant sells claimed inventory")

    # Legacy alias support for backward compatibility with tests/existing data
    accepts_scheme: Optional[bool] = Field(None, description="Legacy alias for in_network")
    admitting_patients: Optional[bool] = Field(None, description="Legacy alias for accepting_new_patients")
    operating_status: Optional[str] = Field(None, description="active, closed, wrong_number, left_network")


class CallOutcome(BaseModel):
    entry_id: str
    entry_name: str
    phone: str
    run_id: str
    calle_status: str
    verdict: Verdict
    confidence: Confidence
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evidence_quotes: List[str] = Field(default_factory=list)
    stated_reason: str = ""
    extracted: Dict[str, Any] = Field(default_factory=dict)
    transcript: str = ""
    duration_seconds: float = 0.0
    timestamp: str = ""
    sector: Sector = Sector.US_INSURER


class AuditSummary(BaseModel):
    total: int = 0
    completed: int = 0
    present_count: int = 0
    ghost_count: int = 0
    unreachable_count: int = 0
    uncertain_count: int = 0
    ghost_rate_pct: float = 0.0
    verified_rate_pct: float = 0.0
    avg_duration_sec: float = 0.0
    headline: str = ""
    sector: Sector = Sector.US_INSURER


class AuditJob(BaseModel):
    job_id: str
    name: str
    mode: str = "mock"  # "mock" | "live"
    status: str = "PENDING"  # PENDING | RUNNING | COMPLETED | FAILED
    sector: Sector = Sector.US_INSURER
    total_entries: int = 0
    completed_entries: int = 0
    summary: Optional[AuditSummary] = None
    outcomes: List[CallOutcome] = Field(default_factory=list)
    created_at: str = ""
    finished_at: Optional[str] = None


class AuditProgressEvent(BaseModel):
    job_id: str
    event_type: str  # "start" | "row_queued" | "row_calling" | "row_analyzing" | "row_resolved" | "complete" | "error"
    entry_id: Optional[str] = None
    outcome: Optional[CallOutcome] = None
    summary: Optional[AuditSummary] = None
    message: str = ""
    progress_pct: float = 0.0


SECTOR_DEFAULTS = {
    Sector.US_INSURER: {
        "name": "US Health Insurer Provider Roll",
        "language": "en",
        "default_goal": "Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients?",
    },
    Sector.MARKETPLACE_SELLER: {
        "name": "Verified Marketplace Merchant Roll",
        "language": "en",
        "default_goal": "Hello, calling for merchant directory verification. Are you currently operational and fulfilling orders for your listed store?",
    },
}
