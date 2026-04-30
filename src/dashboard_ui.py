from __future__ import annotations


def dashboard_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Capital Kronos Signal Console</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f1a;
      --surface: #121826;
      --surface-2: #172033;
      --surface-3: #1d273b;
      --line: rgba(148, 163, 184, .18);
      --text: #eef2ff;
      --muted: #9aa8bd;
      --soft: #cbd5e1;
      --blue: #62a8ff;
      --cyan: #27d3d8;
      --green: #3ddc97;
      --amber: #f5b84b;
      --red: #ff6b6b;
      --violet: #9b87ff;
      --shadow: 0 22px 60px rgba(0, 0, 0, .38);
      --radius: 8px;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at 20% 0%, rgba(39, 211, 216, .18), transparent 28rem),
        radial-gradient(circle at 80% 8%, rgba(155, 135, 255, .16), transparent 30rem),
        linear-gradient(135deg, #08111e 0%, var(--bg) 45%, #11151f 100%);
      color: var(--text);
      letter-spacing: 0;
    }

    a { color: var(--cyan); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .app-shell {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
    }

    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 22px;
      border-right: 1px solid var(--line);
      background: rgba(10, 15, 27, .82);
      backdrop-filter: blur(16px);
      overflow-y: auto;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 22px;
    }

    .brand-mark {
      width: 42px;
      height: 42px;
      border-radius: 8px;
      background: linear-gradient(135deg, var(--cyan), var(--violet));
      display: grid;
      place-items: center;
      color: #07111f;
      font-weight: 900;
      box-shadow: 0 14px 34px rgba(39, 211, 216, .24);
    }

    .brand h1 {
      margin: 0;
      font-size: 16px;
      line-height: 1.15;
    }

    .brand p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 12px;
    }

    .side-card {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(255,255,255,.045);
      padding: 14px;
      margin-bottom: 14px;
    }

    .side-label { color: var(--muted); font-size: 12px; margin-bottom: 7px; }
    .side-value { font-size: 15px; font-weight: 750; overflow-wrap: anywhere; }
    .side-note { color: var(--muted); font-size: 12px; line-height: 1.5; margin-top: 10px; }

    .content {
      min-width: 0;
      padding: 24px;
    }

    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr);
      gap: 18px;
      align-items: stretch;
      margin-bottom: 18px;
    }

    .hero-main, .control-panel, .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.035));
      box-shadow: var(--shadow);
    }

    .hero-main {
      padding: 26px;
      min-height: 216px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      overflow: hidden;
      position: relative;
    }

    .hero-main::after {
      content: "";
      position: absolute;
      inset: auto -20% -45% 24%;
      height: 220px;
      background: linear-gradient(90deg, transparent, rgba(39,211,216,.18), rgba(155,135,255,.14), transparent);
      transform: skewY(-7deg);
      pointer-events: none;
    }

    .eyebrow {
      color: var(--cyan);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .12em;
      margin-bottom: 10px;
    }

    .hero-title {
      margin: 0;
      font-size: clamp(28px, 4vw, 52px);
      line-height: 1;
      max-width: 760px;
    }

    .hero-copy {
      margin: 14px 0 0;
      color: var(--soft);
      line-height: 1.55;
      max-width: 760px;
    }

    .hero-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 28px;
      border-radius: 999px;
      padding: 6px 10px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.055);
      color: var(--soft);
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }

    .badge.good { color: #aff7d3; border-color: rgba(61,220,151,.32); background: rgba(61,220,151,.10); }
    .badge.warn { color: #ffe0a2; border-color: rgba(245,184,75,.34); background: rgba(245,184,75,.10); }
    .badge.bad { color: #ffc0c0; border-color: rgba(255,107,107,.34); background: rgba(255,107,107,.10); }
    .badge.info { color: #cbdfff; border-color: rgba(98,168,255,.34); background: rgba(98,168,255,.10); }

    .control-panel { padding: 18px; }
    .control-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    .control-title h2 { margin: 0; font-size: 16px; }

    .control-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    label.field {
      display: flex;
      flex-direction: column;
      gap: 7px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    input, select {
      width: 100%;
      min-height: 40px;
      border: 1px solid rgba(148, 163, 184, .25);
      border-radius: 8px;
      background: rgba(8, 13, 24, .72);
      color: var(--text);
      padding: 9px 11px;
      outline: none;
      transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }

    input:focus, select:focus {
      border-color: rgba(39, 211, 216, .78);
      box-shadow: 0 0 0 3px rgba(39,211,216,.16);
    }

    .toggle-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }

    .toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.04);
      padding: 9px 11px;
      color: var(--soft);
      font-size: 12px;
      font-weight: 750;
    }

    .toggle input { width: 18px; min-height: 18px; accent-color: var(--cyan); }

    .actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }

    button {
      min-height: 42px;
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 10px 13px;
      color: var(--text);
      background: rgba(255,255,255,.08);
      font-weight: 800;
      cursor: pointer;
      transition: transform .16s ease, border-color .16s ease, background .16s ease, box-shadow .16s ease;
    }

    button:hover { transform: translateY(-1px); border-color: rgba(255,255,255,.22); }
    button:focus-visible { outline: 3px solid rgba(39,211,216,.35); outline-offset: 2px; }
    button:disabled { opacity: .58; cursor: wait; transform: none; }
    button.primary { background: linear-gradient(135deg, #2077ff, #27d3d8); color: #04111d; box-shadow: 0 14px 30px rgba(32,119,255,.25); }
    button.secondary { background: rgba(98,168,255,.12); border-color: rgba(98,168,255,.24); }
    button.warn { background: rgba(245,184,75,.14); border-color: rgba(245,184,75,.30); color: #ffe8b7; }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(150px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }

    .stat-card {
      position: relative;
      min-height: 112px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 15px;
      background: rgba(255,255,255,.055);
      overflow: hidden;
    }

    .stat-card::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 3px;
      background: linear-gradient(90deg, var(--cyan), var(--blue), var(--violet));
      opacity: .86;
    }

    .stat-label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .08em;
      font-weight: 850;
      margin-bottom: 10px;
    }

    .stat-value {
      font-size: clamp(18px, 2vw, 28px);
      font-weight: 900;
      line-height: 1.05;
      overflow-wrap: anywhere;
    }

    .stat-sub {
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }

    .tabs {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 7px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(255,255,255,.045);
      margin-bottom: 14px;
    }

    .tab {
      flex: 0 0 auto;
      min-height: 38px;
      color: var(--soft);
      background: transparent;
      border-color: transparent;
    }

    .tab.active {
      color: #06111e;
      background: linear-gradient(135deg, var(--cyan), var(--blue));
      box-shadow: 0 10px 24px rgba(39,211,216,.22);
    }

    .panel {
      padding: 18px;
      margin-bottom: 16px;
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      margin-bottom: 14px;
    }

    .panel h2 { margin: 0; font-size: 18px; }
    .panel p { color: var(--soft); line-height: 1.55; }
    .hidden { display: none !important; }
    .muted { color: var(--muted); }

    .chart-wrap {
      position: relative;
      min-height: 420px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #0d1422;
      overflow: hidden;
    }

    canvas {
      display: block;
      width: 100%;
      height: 420px;
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(8,13,24,.46);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }

    th, td {
      padding: 11px 12px;
      border-bottom: 1px solid rgba(148,163,184,.14);
      text-align: left;
      font-size: 13px;
      vertical-align: top;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #111a2b;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .07em;
      font-size: 11px;
    }

    tr:hover td { background: rgba(255,255,255,.03); }

    pre {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #080d18;
      color: #d8e1ef;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      max-height: 420px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.45;
    }

    iframe {
      width: 100%;
      min-height: 780px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: white;
    }

    .empty {
      border: 1px dashed rgba(148,163,184,.28);
      border-radius: var(--radius);
      padding: 28px;
      color: var(--muted);
      text-align: center;
      background: rgba(255,255,255,.025);
    }

    .toast {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 20;
      max-width: min(420px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px 14px;
      background: rgba(12, 18, 31, .94);
      box-shadow: var(--shadow);
      color: var(--soft);
      transform: translateY(18px);
      opacity: 0;
      pointer-events: none;
      transition: transform .18s ease, opacity .18s ease;
    }

    .toast.show { transform: translateY(0); opacity: 1; }

    @media (max-width: 1180px) {
      .app-shell { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .brand { grid-column: 1 / -1; margin-bottom: 0; }
      .side-card { margin-bottom: 0; }
      .hero { grid-template-columns: 1fr; }
      .stats-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }

    @media (max-width: 760px) {
      .app-shell { display: flex; flex-direction: column; }
      .content { order: 1; }
      .sidebar { order: 2; }
      .content { padding: 14px; }
      .sidebar { padding: 14px; grid-template-columns: 1fr; }
      .hero-main { padding: 20px; }
      .control-grid, .toggle-row, .actions { grid-template-columns: 1fr; }
      .stats-grid { grid-template-columns: 1fr 1fr; }
      canvas { height: 340px; }
      .chart-wrap { min-height: 340px; }
      .tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); overflow: visible; }
      .tab { width: 100%; }
    }

    @media (max-width: 520px) {
      .stats-grid { grid-template-columns: 1fr; }
      .hero-title { font-size: 30px; }
      .panel-header { flex-direction: column; }
    }
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar" aria-label="System summary">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">K</div>
      <div>
        <h1>Capital Kronos</h1>
        <p>Signal intelligence console</p>
      </div>
    </div>
    <div class="side-card">
      <div class="side-label">Runtime</div>
      <div class="side-value" id="runtimeStatus">Loading</div>
      <div class="side-note">Data-only signal generation. No order execution is implemented.</div>
    </div>
    <div class="side-card">
      <div class="side-label">Latest Service Heartbeats</div>
      <div class="side-value" id="heartbeatStatus">Waiting for status</div>
    </div>
    <div class="side-card">
      <div class="side-label">Local Time Display</div>
      <div class="side-value">Asia/Amman</div>
    </div>
  </aside>

  <main class="content">
    <section class="hero">
      <div class="hero-main">
        <div>
          <div class="eyebrow">ETHUSD forecasting and signal validation</div>
          <h1 class="hero-title">Kronos signal cockpit for live market decisions.</h1>
          <p class="hero-copy">Monitor Capital.com candles, Kronos forecast paths, PostgreSQL outcomes, and validation quality in one responsive production console.</p>
        </div>
        <div class="hero-meta" id="heroMeta">
          <span class="badge info">Loading market state</span>
        </div>
      </div>

      <section class="control-panel" aria-label="Prediction controls">
        <div class="control-title">
          <h2>Run Controls</h2>
          <span class="badge info" id="controlBadge">Ready</span>
        </div>
        <div class="control-grid">
          <label class="field">Market <input id="market" value="ETHUSD" autocomplete="off"></label>
          <label class="field">Resolution <select id="resolution"><option>MINUTE_5</option><option>MINUTE_15</option><option>MINUTE_30</option><option>HOUR</option></select></label>
          <label class="field">Prediction Length <input id="predLen" type="number" value="12" min="1" max="120"></label>
          <label class="field">Lookback <input id="lookback" type="number" value="512" min="50" max="512"></label>
          <label class="field">Feature Set <select id="featureSet"><option>auto</option><option>ohlc</option><option>ohlcv</option><option>ohlcva</option></select></label>
          <label class="field">Auto Refresh <select id="autoRefresh"><option value="0">Off</option><option value="30">30 sec</option><option value="60">60 sec</option><option value="300">5 min</option></select></label>
        </div>
        <div class="toggle-row">
          <label class="toggle"><span>Repair OHLC</span><input id="repairOhlc" type="checkbox" checked></label>
          <label class="toggle"><span>Auto predict</span><input id="autoPredict" type="checkbox"></label>
        </div>
        <div class="actions">
          <button id="predict" class="primary">Run Prediction</button>
          <button id="refresh" class="secondary">Refresh</button>
          <button id="fetchActual" class="warn">Fetch Actuals</button>
          <button id="validateActual" class="warn">Validate Actuals</button>
          <button id="baselines" class="secondary">Run Baselines</button>
        </div>
      </section>
    </section>

    <section class="stats-grid" id="summaryCards" aria-label="Key metrics"></section>

    <nav class="tabs" aria-label="Dashboard sections">
      <button class="tab active" data-tab="overview">Overview</button>
      <button class="tab" data-tab="forecast">Forecast Chart</button>
      <button class="tab" data-tab="candles">Candles</button>
      <button class="tab" data-tab="validation">Validation</button>
      <button class="tab" data-tab="baselines">Baselines</button>
      <button class="tab" data-tab="risk">Risk</button>
      <button class="tab" data-tab="history">History</button>
      <button class="tab" data-tab="files">Files</button>
      <button class="tab" data-tab="logs">Logs</button>
      <button class="tab" data-tab="report">Embedded Report</button>
    </nav>

    <section id="overview" class="panel tabPanel"></section>
    <section id="forecast" class="panel tabPanel hidden"><div class="panel-header"><div><h2>Actual + Forecast Close</h2><p class="muted">Blue is actual history, cyan is forecast path.</p></div></div><div class="chart-wrap"><canvas id="closeChart" width="1200" height="420"></canvas></div></section>
    <section id="candles" class="panel tabPanel hidden"><div class="panel-header"><div><h2>Historical + Forecast Candles</h2><p class="muted">Historical and generated candles share the same price scale.</p></div></div><div class="chart-wrap"><canvas id="candleChart" width="1200" height="420"></canvas></div></section>
    <section id="validation" class="panel tabPanel hidden"></section>
    <section id="baselines" class="panel tabPanel hidden"></section>
    <section id="risk" class="panel tabPanel hidden"></section>
    <section id="history" class="panel tabPanel hidden"></section>
    <section id="files" class="panel tabPanel hidden"></section>
    <section id="logs" class="panel tabPanel hidden"><div class="panel-header"><h2>Logs</h2><span class="badge info">Action output</span></div><pre id="log">No actions run in this browser session.</pre></section>
    <section id="report" class="panel tabPanel hidden"><div class="panel-header"><div><h2>Generated Prediction Report</h2><p class="muted">Reports render inline after a prediction run.</p></div><div id="reportLink" class="badge info">No report yet</div></div><iframe id="reportFrame" class="hidden" title="Prediction report"></iframe></section>
  </main>
</div>
<div id="toast" class="toast" role="status" aria-live="polite"></div>

<script>
let latest = {};
let refreshTimer = null;
let lastAutoInputEnd = null;
let autoPredictBusy = false;
const $ = id => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function fmt(n, digits=4) {
  return n === null || n === undefined || Number.isNaN(Number(n)) ? 'n/a' : Number(n).toFixed(digits);
}

function statusClass(value) {
  const text = String(value || '').toUpperCase();
  if (['OK','VALIDATED','WIN','PROMISING','LONG','UP'].includes(text)) return 'good';
  if (['PENDING','PARTIAL','HOLD','NEEDS_MORE_SAMPLES','FLAT'].includes(text)) return 'warn';
  if (['ERROR','LOSS','WEAK','NOT_TRADABLE','SHORT','DOWN'].includes(text)) return 'bad';
  return 'info';
}

function badge(value, extra='') {
  return `<span class="badge ${statusClass(value)} ${extra}">${escapeHtml(value ?? 'n/a')}</span>`;
}

function stat(label, value, sub='') {
  return `<article class="stat-card"><div class="stat-label">${escapeHtml(label)}</div><div class="stat-value">${escapeHtml(value ?? 'n/a')}</div>${sub ? `<div class="stat-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 3600);
}

function setBusy(isBusy, label='Working') {
  $('predict').disabled = isBusy;
  $('controlBadge').className = `badge ${isBusy ? 'warn' : 'info'}`;
  $('controlBadge').textContent = isBusy ? label : 'Ready';
}

function setTab(name) {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tabPanel').forEach(p => p.classList.toggle('hidden', p.id !== name));
  if (name === 'forecast') drawCloseChart();
  if (name === 'candles') drawCandleChart();
}

function resizeCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(320, rect.width);
  const cssHeight = Number.parseFloat(getComputedStyle(canvas).height) || 420;
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: cssWidth, h: cssHeight };
}

function drawLine(ctx, points, color, width=2) {
  if (points.length < 2) return;
  ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = width;
  points.forEach((p,i) => i ? ctx.lineTo(p.x,p.y) : ctx.moveTo(p.x,p.y));
  ctx.stroke();
}

function chartScale(rows, keys, w, h) {
  const vals = [];
  rows.forEach(r => keys.forEach(k => { if (r[k] !== undefined && r[k] !== null && !Number.isNaN(Number(r[k]))) vals.push(Number(r[k])); }));
  let min = Math.min(...vals), max = Math.max(...vals);
  if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
  if (min === max) { min -= 1; max += 1; }
  const pad = 42;
  return {
    x: i => pad + i * ((w - pad * 2) / Math.max(rows.length - 1, 1)),
    y: v => h - pad - ((v - min) / (max - min)) * (h - pad * 2),
    min, max, pad
  };
}

function drawGrid(ctx, s, w, h) {
  ctx.strokeStyle = 'rgba(148,163,184,.16)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = s.pad + i * ((h - s.pad * 2) / 4);
    ctx.beginPath(); ctx.moveTo(s.pad, y); ctx.lineTo(w - s.pad, y); ctx.stroke();
  }
  ctx.fillStyle = '#9aa8bd';
  ctx.font = '12px Segoe UI, Arial';
  ctx.fillText(fmt(s.max, 2), 10, s.pad + 4);
  ctx.fillText(fmt(s.min, 2), 10, h - s.pad + 4);
}

function drawCloseChart() {
  const canvas = $('closeChart'); if (!canvas) return;
  const {ctx, w, h} = resizeCanvas(canvas);
  ctx.clearRect(0,0,w,h);
  const actual = latest.actual_tail || [];
  const forecast = latest.forecast || [];
  const rows = [...actual.map(r => ({...r, type:'actual'})), ...forecast.map(r => ({...r, type:'forecast'}))];
  if (!rows.length) { drawEmptyChart(ctx, w, h, 'No close data available'); return; }
  const s = chartScale(rows, ['close'], w, h);
  drawGrid(ctx, s, w, h);
  drawLine(ctx, actual.map((r,i) => ({x:s.x(i), y:s.y(Number(r.close))})), '#62a8ff', 2.4);
  const offset = actual.length;
  drawLine(ctx, forecast.map((r,i) => ({x:s.x(offset+i), y:s.y(Number(r.close))})), '#27d3d8', 2.6);
  if (forecast.length) {
    const x = s.x(offset);
    ctx.strokeStyle = '#f5b84b'; ctx.setLineDash([6,6]);
    ctx.beginPath(); ctx.moveTo(x,s.pad); ctx.lineTo(x,h-s.pad); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.fillStyle = '#cbd5e1'; ctx.font = '12px Segoe UI, Arial';
  ctx.fillText('Actual history', s.pad, 22);
  ctx.fillStyle = '#27d3d8'; ctx.fillText('Forecast path', s.pad + 112, 22);
}

function drawCandleChart() {
  const canvas = $('candleChart'); if (!canvas) return;
  const {ctx, w, h} = resizeCanvas(canvas);
  ctx.clearRect(0,0,w,h);
  const actual = (latest.actual_tail || []).slice(-72);
  const forecast = latest.forecast || [];
  const rows = [...actual.map(r => ({...r, type:'actual'})), ...forecast.map(r => ({...r, type:'forecast'}))];
  if (!rows.length) { drawEmptyChart(ctx, w, h, 'No candle data available'); return; }
  const s = chartScale(rows, ['open','high','low','close'], w, h);
  drawGrid(ctx, s, w, h);
  const step = (w - s.pad * 2) / Math.max(rows.length, 1);
  rows.forEach((r,i) => {
    const x = s.pad + i * step + step / 2;
    const o = Number(r.open), c = Number(r.close), hi = Number(r.high), lo = Number(r.low);
    const up = c >= o;
    const color = r.type === 'forecast' ? (up ? '#27d3d8' : '#f5b84b') : (up ? '#3ddc97' : '#ff6b6b');
    ctx.strokeStyle = color; ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(x, s.y(hi)); ctx.lineTo(x, s.y(lo)); ctx.stroke();
    const y = Math.min(s.y(o), s.y(c)); const bh = Math.max(Math.abs(s.y(o)-s.y(c)), 2);
    ctx.fillRect(x - Math.max(step*.26,2), y, Math.max(step*.52,3), bh);
  });
}

function drawEmptyChart(ctx, w, h, text) {
  ctx.fillStyle = '#9aa8bd';
  ctx.font = '14px Segoe UI, Arial';
  ctx.textAlign = 'center';
  ctx.fillText(text, w / 2, h / 2);
  ctx.textAlign = 'left';
}

function renderHeartbeat(pg) {
  const beats = pg.heartbeats || [];
  if (!beats.length) return 'No workers yet';
  return beats.map(row => `${escapeHtml(row.service_name)} ${badge(row.status)}`).join('<br>');
}

function render(data) {
  latest = data;
  const m = data.metadata || {}, v = data.validation || {};
  const db = data.prediction_db || {};
  const pg = data.postgres_snapshot || {};
  const latestSignal = (pg.signals || [])[0] || {};
  const postgresOk = pg.postgres?.ok === true;
  const signal = latestSignal.signal || 'n/a';

  $('runtimeStatus').innerHTML = postgresOk ? badge('PostgreSQL OK') : badge('PostgreSQL Offline');
  $('heartbeatStatus').innerHTML = renderHeartbeat(pg);
  $('heroMeta').innerHTML = [
    badge(signal),
    badge(v.forecast_direction || 'Direction pending'),
    badge(postgresOk ? 'PostgreSQL OK' : 'PostgreSQL Offline'),
    `<span class="badge info">${escapeHtml(m.resolution || latestSignal.resolution || 'MINUTE_5')}</span>`
  ].join('');

  $('summaryCards').innerHTML = [
    stat('Last Close', fmt(m.last_input_close), 'Latest input candle close'),
    stat('Forecast Close', fmt(v.last_forecast_close), `${escapeHtml(v.forecast_direction || 'pending')} direction`),
    stat('Signal', signal, `${fmt(latestSignal.confidence, 3)} confidence`),
    stat('Expected Move', `${fmt(v.max_abs_close_move_pct)}%`, `${m.forecast_horizon_minutes || v.forecast_horizon_minutes || 'n/a'} minute horizon`),
    stat('Win Rate', db.win_rate_pct === null || db.win_rate_pct === undefined ? 'n/a' : `${Number(db.win_rate_pct).toFixed(2)}%`, `${db.wins ?? 0} WIN / ${db.losses ?? 0} LOSS`),
    stat('Pending', db.pending ?? 0, 'Forecast rows awaiting actuals'),
  ].join('');

  const signals = pg.signals || [];
  const signalRows = signals.length ? signals.map(r => `<tr><td>${escapeHtml(r.timestamp_utc)}</td><td>${badge(r.signal)}</td><td>${escapeHtml(r.direction || '')}</td><td>${fmt(r.confidence, 3)}</td><td>${fmt(r.expected_move_pct)}%</td><td>${escapeHtml(r.run_status || '')}</td></tr>`).join('') : `<tr><td colspan="6"><div class="empty">No PostgreSQL signals yet.</div></td></tr>`;
  const outcomes = (pg.outcomes || []).map(r => `${escapeHtml(r.status)}: ${escapeHtml(r.count)}`).join(' | ') || 'No outcomes yet';

  $('overview').innerHTML = `
    <div class="panel-header"><div><h2>Signal Engine Overview</h2><p class="muted">Live operational view of forecast generation, persistence, and validation.</p></div>${badge(signal)}</div>
    <div class="table-wrap"><table><thead><tr><th>Generated</th><th>Signal</th><th>Direction</th><th>Confidence</th><th>Move</th><th>Status</th></tr></thead><tbody>${signalRows}</tbody></table></div>
    <p><b>Latest forecast:</b> ${escapeHtml(m.forecast_start_timestamp || 'n/a')} to ${escapeHtml(m.forecast_end_timestamp || 'n/a')}</p>
    <p><b>Outcome mix:</b> ${escapeHtml(outcomes)}</p>`;

  $('validation').innerHTML = `<div class="panel-header"><h2>Validation Payload</h2>${badge(v.quality_status || 'PENDING')}</div><pre>${escapeHtml(JSON.stringify(v, null, 2))}</pre>`;
  $('risk').innerHTML = `<div class="panel-header"><h2>Forecast Confidence / Risk</h2>${badge(v.movement_after_cost_warning ? 'Cost Warning' : 'Cost Clear')}</div><pre>${escapeHtml(JSON.stringify(v.trading_usefulness || {}, null, 2))}</pre><p><b>Input rows:</b> ${escapeHtml(v.input_rows_used || m.input_rows_used || 'n/a')}/512</p><p><b>Analysis only:</b> no execution logic.</p>`;
  $('files').innerHTML = `<div class="panel-header"><h2>Generated Files</h2><span class="badge info">Artifacts</span></div><div class="table-wrap"><table><thead><tr><th>Type</th><th>Path</th></tr></thead><tbody>${Object.entries(data.files || {}).map(([k,p]) => p ? `<tr><td>${escapeHtml(k)}</td><td><a target="_blank" href="/file?path=${encodeURIComponent(p)}">${escapeHtml(p)}</a></td></tr>` : '').join('') || '<tr><td colspan="2">No files found.</td></tr>'}</tbody></table></div>`;
  $('history').innerHTML = `<div class="panel-header"><h2>Run History</h2><span class="badge info">${(db.recent_runs || []).length} DB runs</span></div>${renderHistory(data, db)}`;
  $('baselines').innerHTML = `<div class="panel-header"><h2>Baselines</h2><span class="badge info">Comparisons</span></div><pre>${escapeHtml(JSON.stringify(data.baseline_summary || {}, null, 2))}</pre>`;
  drawCloseChart(); drawCandleChart();
}

function renderHistory(data, db) {
  const fileRows = (data.history || []).map(r => `<tr><td>${escapeHtml(r.generated_at_local || '')}</td><td>${escapeHtml(r.forecast_start || '')}<br>${escapeHtml(r.forecast_end || '')}</td><td>${escapeHtml(r.resolution || '')}</td><td>${escapeHtml(r.direction || '')}</td><td>${escapeHtml(r.quality_status || '')}</td><td>${r.forecast_path ? `<a target="_blank" href="/file?path=${encodeURIComponent(r.forecast_path)}">CSV</a>` : ''}</td></tr>`).join('');
  const dbRows = (db.recent_runs || []).map(r => `<tr><td>${escapeHtml(r.run_id || '')}<br><span class="muted">${escapeHtml(r.epic || '')} ${escapeHtml(r.resolution || '')}</span></td><td>${escapeHtml(r.forecast_start_timestamp_utc || '')}<br>${escapeHtml(r.forecast_end_timestamp_utc || '')}</td><td>${badge(r.run_status)}</td><td>${escapeHtml(r.signal || '')}</td><td>${escapeHtml(r.wins || 0)}</td><td>${escapeHtml(r.losses || 0)}</td><td>${escapeHtml(r.pending || 0)}</td></tr>`).join('');
  return `
    <h3>File Artifacts</h3><div class="table-wrap"><table><thead><tr><th>Generated</th><th>Window</th><th>Resolution</th><th>Direction</th><th>Quality</th><th>Forecast</th></tr></thead><tbody>${fileRows || '<tr><td colspan="6">No file history found.</td></tr>'}</tbody></table></div>
    <h3>PostgreSQL Runs</h3><div class="table-wrap"><table><thead><tr><th>Run</th><th>Window UTC</th><th>Status</th><th>Signal</th><th>WIN</th><th>LOSS</th><th>PENDING</th></tr></thead><tbody>${dbRows || '<tr><td colspan="7">No DB run history found.</td></tr>'}</tbody></table></div>`;
}

async function refreshStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    render(data);
    if (!$('autoPredict').checked || autoPredictBusy) return;
    const currentInputEnd = data.metadata?.input_end_timestamp || null;
    if (!lastAutoInputEnd) { lastAutoInputEnd = currentInputEnd; return; }
    const forecastEnd = data.metadata?.forecast_end_timestamp ? Date.parse(data.metadata.forecast_end_timestamp) : null;
    const forecastExpired = forecastEnd && Date.now() > forecastEnd;
    if ((currentInputEnd && currentInputEnd !== lastAutoInputEnd) || forecastExpired) {
      autoPredictBusy = true;
      try {
        await runPrediction();
        const after = await (await fetch('/api/status')).json();
        lastAutoInputEnd = after.metadata?.input_end_timestamp || currentInputEnd;
      } finally { autoPredictBusy = false; }
    }
  } catch (err) {
    showToast(`Status refresh failed: ${err.message}`);
  }
}

async function postJson(url, payload={}) {
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const data = await res.json();
  $('log').textContent = data.output || data.error || JSON.stringify(data, null, 2);
  if (data.report_url) {
    $('reportFrame').src = data.report_url;
    $('reportFrame').classList.remove('hidden');
    $('reportLink').innerHTML = `<a target="_blank" href="${data.report_url}">Open generated report</a>`;
  }
  await refreshStatus();
  return data;
}

async function runPrediction() {
  setBusy(true, 'Running');
  $('log').textContent = 'Running prediction...';
  try {
    await postJson('/api/predict', {
      market:$('market').value, resolution:$('resolution').value, pred_len:Number($('predLen').value),
      lookback:Number($('lookback').value), feature_set:$('featureSet').value, repair_ohlc:$('repairOhlc').checked
    });
    setTab('forecast');
    showToast('Prediction complete');
  } catch (err) {
    $('log').textContent = err.message;
    showToast(`Prediction failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function setupAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  const seconds = Number($('autoRefresh').value);
  if (seconds > 0) refreshTimer = setInterval(refreshStatus, seconds * 1000);
}

document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
$('predict').addEventListener('click', runPrediction);
$('refresh').addEventListener('click', () => { refreshStatus(); showToast('Dashboard refreshed'); });
$('fetchActual').addEventListener('click', () => postJson('/api/fetch-actual').then(() => showToast('Actual fetch finished')));
$('validateActual').addEventListener('click', () => postJson('/api/validate-actual').then(() => showToast('Validation finished')));
$('baselines').addEventListener('click', () => postJson('/api/baselines').then(() => showToast('Baseline run finished')));
$('autoRefresh').addEventListener('change', setupAutoRefresh);
$('autoPredict').addEventListener('change', () => { lastAutoInputEnd = latest.metadata?.input_end_timestamp || null; });
window.addEventListener('resize', () => { drawCloseChart(); drawCandleChart(); });
refreshStatus(); setupAutoRefresh();
</script>
</body>
</html>"""
