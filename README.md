# Muster

Muster checks whether a directory that someone *claims* is real actually is — an insurer's in-network doctor list, a marketplace's "verified" sellers — by calling every listing with [CALL-E](https://www.calle.ai) and asking one plain question. Each entry comes back as **Present**, **Ghost**, **Unreachable**, or **Uncertain**, with the spoken line that proves it and a headline ghost rate.

Provider directories are often padded with numbers that ring dead, reach the wrong business, or belong to a doctor who left the plan months ago — "ghost networks." A patient usually finds out only after the tenth dead call. Muster makes those calls up front and hands back the evidence.

## How it works

1. Load a directory (CSV or JSON) of names and phone numbers.
2. Muster calls each one through CALL-E and asks a single benign question — e.g. *"Are you currently in-network and accepting new patients?"*
3. CALL-E returns a transcript and a structured read of the conversation.
4. A classifier turns that into a verdict, a confidence score, and the quote it relied on.
5. You get a live ledger in the browser and downloadable CSV / JSON / Markdown reports.

There are two modes. **Mock** is deterministic, places no calls, and spends nothing — it's for development and for rehearsing the demo. **Live** places real CALL-E calls and is kept behind a confirmation step.

## Quick start

```bash
pip install -e .

# Web ledger — then open http://127.0.0.1:8000
python -m muster.cli ui --port 8000

# CLI audit, mock (free, no calls)
python -m muster.cli audit sample_data/us_insurer_network.json --mode mock

# CLI audit, live (places real calls — prompts for confirmation first)
python -m muster.cli audit sample_data/us_insurer_network.json --mode live

# Tests
pytest
```

## Use it from another agent

Muster ships as a reusable skill under `skills/muster/` and as a FastMCP tool, so any agent can call it:

```python
from muster.mcp_server import audit_directory

report = await audit_directory(
    "sample_data/us_insurer_network.json",
    sector="US_INSURER",
    mode="mock",
)
```

The skill and `skills/muster/scripts/run_audit.py` follow the layout used by [awesome-phone-call-agents](https://github.com/CALLE-AI/awesome-phone-call-agents).

## Verdicts

- **Present** — a person confirmed the listing is active and taking patients or orders.
- **Ghost** — dead line, wrong business, or they said they left the network / closed down.
- **Unreachable** — rang out, busy, or voicemail with no human.
- **Uncertain** — the call didn't settle it either way.

Each verdict carries a confidence score and the verbatim quote behind it, so the ghost rate is auditable rather than a black box.

## Sectors

Two archetypes ship today, each with its own question and extraction schema:

- **US_INSURER** — in-network providers (primary care, therapists, clinics, specialists).
- **MARKETPLACE_SELLER** — "verified" merchants and storefronts.

## Safety

- Mock mode makes zero calls, and the test suite enforces it (`test_zero_live_calls_guarantee` patches `subprocess.run` and asserts it is never touched).
- Live mode is gated: a confirmation prompt in the CLI and a credit-guard dialog in the web UI, since CALL-E bills by call duration.
- One benign question per call. Muster never asks for health details, payment, or personal information.
- Directory files are checked for dummy and duplicate numbers before dialing, and every CSV field is sanitized on import and export against spreadsheet formula injection.

## Sample data

The bundled samples use fictional `+1 555` numbers on purpose, so nothing gets dialed by accident. To run a real audit, point Muster at a directory whose numbers you're allowed to call.

## Project layout

```
muster/          core package — parser, classifier, engine, CALL-E client, CLI, MCP server, web app
skills/muster/   reusable agent skill (SKILL.md + run_audit.py)
sample_data/     example directories (fictional numbers)
tests/           pytest suite (no live calls)
```

## License

MIT
