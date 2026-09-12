/**
 * MUSTER — "Live Audit Ledger" (v2) Controller
 * Matches handoff/design-ref.html and handoff/DESIGN.md.
 * Drives:
 *   - Dark switchboard network (central hub + node ring + pulse ripples + crack marks)
 *   - Live ghost-rate dial (SVG arc + Newsreader % counter)
 *   - Telegraph transcripts & flat ink-stamp verdicts
 *   - "The Reveal" finale (ghosts drop away & strikethrough)
 *   - Derived headline patient-ratio stat & tier rating
 *   - Node hover tooltips & bidirectional switchboard-ledger highlighting
 *   - Demo speed controls (1x / 2x / Instant) & pause/resume
 *   - Credit-guard modal for live CALL-E runs
 *   - Real-time Server-Sent Events (SSE) from FastAPI engine
 */

const CFG = {
  PRESENT: { stamp: 'Present', cls: 'st-present', col: '#16A394', fill: '#0E7C70' },
  GHOST:   { stamp: 'Ghost',   cls: 'st-ghost',   col: '#C8434E', fill: '#2a1416' },
  UNREACHABLE: { stamp: 'Unreachable', cls: 'st-unreach', col: '#7A828E', fill: '#31353f' },
  UNCERTAIN:   { stamp: 'Uncertain',   cls: 'st-unreach', col: '#B45309', fill: '#31353f' },
};

const NS = "http://www.w3.org/2000/svg";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Application State
const state = {
  mode: 'mock', // 'mock' | 'live'
  presets: [],
  selectedPresetId: 'us_insurer_network',
  entries: [],
  jobId: null,
  outcomes: new Map(), // entryId -> CallOutcome
  nodes: [], // { line, c, glow, lbl, x, y, done, crack, typer, calling }
  isAuditing: false,
  isPaused: false,
  pendingEvents: [],
  speed: 1, // 1 = 1x, 2 = 2x, 0 = Instant
  timer: null,
  t0: 0,
  elapsedOffset: 0,
  eventSource: null,
};

// DOM Cache
const dom = {
  mCalls: document.getElementById('mCalls'),
  mElapsed: document.getElementById('mElapsed'),
  mStatus: document.getElementById('mStatus'),

  arc: document.getElementById('arc'),
  dialPct: document.getElementById('dialPct'),
  dialSub: document.getElementById('dialSub'),
  hlGhost: document.getElementById('hlGhost'),
  hlRest: document.getElementById('hlRest'),

  bPresent: document.getElementById('bPresent'),
  bGhost: document.getElementById('bGhost'),
  bUnreach: document.getElementById('bUnreach'),
  nPresent: document.getElementById('nPresent'),
  nGhost: document.getElementById('nGhost'),
  nUnreach: document.getElementById('nUnreach'),

  board: document.querySelector('.board'),
  boardSt: document.getElementById('boardSt'),
  net: document.getElementById('net'),
  nodeTooltip: document.getElementById('nodeTooltip'),

  runBtn: document.getElementById('runBtn'),
  pauseBtn: document.getElementById('pauseBtn'),
  modeChip: document.getElementById('modeChip'),
  presetSelect: document.getElementById('presetSelect'),
  fileInput: document.getElementById('fileInput'),
  speedGroup: document.getElementById('speedGroup'),

  dlCsv: document.getElementById('dlCsv'),
  dlJson: document.getElementById('dlJson'),
  dlMd: document.getElementById('dlMd'),

  ledger: document.getElementById('ledger'),
  scrim: document.getElementById('scrim'),
  modal: document.getElementById('modal'),

  // Credit Guard Live Modal
  liveGuardScrim: document.getElementById('liveGuardScrim'),
  liveGuardModal: document.getElementById('liveGuardModal'),
  liveGuardCloseBtn: document.getElementById('liveGuardCloseBtn'),
  liveGuardCancelBtn: document.getElementById('liveGuardCancelBtn'),
  liveGuardConfirmBtn: document.getElementById('liveGuardConfirmBtn'),
  liveGuardCount: document.getElementById('liveGuardCount'),
  liveGuardCreditNote: document.getElementById('liveGuardCreditNote'),
};

// Initialize
async function init() {
  setupEventListeners();
  await loadPresets();
  await selectPreset(state.selectedPresetId);
}

function setupEventListeners() {
  // Mode toggle
  dom.modeChip.addEventListener('click', toggleMode);

  // Preset select
  dom.presetSelect.addEventListener('change', (e) => selectPreset(e.target.value));

  // Custom file upload
  dom.fileInput.addEventListener('change', handleFileUpload);

  // Run audit button
  dom.runBtn.addEventListener('click', handleRunClick);

  // Pause / Resume button
  if (dom.pauseBtn) {
    dom.pauseBtn.addEventListener('click', togglePause);
  }

  // Speed multiplier
  if (dom.speedGroup) {
    dom.speedGroup.querySelectorAll('.speed-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        dom.speedGroup.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.speed = parseFloat(btn.dataset.speed);
      });
    });
  }

  // Live Credit Guard Modal
  if (dom.liveGuardCloseBtn) dom.liveGuardCloseBtn.addEventListener('click', closeLiveGuardModal);
  if (dom.liveGuardCancelBtn) dom.liveGuardCancelBtn.addEventListener('click', () => {
    closeLiveGuardModal();
    if (state.mode === 'live') toggleMode(); // Revert to mock safely
  });
  if (dom.liveGuardConfirmBtn) dom.liveGuardConfirmBtn.addEventListener('click', () => {
    closeLiveGuardModal();
    executeAudit();
  });
  if (dom.liveGuardScrim) {
    dom.liveGuardScrim.addEventListener('click', (e) => {
      if (e.target === dom.liveGuardScrim) closeLiveGuardModal();
    });
  }

  // Downloads
  dom.dlCsv.addEventListener('click', () => downloadReport('csv'));
  dom.dlJson.addEventListener('click', () => downloadReport('json'));
  dom.dlMd.addEventListener('click', () => downloadReport('md'));

  // Evidence Modal dismiss
  dom.scrim.addEventListener('click', (e) => {
    if (e.target === dom.scrim) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      closeLiveGuardModal();
    }
  });
}

function toggleMode() {
  if (state.isAuditing) return;
  state.mode = state.mode === 'mock' ? 'live' : 'mock';
  if (state.mode === 'live') {
    dom.modeChip.textContent = '◉ Live CALL-E';
    dom.modeChip.style.borderColor = '#C8434E';
    dom.modeChip.style.color = '#9B2A34';
  } else {
    dom.modeChip.textContent = '◉ Mock Rehearsal';
    dom.modeChip.style.borderColor = 'var(--ink)';
    dom.modeChip.style.color = 'var(--ink)';
  }
}

async function loadPresets() {
  try {
    const res = await fetch('/api/presets');
    state.presets = await res.json();
  } catch (err) {
    console.error('Failed to load presets:', err);
  }
}

async function selectPreset(presetId) {
  state.selectedPresetId = presetId;
  const meta = state.presets.find(p => p.id === presetId);
  try {
    const res = await fetch(`/api/presets/${presetId}`);
    state.entries = await res.json();
    resetState();
    buildSwitchboard();
    buildLedger();
  } catch (err) {
    console.error('Error loading preset entries:', err);
  }
}

async function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json();
      alert(`Upload error: ${err.detail || 'Could not parse directory file.'}`);
      return;
    }
    state.entries = await res.json();
    dom.boardSt.textContent = `${file.name} · ${state.entries.length}`;
    resetState();
    buildSwitchboard();
    buildLedger();
  } catch (err) {
    alert(`File upload failed: ${err.message}`);
  }
}

function resetState() {
  state.outcomes.clear();
  state.jobId = null;
  state.isAuditing = false;
  state.isPaused = false;
  state.pendingEvents = [];

  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  clearInterval(state.timer);

  dom.mCalls.textContent = '0';
  dom.mElapsed.textContent = '0.0s';
  dom.mStatus.textContent = 'Ready';
  dom.mStatus.classList.add('on');

  dom.runBtn.disabled = false;
  dom.runBtn.textContent = '▶ Run audit';

  if (dom.pauseBtn) {
    dom.pauseBtn.disabled = true;
    dom.pauseBtn.classList.add('disabled');
    dom.pauseBtn.classList.remove('paused');
    dom.pauseBtn.textContent = '⏸ Pause';
  }

  dom.dlCsv.classList.add('disabled');
  dom.dlJson.classList.add('disabled');
  dom.dlMd.classList.add('disabled');

  setDial(0, 0, 0, 0);
  dom.hlGhost.textContent = '—';
  dom.hlRest.textContent = `of ${state.entries.length} listed are ghosts`;
  dom.dialSub.textContent = 'ghost rate';

  const meta = state.presets.find(p => p.id === state.selectedPresetId);
  dom.boardSt.textContent = meta ? `${meta.name} · ${state.entries.length}` : `Target Directory · ${state.entries.length}`;
}

// --------------------------------------------------------------------------
// Switchboard Network Rendering with Tooltips & Bidirectional Interaction
// --------------------------------------------------------------------------
function buildSwitchboard() {
  dom.net.innerHTML = '';
  state.nodes = [];

  const CX = 360, CY = 238, R = 168;
  const N = state.entries.length;

  // Spoke lines
  state.entries.forEach((entry, i) => {
    const angle = (-90 + i * (360 / N)) * (Math.PI / 180);
    const x = CX + R * Math.cos(angle);
    const y = CY + R * Math.sin(angle);

    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", CX);
    line.setAttribute("y1", CY);
    line.setAttribute("x2", x);
    line.setAttribute("y2", y);
    line.setAttribute("stroke", "#2c313c");
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("stroke-dasharray", "4 5");
    dom.net.appendChild(line);

    const g = document.createElementNS(NS, "g");
    g.style.cursor = "pointer";

    const glow = document.createElementNS(NS, "circle");
    glow.setAttribute("cx", x);
    glow.setAttribute("cy", y);
    glow.setAttribute("r", 20);
    glow.setAttribute("fill", "transparent");

    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", x);
    c.setAttribute("cy", y);
    c.setAttribute("r", 11);
    c.setAttribute("fill", "#31353f");
    c.setAttribute("stroke", "#454b57");
    c.setAttribute("stroke-width", "1.5");

    const lbl = document.createElementNS(NS, "text");
    lbl.setAttribute("x", x);
    lbl.setAttribute("y", y + (y > CY ? 30 : -20));
    lbl.setAttribute("text-anchor", "middle");
    lbl.setAttribute("fill", "#7c8492");
    lbl.setAttribute("font-size", "9");
    lbl.setAttribute("font-family", "JetBrains Mono, monospace");
    lbl.textContent = String(i + 1).padStart(2, '0');

    g.appendChild(glow);
    g.appendChild(c);
    g.appendChild(lbl);
    dom.net.appendChild(g);

    const nodeObj = { line, c, glow, lbl, x, y, done: false, crack: [], calling: false };
    state.nodes.push(nodeObj);

    // Tooltip handlers
    g.addEventListener("mouseenter", (evt) => {
      const outcome = state.outcomes.get(entry.id);
      const statusText = outcome ? outcome.verdict : (nodeObj.calling ? "CALLING" : "QUEUED");
      const badgeCol = outcome ? (CFG[outcome.verdict] || CFG.UNCERTAIN).col : (nodeObj.calling ? "#E0A44A" : "#8c95a6");

      dom.nodeTooltip.innerHTML = `
        <div class="tt-title">${escapeHtml(entry.name)}</div>
        <div class="tt-meta">${escapeHtml(entry.phone)} · ${escapeHtml(entry.address || entry.category || '')}</div>
        <span class="tt-badge" style="background:${badgeCol}22; color:${badgeCol}; border:1px solid ${badgeCol}55;">${statusText}</span>
      `;
      positionTooltip(evt);
      dom.nodeTooltip.classList.add("show");
    });

    g.addEventListener("mousemove", (evt) => {
      positionTooltip(evt);
    });

    g.addEventListener("mouseleave", () => {
      dom.nodeTooltip.classList.remove("show");
    });

    // Bidirectional click: node -> highlight ledger row & open modal
    g.addEventListener("click", () => {
      highlightLedgerRow(entry.id);
      const outcome = state.outcomes.get(entry.id);
      if (outcome) openModal(outcome);
    });
  });

  // Center Operator Hub
  const hub = document.createElementNS(NS, "circle");
  hub.setAttribute("cx", CX);
  hub.setAttribute("cy", CY);
  hub.setAttribute("r", 26);
  hub.setAttribute("fill", "#20232b");
  hub.setAttribute("stroke", "#3a3f4b");
  hub.setAttribute("stroke-width", 1.5);
  dom.net.appendChild(hub);

  // Pulse Wave Circle
  const pulse = document.createElementNS(NS, "circle");
  pulse.setAttribute("id", "netPulse");
  pulse.setAttribute("cx", CX);
  pulse.setAttribute("cy", CY);
  pulse.setAttribute("r", 26);
  pulse.setAttribute("fill", "none");
  pulse.setAttribute("stroke", "#C8434E");
  pulse.setAttribute("stroke-width", 2);
  pulse.setAttribute("opacity", "0");
  dom.net.appendChild(pulse);
}

function positionTooltip(evt) {
  if (!dom.board) return;
  const rect = dom.board.getBoundingClientRect();
  const x = Math.min(Math.max(evt.clientX - rect.left + 14, 10), rect.width - 240);
  const y = Math.min(Math.max(evt.clientY - rect.top - 12, 10), rect.height - 80);
  dom.nodeTooltip.style.left = `${x}px`;
  dom.nodeTooltip.style.top = `${y}px`;
}

function highlightLedgerRow(entryId) {
  dom.ledger.querySelectorAll('.lrow').forEach(r => r.classList.remove('highlighted'));
  const row = dom.ledger.querySelector(`[data-id="${entryId}"]`);
  if (row) {
    row.classList.add('highlighted');
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function highlightSwitchboardNode(entryId) {
  const idx = state.entries.findIndex(e => e.id === entryId);
  if (idx === -1) return;
  const n = state.nodes[idx];
  if (n && n.glow) {
    n.glow.setAttribute('fill', '#E0A44A');
    n.glow.style.opacity = '0.5';
    setTimeout(() => {
      n.glow.style.opacity = n.done ? '0.2' : '0';
    }, 900);
  }
}

// --------------------------------------------------------------------------
// Ledger Rendering
// --------------------------------------------------------------------------
function buildLedger() {
  dom.ledger.innerHTML = '';
  state.entries.forEach((entry, i) => {
    const idxStr = String(i + 1).padStart(2, '0');
    const r = document.createElement('div');
    r.className = 'lrow';
    r.dataset.id = entry.id;

    const loc = entry.address || entry.category || '';
    r.innerHTML = `
      <div class="idx">${idxStr}</div>
      <div>
        <div class="nm">${escapeHtml(entry.name)}</div>
        <div class="ph">${escapeHtml(entry.phone)}</div>
      </div>
      <div class="claim">${escapeHtml(entry.claimed_status)}${loc ? ` · ${escapeHtml(loc)}` : ''}</div>
      <div class="verdict">
        <span class="calling" style="visibility:hidden">
          <span class="dot"></span>
          <span class="txt">queued</span>
        </span>
      </div>
      <div class="conf">—</div>
    `;

    r.addEventListener('click', () => {
      highlightLedgerRow(entry.id);
      highlightSwitchboardNode(entry.id);
      const outcome = state.outcomes.get(entry.id);
      if (outcome) openModal(outcome);
    });

    dom.ledger.appendChild(r);
  });
}

// --------------------------------------------------------------------------
// Dial & Stats
// --------------------------------------------------------------------------
function setDial(present, ghost, unreach, total) {
  const gr = total > 0 ? Math.round((ghost / total) * 100) : 0;
  dom.arc.setAttribute('stroke-dashoffset', 515 - (515 * gr / 100));
  dom.dialPct.textContent = `${gr}%`;
  dom.hlGhost.textContent = ghost > 0 ? ghost : '—';

  dom.nPresent.textContent = present;
  dom.nGhost.textContent = ghost;
  dom.nUnreach.textContent = unreach;

  if (total > 0) {
    dom.bPresent.style.width = `${(present / total) * 100}%`;
    dom.bGhost.style.width = `${(ghost / total) * 100}%`;
    dom.bUnreach.style.width = `${(unreach / total) * 100}%`;
  } else {
    dom.bPresent.style.width = '0%';
    dom.bGhost.style.width = '0%';
    dom.bUnreach.style.width = '0%';
  }
}

// --------------------------------------------------------------------------
// Credit Guard & Launch Audit
// --------------------------------------------------------------------------
async function handleRunClick() {
  if (state.isAuditing || state.entries.length === 0) return;

  if (state.mode === 'live') {
    // Show credit guard modal before placing real calls
    openLiveGuardModal();
  } else {
    executeAudit();
  }
}

async function openLiveGuardModal() {
  if (dom.liveGuardCount) dom.liveGuardCount.textContent = state.entries.length;
  if (dom.liveGuardCreditNote) {
    dom.liveGuardCreditNote.textContent = "Checking account status...";
    try {
      const res = await fetch('/api/auth/status');
      const data = await res.json();
      if (data.authenticated) {
        dom.liveGuardCreditNote.innerHTML = `<strong>Active CALL-E session</strong> · ${escapeHtml(data.credits_note)}`;
      } else {
        dom.liveGuardCreditNote.innerHTML = `<span style="color:#d9534f;">⚠️ Warning: ${escapeHtml(data.status_text)}. Live calls may fail.</span>`;
      }
    } catch (e) {
      dom.liveGuardCreditNote.textContent = "Metered billing: ~34 credits per minute. Keep calls short.";
    }
  }
  if (dom.liveGuardScrim) dom.liveGuardScrim.classList.add('open');
}

function closeLiveGuardModal() {
  if (dom.liveGuardScrim) dom.liveGuardScrim.classList.remove('open');
}

// --------------------------------------------------------------------------
// Run Audit (SSE Orchestration)
// --------------------------------------------------------------------------
async function executeAudit() {
  state.isAuditing = true;
  state.isPaused = false;
  state.pendingEvents = [];

  // Reset visual state
  dom.mStatus.textContent = state.mode === 'live' ? 'Calling (Live)…' : 'Auditing…';
  dom.mStatus.classList.add('on');
  dom.runBtn.disabled = true;
  dom.runBtn.textContent = 'Auditing…';

  if (dom.pauseBtn) {
    dom.pauseBtn.disabled = false;
    dom.pauseBtn.classList.remove('disabled', 'paused');
    dom.pauseBtn.textContent = '⏸ Pause';
  }

  dom.ledger.querySelectorAll('.lrow').forEach(r => {
    r.classList.remove('done', 'highlighted');
    r.querySelector('.verdict').innerHTML = '<span class="calling" style="visibility:hidden"><span class="dot"></span><span class="txt"></span></span>';
    r.querySelector('.conf').textContent = '—';
    r.querySelector('.nm').classList.remove('ghosted');
  });

  state.nodes.forEach((n) => {
    (n.crack || []).forEach(el => el.remove());
    n.crack = [];
    n.done = false;
    n.calling = false;
    n.c.setAttribute('fill', '#31353f');
    n.c.setAttribute('stroke', '#454b57');
    n.c.setAttribute('r', 11);
    n.c.style.opacity = 1;
    n.c.style.transform = '';
    n.lbl.style.transform = '';
    n.lbl.style.opacity = 1;
    n.lbl.setAttribute('fill', '#7c8492');
    n.glow.style.opacity = 0;
    n.line.setAttribute('stroke', '#2c313c');
    n.line.setAttribute('stroke-dasharray', '4 5');
    n.line.style.opacity = 1;
  });

  setDial(0, 0, 0, state.entries.length);
  dom.hlRest.textContent = `of ${state.entries.length} listed are ghosts`;

  // Start timer
  state.t0 = Date.now();
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!state.isPaused) {
      dom.mElapsed.textContent = ((Date.now() - state.t0) / 1000).toFixed(1) + 's';
    }
  }, 100);

  // Sector and Goal: English hero by default
  const meta = state.presets.find(p => p.id === state.selectedPresetId);
  const goal = meta?.default_goal || "Hello, I am calling to verify directory network status. Are you currently in-network and accepting new patients?";
  const language = 'en';
  const sector = meta?.sector || 'US_INSURER';

  const payload = {
    entries: state.entries,
    mode: state.mode,
    goal: goal,
    concurrency: 2,
    language: language,
    sector: sector,
  };

  try {
    const res = await fetch('/api/audit/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`Could not initiate audit: ${res.statusText}`);

    const data = await res.json();
    state.jobId = data.job_id;
    listenToEvents(state.jobId);
  } catch (err) {
    alert(`Audit launch error: ${err.message}`);
    state.isAuditing = false;
    dom.runBtn.disabled = false;
    dom.runBtn.textContent = '▶ Run audit';
    if (dom.pauseBtn) dom.pauseBtn.classList.add('disabled');
    clearInterval(state.timer);
  }
}

function listenToEvents(jobId) {
  if (state.eventSource) state.eventSource.close();

  const es = new EventSource(`/api/audit/events/${jobId}`);
  state.eventSource = es;

  es.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      if (state.isPaused) {
        state.pendingEvents.push(event);
      } else {
        handleProgressEvent(event);
      }
    } catch (err) {
      console.error('Error parsing SSE event:', err);
    }
  };

  es.addEventListener('done', () => {
    es.close();
    if (!state.isPaused) {
      finishAudit();
    }
  });

  es.onerror = () => {
    es.close();
    if (!state.isPaused) {
      finishAudit();
    }
  };
}

function togglePause() {
  if (!state.isAuditing) return;
  state.isPaused = !state.isPaused;

  if (state.isPaused) {
    dom.pauseBtn.textContent = '▶ Resume';
    dom.pauseBtn.classList.add('paused');
    dom.mStatus.textContent = 'Paused';
    dom.mStatus.classList.remove('on');
  } else {
    dom.pauseBtn.textContent = '⏸ Pause';
    dom.pauseBtn.classList.remove('paused');
    dom.mStatus.textContent = state.mode === 'live' ? 'Calling (Live)…' : 'Auditing…';
    dom.mStatus.classList.add('on');

    // Drain queued events
    while (state.pendingEvents.length > 0) {
      const ev = state.pendingEvents.shift();
      handleProgressEvent(ev);
    }
  }
}

function handleProgressEvent(event) {
  const { event_type, entry_id, outcome, summary } = event;

  if (event_type === 'row_calling' && entry_id) {
    animateCalling(entry_id, true);
  } else if (event_type === 'row_analyzing' && entry_id) {
    updateCallingSnippet(entry_id, "analyzing transcript…");
  } else if (event_type === 'row_resolved' && outcome) {
    state.outcomes.set(outcome.entry_id, outcome);
    animateCalling(outcome.entry_id, false);
    resolveEntry(outcome);
  } else if (event_type === 'complete') {
    finishAudit();
  }

  if (summary) {
    setDial(summary.present_count, summary.ghost_count, summary.unreachable_count, summary.total);
    dom.mCalls.textContent = summary.completed;
  }
}

function animateCalling(entryId, on) {
  const idx = state.entries.findIndex(e => e.id === entryId);
  if (idx === -1) return;

  const n = state.nodes[idx];
  const pulse = document.getElementById('netPulse');
  const row = dom.ledger.querySelector(`[data-id="${entryId}"]`);

  if (on) {
    if (n) {
      n.calling = true;
      n.c.setAttribute('stroke', '#E0A44A');
      n.c.setAttribute('r', 13);
      n.line.setAttribute('stroke', '#E0A44A');
      n.line.style.opacity = 0.9;
    }

    if (pulse) {
      pulse.style.transition = 'none';
      pulse.setAttribute('r', 26);
      pulse.setAttribute('opacity', '0.9');
      requestAnimationFrame(() => {
        pulse.style.transition = 'all 1.1s ease-out';
        pulse.setAttribute('r', 190);
        pulse.setAttribute('opacity', '0');
      });
    }

    if (row) {
      const c = row.querySelector('.calling');
      c.style.visibility = 'visible';
      c.querySelector('.txt').textContent = 'calling…';

      // Telegraph typing effect (adjusted by state.speed)
      const phone = state.entries[idx].phone;
      const full = `  ▸ dialing ${phone}…`;
      let s = 0;
      clearInterval(n._typer);
      const intervalMs = state.speed === 0 ? 0 : (state.speed === 2 ? 14 : 26);
      if (intervalMs === 0 || reduceMotion) {
        c.querySelector('.txt').textContent = 'calling' + full;
      } else {
        n._typer = setInterval(() => {
          s++;
          c.querySelector('.txt').textContent = 'calling' + full.slice(0, s);
          if (s >= full.length) clearInterval(n._typer);
        }, intervalMs);
      }
    }
  } else {
    if (n) {
      n.calling = false;
      clearInterval(n._typer);
    }
    if (row) {
      const c = row.querySelector('.calling');
      c.style.visibility = 'hidden';
    }
  }
}

function updateCallingSnippet(entryId, snippet) {
  const row = dom.ledger.querySelector(`[data-id="${entryId}"]`);
  if (row) {
    const txt = row.querySelector('.calling .txt');
    if (txt) txt.textContent = `calling  ▸ ${snippet}`;
  }
}

function resolveEntry(outcome) {
  const idx = state.entries.findIndex(e => e.id === outcome.entry_id);
  if (idx === -1) return;

  const n = state.nodes[idx];
  const v = outcome.verdict;
  const cfg = CFG[v] || CFG.UNCERTAIN;

  // Switchboard node resolution
  if (n) {
    n.line.setAttribute('stroke', cfg.col);
    n.line.setAttribute('stroke-dasharray', 'none');
    n.line.style.opacity = 0.55;

    n.c.setAttribute('fill', cfg.fill);
    n.c.setAttribute('stroke', cfg.col);
    n.c.setAttribute('stroke-width', v === 'GHOST' ? 2.5 : 2);
    n.lbl.setAttribute('fill', cfg.col);

    if (v === 'PRESENT') {
      n.glow.setAttribute('fill', cfg.col);
      n.glow.style.opacity = 0.16;
    } else if (v === 'GHOST') {
      // Crack: draw an X on the node
      n.c.setAttribute('r', 9);
      n.c.style.opacity = 0.85;
      [[-6, -6, 6, 6], [-6, 6, 6, -6]].forEach(seg => {
        const l = document.createElementNS(NS, 'line');
        l.setAttribute('x1', n.x + seg[0]);
        l.setAttribute('y1', n.y + seg[1]);
        l.setAttribute('x2', n.x + seg[2]);
        l.setAttribute('y2', n.y + seg[3]);
        l.setAttribute('stroke', cfg.col);
        l.setAttribute('stroke-width', 1.6);
        dom.net.appendChild(l);
        n.crack.push(l);
      });
    }
    n.done = true;
  }

  // Ledger row resolution
  const row = dom.ledger.querySelector(`[data-id="${outcome.entry_id}"]`);
  if (row) {
    row.classList.add('done');
    row.querySelector('.verdict').innerHTML = `<span class="stamp ${cfg.cls} in">${cfg.stamp}</span>`;
    row.querySelector('.conf').textContent = outcome.verdict === 'UNREACHABLE' ? '—' : outcome.confidence_score.toFixed(2);
  }
}

// --------------------------------------------------------------------------
// "The Reveal" Finale & Derived Editorial Headline Stat
// --------------------------------------------------------------------------
function finishAudit() {
  state.isAuditing = false;
  state.isPaused = false;
  clearInterval(state.timer);

  dom.mStatus.textContent = 'Complete';
  dom.mStatus.classList.remove('on');

  if (dom.pauseBtn) {
    dom.pauseBtn.disabled = true;
    dom.pauseBtn.classList.add('disabled');
    dom.pauseBtn.classList.remove('paused');
    dom.pauseBtn.textContent = '⏸ Pause';
  }

  const outcomesArr = Array.from(state.outcomes.values());
  const ghostCount = outcomesArr.filter(o => o.verdict === 'GHOST').length;
  const total = state.entries.length;
  const ghostPct = total > 0 ? Math.round((ghostCount / total) * 100) : 0;

  // Milestone 3: ONE derived headline stat, tastefully done
  // N = 1 / (1 - ghostRate); Tier: PRIME / COMPROMISED / HIGH-RISK / DEFECTIVE
  const nonGhostRatio = total > 0 ? (total - ghostCount) / total : 1;
  const patientCallRatio = nonGhostRatio > 0 ? (1 / nonGhostRatio).toFixed(1) : '∞';

  let tier = 'PRIME';
  let tierCol = 'var(--present)';
  if (ghostPct > 50) {
    tier = 'DEFECTIVE';
    tierCol = 'var(--ghost)';
  } else if (ghostPct > 25) {
    tier = 'HIGH-RISK';
    tierCol = '#c2410c';
  } else if (ghostPct > 10) {
    tier = 'COMPROMISED';
    tierCol = '#d97706';
  }

  dom.boardSt.innerHTML = `<b style="color:#C8434E">${ghostCount} of ${total}</b> = ghost (${ghostPct}%)`;
  dom.dialSub.textContent = 'ghost rate · final';

  // Editorial one-line breakdown
  dom.hlRest.innerHTML = `of ${total} listed are ghosts<br><span style="display:block; margin-top:5px; font-size:12.5px; font-family:var(--font-mono); color:var(--muted); font-weight:400; line-height:1.4;">A patient must call ~<strong style="color:var(--ink);">${patientCallRatio}</strong> listings to reach 1 real provider · <strong style="color:${tierCol}; letter-spacing:0.04em;">${tier}</strong></span>`;

  // SET-PIECE: "THE REVEAL"
  // Ghost nodes crack and drop down; ledger ghost rows get struck through
  state.nodes.forEach((n, i) => {
    const entry = state.entries[i];
    const outcome = state.outcomes.get(entry.id);
    const isGhost = outcome && outcome.verdict === 'GHOST';

    if (isGhost) {
      setTimeout(() => {
        const dy = 40 + Math.random() * 30;
        [n.c, n.lbl, ...(n.crack || [])].forEach(el => {
          el.style.transition = 'transform 1.1s ease-in, opacity 1.1s';
          el.style.transform = `translateY(${dy}px)`;
          el.style.opacity = 0.15;
        });
        n.line.style.transition = 'opacity 0.8s';
        n.line.style.opacity = 0.08;
      }, i * 45);

      const row = dom.ledger.querySelector(`[data-id="${entry.id}"]`);
      if (row) row.querySelector('.nm').classList.add('ghosted');
    } else if (outcome && outcome.verdict === 'PRESENT') {
      n.glow.style.transition = 'opacity 0.6s';
      n.glow.style.opacity = 0.28;
    }
  });

  // Enable download actions
  if (state.jobId) {
    dom.dlCsv.classList.remove('disabled');
    dom.dlJson.classList.remove('disabled');
    dom.dlMd.classList.remove('disabled');
  }

  dom.runBtn.disabled = false;
  dom.runBtn.textContent = '↻ Replay audit';
}

// --------------------------------------------------------------------------
// Evidence Modal
// --------------------------------------------------------------------------
function openModal(outcome) {
  const cfg = CFG[outcome.verdict] || CFG.UNCERTAIN;
  const ext = outcome.extracted || {};

  const quote = (outcome.evidence_quotes && outcome.evidence_quotes.length > 0)
    ? outcome.evidence_quotes[0]
    : outcome.stated_reason || 'Verified operational response.';

  const formattedTranscript = (outcome.transcript || '[No audio transcript captured]')
    .replace(/^(Agent|Reception|Respondent|Operator):/gm, '<em>$1:</em>')
    .replace(/\n/g, '<br>');

  const isInsurer = outcome.sector === 'US_INSURER' || ext.in_network !== undefined || ext.accepts_scheme !== undefined;
  const inNetworkVal = ext.in_network !== undefined ? ext.in_network : ext.accepts_scheme;
  const intakeVal = ext.accepting_new_patients !== undefined ? ext.accepting_new_patients : ext.admitting_patients;

  let specDl = '';
  if (isInsurer) {
    specDl = `
      <dt>In-network</dt><dd class="${inNetworkVal === true ? 'yes' : (inNetworkVal === false ? 'no' : '')}">${inNetworkVal === true ? 'Yes' : (inNetworkVal === false ? 'No — left network' : '—')}</dd>
      <dt>Intake open</dt><dd class="${intakeVal === true ? 'yes' : (intakeVal === false ? 'no' : '')}">${intakeVal === true ? 'Yes' : (intakeVal === false ? 'No — closed intake' : '—')}</dd>
    `;
  } else {
    specDl = `
      <dt>Operational</dt><dd class="${ext.operational === true ? 'yes' : (ext.operational === false ? 'no' : '')}">${ext.operational === true ? 'Yes' : (ext.operational === false ? 'No — closed' : '—')}</dd>
      <dt>Sells goods</dt><dd class="${ext.sells_claimed_product === true ? 'yes' : (ext.sells_claimed_product === false ? 'no' : '')}">${ext.sells_claimed_product === true ? 'Yes' : (ext.sells_claimed_product === false ? 'No' : '—')}</dd>
    `;
  }

  dom.modal.innerHTML = `
    <div class="mh">
      <div class="nm">
        ${escapeHtml(outcome.entry_name)}
        <span>${escapeHtml(outcome.phone)}</span>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <span class="stamp ${cfg.cls}">${cfg.stamp}</span>
        <button class="x" id="modalCloseBtn">&times;</button>
      </div>
    </div>
    <dl>
      <dt>Reached human</dt><dd class="${ext.reached_human ? 'yes' : 'no'}">${ext.reached_human ? 'Yes' : 'No'}</dd>
      ${specDl}
      <dt>Confidence</dt><dd>${outcome.confidence} · ${outcome.confidence_score.toFixed(2)}</dd>
    </dl>
    <div class="quote quote--${outcome.verdict === 'PRESENT' ? 'present' : 'ghost'}">&ldquo;${escapeHtml(quote)}&rdquo;</div>
    <div class="trans-lbl">CALL-E Verbatim Spoken Transcript</div>
    <div class="trans">${formattedTranscript}</div>
  `;

  dom.scrim.classList.add('open');
  document.getElementById('modalCloseBtn').onclick = closeModal;
}

function closeModal() {
  dom.scrim.classList.remove('open');
}

function downloadReport(fmt) {
  if (!state.jobId) return;
  window.open(`/api/audit/report/${state.jobId}/${fmt}`, '_blank');
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

window.addEventListener('DOMContentLoaded', init);
