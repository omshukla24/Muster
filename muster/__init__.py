"""
Muster — Directory Ghost-Rate Auditor powered by CALL-E.
Batch-calls directory entries, asks benign qualifying questions,
and certifies PRESENT, GHOST, and UNREACHABLE statuses with cited evidence.
"""

__version__ = "0.1.0"

from muster.models import (
    DirectoryEntry,
    Verdict,
    Confidence,
    CallOutcome,
    AuditSummary,
    AuditJob,
    ExtractSchema,
)
from muster.parser import parse_directory
from muster.classifier import classify_outcome
from muster.engine import AuditEngine
from muster.calle_client import CalleClient, MockCalleClient

__all__ = [
    "DirectoryEntry",
    "Verdict",
    "Confidence",
    "CallOutcome",
    "AuditSummary",
    "AuditJob",
    "ExtractSchema",
    "parse_directory",
    "classify_outcome",
    "AuditEngine",
    "CalleClient",
    "MockCalleClient",
]
