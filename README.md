# 📡 Muster — Directory Ghost-Rate Auditor powered by CALL-E

> **An offline batch verification engine and reusable Agent Skill that calls institutional directories to detect "ghost" listings, extract cited transcript proof, and calculate definitive ghost rates.**

[![Test Suite](https://img.shields.io/badge/pytest-30%20passed-emerald)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![CALL-E](https://img.shields.io/badge/powered%20by-CALL--E%20v0.5.1-indigo)](https://github.com/CALLE-AI/awesome-phone-call-agents)
[![FastMCP](https://img.shields.io/badge/MCP-FastMCP%20Server-teal)](muster/mcp_server.py)
[![License](https://img.shields.io/badge/license-MIT-slate)](LICENSE)

---

## 💡 The Problem: Institutional "Ghost Networks"

Insurance provider networks claim hundreds of in-network therapists and doctors. Government health portals list thousands of "empanelled" hospitals. Marketplaces advertise verified merchants. 

In reality, **30% to 70% of these listings are ghosts**:
- Dead or disconnected carrier lines.
- Private mobile numbers belonging to confused strangers.
- Facilities that withdrew from schemes months ago due to unpaid claims.
- Facilities that refuse to admit scheme patients.

When a citizen in a medical crisis or a patient in distress looks up an "in-network" provider, they are forced to make 10 frantic phone calls, only to discover ghost listing after ghost listing.

**Muster solves this by automating the audit offline.** It batch-calls every listing through **CALL-E**, asks **ONE benign qualifying question**, extracts structured operational signals, and returns each entry as **PRESENT**, **GHOST**, or **UNREACHABLE** — each backed by a cited transcript quote and a confidence score — ending on an institutional **Ghost Rate** (e.g., *"7 of 12 listed = GHOST, 58.3%"*) and real-world access metric (*"A patient must call ~2.4 listings to reach 1 real provider"*).

---

## 🏆 Key Features

1. **Reusable CALL-E Agent Skill (`skills/muster/`)**:
   - The primary pull request deliverable for `github.com/CALLE-AI/awesome-phone-call-agents`.
   - Includes standard `SKILL.md` frontmatter, parameter documentation, and CLI entrypoint.
2. **FastMCP Server (`muster/mcp_server.py`)**:
   - Exposes `audit_directory(file_path, sector, mode)` so any agent or MCP client can run Muster.
3. **Framework-Agnostic Python Audit Engine (`muster/`)**:
   - Directory parsing (CSV & JSON) with E.164 phone normalization.
   - Batch concurrency management.
   - Pure, deterministic classifier mapping structured extracts & transcripts to verdicts (`PRESENT`, `GHOST`, `UNREACHABLE`, `UNCERTAIN`).
   - Statistical Ghost-Rate and verification percentage calculations.
   - Defensive security: CSV formula-injection sanitizer (`= + - @`) and pre-call phone anomaly detection.
4. **Interactive Live Web Audit Ledger (`muster/app/`)**:
   - Full-bleed responsive UI matching the v2 design lock (`tokens.css`).
   - Centerpiece dark switchboard network with pulse waves, node tooltips, and bidirectional highlighting.
   - Rehearsal speed controls (`1x`, `2x`, `Instant`) and pause/resume.
   - Credit-guard modal protecting live CALL-E quota.
   - "The Reveal" finale: ghost nodes crack and drop away.
   - Real-time Server-Sent Events (SSE) streaming row-by-row call progress.
   - Multi-format compliance export: **CSV**, **JSON**, and **Markdown Audit Certificates**.
5. **Dual Execution Modes**:
   - **Mock Rehearsal Mode**: Zero-cost deterministic simulator with rich transcripts for rehearsals and UI demos without burning CALL-E credits.
   - **Live CALL-E Mode**: Integrates directly with the local `calle` CLI (`calle call start` -> poll `calle call status`).
6. **Comprehensive Unit Test Suite**:
   - 30 automated tests covering phone normalization, classifier edge cases, math precision, and batch streaming with a zero-live-call guarantee.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+
- `calle` CLI installed and authenticated:
  ```bash
  calle auth status
  ```

### Installation
```bash
git clone https://github.com/CALLE-AI/awesome-phone-call-agents.git
cd "Call E"
pip install -e .
```

---

## 💻 Usage

### 1. Launch the Live Web Audit Ledger
```bash
python -m muster.cli ui --port 8000
# or: uvicorn muster.app.server:app --port 8000
```
Open **`http://127.0.0.1:8000`** in your browser. Choose a target directory, select your mode, and click **"Run Batch Audit"**.

### 2. Run via Terminal CLI
```bash
# Offline Mock Rehearsal (0 credits used)
python -m muster.cli audit sample_data/hospitals_pmjay.json --mode mock --out reports/

# Live Phone Audit via CALL-E
python -m muster.cli audit sample_data/hospitals_pmjay.json --mode live --concurrency 2 --out reports/
```

### 3. Run as an Agent Skill
```bash
python skills/muster/scripts/run_audit.py sample_data/hospitals_pmjay.json --mode mock
```

---

## 🧪 Testing

Run the full automated test suite:
```bash
pytest tests/ -v
```
Output:
```text
tests/test_calle_client.py::test_calle_client_environment_attribution PASSED
tests/test_calle_client.py::test_mock_calle_client_scenarios PASSED
tests/test_classifier.py::test_classify_present_clear PASSED
tests/test_classifier.py::test_classify_ghost_refused_scheme PASSED
tests/test_classifier.py::test_classify_ghost_wrong_number PASSED
tests/test_classifier.py::test_classify_ghost_dead_carrier_line PASSED
tests/test_classifier.py::test_classify_unreachable_no_answer PASSED
tests/test_classifier.py::test_classify_unreachable_ivr_loop PASSED
tests/test_classifier.py::test_extract_cited_quotes_matching PASSED
tests/test_engine.py::test_engine_run_audit_stream_order PASSED
tests/test_engine.py::test_engine_run_audit_and_reports PASSED
tests/test_ghost_rate.py::test_ghost_rate_typical_distribution PASSED
tests/test_parser.py::test_normalize_phone_formats PASSED
============================= 21 passed in 0.10s ==============================
```

---

## 📊 Sample Audit Output

```text
+------------------------------- Audit Summary -------------------------------+
| HEADLINE: 7 of 12 audited = GHOST (58.3%)                                   |
|                                                                             |
|   Total Audited: 12                                                         |
|   Verified Present: 4 (33.3%)                                               |
|   Confirmed Ghosts: 7 (58.3%)                                               |
|   Unreachable / Dead: 1                                                     |
|   Uncertain: 0                                                              |
+-----------------------------------------------------------------------------+
```

---

## 🛡️ Guardrails & Ethical Boundaries

- **Benign Qualifying Questions**: Strictly verifies directory presence and active admissions/operations. Never inquires into patient case histories, personal identities, or financial credentials.
- **Rate-Limited Concurrency**: Defaults to 2 parallel calls to prevent congestion on healthcare and clinic lines.
- **Attribution Environment**: Automatically sets `CALLE_SOURCE=skills_sh`, `CALLE_INTEGRATION=skills_sh_skill`, and `CALLE_INTEGRATION_VERSION=0.1.0`.

---

## ⚖️ License
MIT © 2026 Muster Contributors.
