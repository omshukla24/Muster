"""
Unit tests for Muster directory parser and phone normalization.
"""

import pytest
from muster.parser import normalize_phone, parse_directory_data, _find_field
from muster.models import DirectoryEntry


def test_normalize_phone_formats():
    # 10-digit Indian number without prefix
    assert normalize_phone("9876543210") == "+919876543210"
    # Leading zero 11-digit
    assert normalize_phone("09876543210") == "+919876543210"
    # Dashes and spaces
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    # International number
    assert normalize_phone("+1 (555) 234-5678") == "+15552345678"
    # Empty string or None
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_parse_directory_csv_string():
    csv_raw = """name,phone,claimed_status,category,address
City Hospital,9876543201,Empanelled,General,Delhi
Apollo Clinic,+919876543202,Empanelled,Cardiology,Mumbai
"""
    entries = parse_directory_data(csv_raw, is_csv=True)
    assert len(entries) == 2
    assert entries[0].name == "City Hospital"
    assert entries[0].phone == "+919876543201"
    assert entries[0].claimed_status == "Empanelled"
    assert entries[1].name == "Apollo Clinic"
    assert entries[1].phone == "+919876543202"


def test_parse_directory_json_string():
    json_raw = """[
        {"id": "H-1", "hospital_name": "Metro Hospital", "contact": "9876543201", "status": "In-Network"},
        {"id": "H-2", "hospital_name": "Care Clinic", "contact": "+919876543202", "status": "In-Network"}
    ]"""
    entries = parse_directory_data(json_raw)
    assert len(entries) == 2
    assert entries[0].id == "H-1"
    assert entries[0].name == "Metro Hospital"
    assert entries[0].phone == "+919876543201"
    assert entries[0].claimed_status == "In-Network"


def test_parse_directory_missing_fields_defaults():
    csv_raw = "hospital_name,phone\nFortis,9876543201\n"
    entries = parse_directory_data(csv_raw, is_csv=True)
    assert len(entries) == 1
    assert entries[0].name == "Fortis"
    assert entries[0].id == "entry-001"
    assert entries[0].claimed_status == "Empanelled"
    assert entries[0].category == "Healthcare"


def test_empty_directory_handling():
    assert parse_directory_data("") == []
    assert parse_directory_data("   ") == []
    assert parse_directory_data("[]") == []
