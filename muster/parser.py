"""
Directory parser for Muster audit engine.
Supports CSV and JSON files, normalizing fields and phone numbers into DirectoryEntry models.
"""

from __future__ import annotations
import csv
import io
import json
import re
from pathlib import Path
from typing import List, Union, Dict, Any

from muster.models import DirectoryEntry


def normalize_phone(phone_raw: Any, default_country_code: str = "+91") -> str:
    """
    Normalize arbitrary phone strings into clean E.164 format.
    Example:
      "9876543210" -> "+919876543210"
      "09876543210" -> "+919876543210"
      "+91 98765-43210" -> "+919876543210"
      "+1 (555) 019-2831" -> "+15550192831"
    """
    if not phone_raw:
        return ""
    
    cleaned = str(phone_raw).strip()
    # Remove whitespace, dashes, parentheses, dots
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", cleaned)
    
    if not cleaned:
        return ""

    if cleaned.startswith("+"):
        return cleaned
    
    # Strip leading 0
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    # If standard 10 digit number and default country code given
    if len(cleaned) == 10 and default_country_code:
        cc = default_country_code if default_country_code.startswith("+") else f"+{default_country_code}"
        return f"{cc}{cleaned}"

    # Fallback to prefixing with + if digits only
    if cleaned.isdigit():
        return f"+{cleaned}"
        
    return cleaned


def sanitize_formula_injection(val: Any) -> str:
    """
    Neutralizes CSV formula injection (DDE / command execution attacks in Excel/Sheets).
    Prepends a single quote if the field begins with =, +, -, @, or tabs/returns.
    """
    if val is None:
        return ""
    text = str(val)
    trimmed = text.lstrip(" \t\r\n")
    if text and (text[0] in ("\t", "\r", "\n") or (trimmed and trimmed[0] in ("=", "+", "-", "@"))):
        return f"'{text}"
    return text


def pre_call_phone_sanity_check(entries: List[DirectoryEntry]) -> List[Dict[str, Any]]:
    """
    Pre-call sanity check (Milestone 5):
    Identifies obvious dummy numbers, invalid lengths, or duplicate phone numbers
    mapped to different entities BEFORE placing costly telephony calls.
    Returns a list of anomaly warning dictionaries.
    """
    anomalies: List[Dict[str, Any]] = []
    seen_phones: Dict[str, str] = {}

    for entry in entries:
        phone_digits = re.sub(r"\D", "", entry.phone)
        
        # 1. Length check: E.164 numbers are 10 to 15 digits
        if len(phone_digits) < 10 or len(phone_digits) > 15:
            anomalies.append({
                "entry_id": entry.id,
                "name": entry.name,
                "phone": entry.phone,
                "issue": "INVALID_LENGTH",
                "detail": f"Phone has {len(phone_digits)} digits (expected 10-15)",
            })

        # 2. Obvious dummy/repeated digit patterns (e.g. 0000000000, 5555555555)
        if len(phone_digits) >= 7 and len(set(phone_digits[-7:])) == 1:
            anomalies.append({
                "entry_id": entry.id,
                "name": entry.name,
                "phone": entry.phone,
                "issue": "DUMMY_PATTERN",
                "detail": f"Last 7 digits are identical: {phone_digits[-7:]}",
            })

        # 3. Duplicate phone numbers assigned to different entity names
        if entry.phone in seen_phones:
            prior_name = seen_phones[entry.phone]
            if prior_name.strip().lower() != entry.name.strip().lower():
                anomalies.append({
                    "entry_id": entry.id,
                    "name": entry.name,
                    "phone": entry.phone,
                    "issue": "DUPLICATE_CROSS_ENTITY",
                    "detail": f"Shared phone line with '{prior_name}' (potential fraud/aggregator line)",
                })
        else:
            seen_phones[entry.phone] = entry.name

    return anomalies


def _find_field(row: Dict[str, Any], candidates: List[str], default: str = "") -> str:
    """Case-insensitive dictionary key search matching candidate field names."""
    normalized_row = {k.strip().lower().replace(" ", "_").replace("-", "_"): v for k, v in row.items()}
    for candidate in candidates:
        cand_key = candidate.lower().replace(" ", "_").replace("-", "_")
        if cand_key in normalized_row and normalized_row[cand_key] is not None:
            val = str(normalized_row[cand_key]).strip()
            if val:
                return val
    return default


def parse_directory_data(data: Union[List[Dict[str, Any]], str], is_csv: bool = False) -> List[DirectoryEntry]:
    """
    Parses directory data from either a list of dicts or a raw string (CSV/JSON).
    """
    raw_rows: List[Dict[str, Any]] = []

    if isinstance(data, list):
        raw_rows = data
    elif isinstance(data, str):
        content = data.strip()
        if not content:
            return []
        if is_csv or content.startswith("name") or content.startswith('"') or "," in content.split("\n")[0]:
            reader = csv.DictReader(io.StringIO(content))
            raw_rows = [row for row in reader]
        else:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    raw_rows = parsed
                elif isinstance(parsed, dict) and "entries" in parsed:
                    raw_rows = parsed["entries"]
                else:
                    raise ValueError("JSON must contain an array of directory entries or an 'entries' key.")
            except json.JSONDecodeError as exc:
                # Fallback to CSV attempt
                reader = csv.DictReader(io.StringIO(content))
                raw_rows = [row for row in reader]

    entries: List[DirectoryEntry] = []
    for idx, row in enumerate(raw_rows, start=1):
        name = _find_field(row, ["name", "hospital_name", "provider_name", "doctor_name", "seller_name", "facility", "title"])
        if not name:
            name = f"Directory Entity #{idx}"

        phone_raw = _find_field(row, ["phone", "phone_number", "contact", "mobile", "tel", "telephone", "cell"])
        phone = normalize_phone(phone_raw)

        claimed_status = _find_field(row, ["claimed_status", "status", "empanelled_status", "verification_status", "network_status"], default="Empanelled")
        category = _find_field(row, ["category", "specialty", "type", "facility_type"], default="Healthcare")
        address = _find_field(row, ["address", "location", "city", "state", "district"], default="")
        entry_id = _find_field(row, ["id", "entry_id", "hosp_id", "provider_id"], default=f"entry-{idx:03d}")

        entries.append(
            DirectoryEntry(
                id=entry_id,
                name=name,
                phone=phone,
                claimed_status=claimed_status,
                category=category,
                address=address,
                metadata={k: v for k, v in row.items() if k not in ["id", "name", "phone"]}
            )
        )

    return entries


def parse_directory(file_path: Union[str, Path]) -> List[DirectoryEntry]:
    """
    Parses a CSV or JSON file from the filesystem into a list of DirectoryEntry objects.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Directory file not found at: {file_path}")

    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")

    if suffix == ".json":
        return parse_directory_data(content, is_csv=False)
    elif suffix in [".csv", ".tsv"]:
        return parse_directory_data(content, is_csv=True)
    else:
        # Infer from content
        return parse_directory_data(content)
