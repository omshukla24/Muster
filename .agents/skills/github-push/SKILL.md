---
name: github-push
description: >-
  Prepares, validates, and pushes production-grade READMEs and codebases to GitHub repositories. Automatically activate whenever Om mentions "github", "push to github", "git push", "push to repo", or asks to update the repository with comprehensive README documentation, architecture diagrams, tables, and full project details.
---

# GitHub Push & README Publisher Skill

This skill governs preparing high-standard repository documentation and safely pushing commits to remote GitHub repositories for Om's projects.

## Activation Triggers
Automatically activate this skill whenever Om:
- Mentions "github", "push to github", "push to repo", or "git push"
- Says "update repo with good readme" or requests full architectural details, design breakdowns, and tables in the repository
- Needs to publish or synchronize a project's codebase and README with GitHub

---

## Workflow: From Codebase to High-Fidelity GitHub Publication

### Step 1: Pre-Flight Safety & Git Boundary Check
1. **Verify Git Root**:
   Always verify the git repository top-level directory (`git rev-parse --show-toplevel`). Ensure git is initialized in the **project root**, NOT in parent directories (like `C:\Users\user`). If uninitialized or in parent, run `git init` directly inside the project directory.
2. **Verify `.gitignore` & Secrets Protection**:
   - Om's global rule: `<project root>/handoff/` MUST be in `.gitignore` and NEVER committed or pushed.
   - Ensure `.env`, `reports/`, scratch files, virtualenvs (`.venv/`), and caches (`__pycache__/`, `.pytest_cache/`) are ignored.
   - Run `git check-ignore -v handoff/ .env reports/` to prove they are excluded.

### Step 2: Crafting the Comprehensive, High-Fidelity README
Never push a "basic ass" or skeletal README. A winning hackathon/production repository README must include:
1. **Header & Dynamic Badges**:
   - Status badges for test suite pass count, language runtime, core framework, MCP integration, and license.
   - One-line punchy value proposition blockquote.
2. **The Problem & Real-World Impact (The Hook)**:
   - Deep context on the failure mode (e.g. ghost networks in health insurance, merchant fraud in marketplaces).
   - Regulatory findings (GAO, CMS, US Senate reports) and human consequence.
3. **Architecture & System Design**:
   - Clear ASCII / Mermaid system sequence and architecture diagrams.
   - Detailed component-by-component breakdown (Telephony Gateway, Core Engine, MCP Server, Web App, Safety Layers).
   - State machine diagrams for entities and batch lifecycles.
4. **Structured Tables**:
   - Sector archetypes with extraction schemas and default qualification questions.
   - Classification and Evidence Decision Matrix (verdict, criteria, confidence, sample quotes).
   - CLI flags and FastMCP parameters table.
5. **Interactive UI & Visual Showcase**:
   - Design philosophy (Design tokens, serif + archival paper, dark switchboard centerpiece).
   - Breakdown of controls (speed multiplier, pause/resume, telegraph tickers, node tooltips, "The Reveal" finale).
   - Derived headline mathematical formula & adequacy tiers.
6. **Defensive Security & Guardrails**:
   - CSV formula injection sanitizer (`= + - @ \t \r`).
   - Pre-call phone anomaly detection (dummy digits, invalid lengths, cross-entity shared lines).
   - Credit-guard modal and zero-live-call guarantee in test suites.
7. **Developer & Agent Integration**:
   - FastMCP tool usage with copy-pasteable Python snippet.
   - Reusable Agent Skill workflow for agent directories (`awesome-phone-call-agents`).
8. **Installation, Quickstart & Testing**:
   - Copy-paste terminal commands for local UI, CLI audit (mock vs live), and pytest suite.
   - Clear project tree showing every file and directory.

### Strict Prohibitions (Never Include in README)
- **NEVER include Hackathon Rubric Alignments, judging criteria, scoring weights, or competition pandering**. The public GitHub README must present strictly as a serious, professional, production-grade open-source software project. Competition rubrics and judging notes belong exclusively in internal handoff docs or private submission portals, never in the public repo README.

### Step 3: Git Staging, Commit & Push
1. Check `git status` to verify ONLY intended source files are staged.
2. Commit with a clear, conventional message:
   `git commit -m "docs: enrich README with comprehensive architecture, design tables, and system workflow"`
3. Push to the configured remote branch (`git push -u origin main`).
4. Verify remote status (`git status`).

### Step 4: Living Handoff Update
Update `<project root>/handoff/HANDOFF.md` per Om's global rule:
- Increment handoff version (e.g. `vN+1`).
- Update Section 0 ("Resume here") and Snapshot with the GitHub repo link and latest commit status.
- Add append-only Changelog entry signed by Antigravity in IST (`Asia/Kolkata`).
