from __future__ import annotations


def dashboard_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kronos Signal Dashboard</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

    :root {
      --bg: #071018;
      --bg-2: #0c1a25;
      --panel: rgba(14, 26, 38, 0.86);
      --panel-2: rgba(19, 33, 46, 0.9);
      --line: rgba(126, 167, 199, 0.2);
      --text: #eaf4ff;
      --muted: #90a9bc;
      --teal: #3fd5c5;
      --blue: #57a4ff;
      --amber: #f6b35b;
      --green: #4ee38d;
      --red: #ff7070;
      --radius: 14px;
      --shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
    }

    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      font-family: "Space Grotesk", "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(1200px 600px at 8% -10%, rgba(63, 213, 197, 0.2), transparent 60%),
        radial-gradient(1100px 560px at 90% -15%, rgba(87, 164, 255, 0.2), transparent 60%),
        linear-gradient(135deg, #050d14 0%, #08121c 30%, #0a1823 100%);
      letter-spacing: 0.01em;
    }

    .ambient {
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(126, 167, 199, 0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(126, 167, 199, 0.045) 1px, transparent 1px);
      background-size: 24px 24px;
      mask-image: radial-gradient(circle at 50% 10%, rgba(0, 0, 0, 1), rgba(0, 0, 0, 0.2));
      z-index: 0;
    }

    .shell {
      position: relative;
      z-index: 1;
      max-width: 1560px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      gap: 16px;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015));
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
      animation: rise 320ms ease both;
    }

    @keyframes rise {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .topbar {
      padding: 16px 18px;
      display: grid;
      grid-template-columns: minmax(280px, 1.1fr) minmax(0, 0.9fr);
      gap: 14px;
      align-items: stretch;
    }

    .brand h1 {
      margin: 0;
      font-size: clamp(24px, 3vw, 38px);
      line-height: 1.1;
      font-weight: 700;
    }

    .title-price {
      margin-left: 10px;
      font-size: clamp(14px, 1.4vw, 22px);
      color: #95f2e4;
      font-weight: 700;
      white-space: nowrap;
    }

    .brand p {
      margin: 10px 0 0;
      color: var(--muted);
      max-width: 760px;
      font-size: 14px;
      line-height: 1.5;
    }

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      height: 100%;
    }

    .meta-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel-2);
      padding: 12px;
      min-height: 72px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 6px;
    }

    .meta-label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
    }

    .meta-value {
      font-size: 14px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .status-strip {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.05);
      padding: 6px 10px;
      min-height: 30px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }

    .chip.good { color: #b9f8d8; border-color: rgba(78,227,141,0.35); background: rgba(78,227,141,0.13); }
    .chip.warn { color: #ffe5ba; border-color: rgba(246,179,91,0.35); background: rgba(246,179,91,0.13); }
    .chip.bad { color: #ffc5c5; border-color: rgba(255,112,112,0.35); background: rgba(255,112,112,0.13); }
    .chip.info { color: #d4e8ff; border-color: rgba(87,164,255,0.35); background: rgba(87,164,255,0.13); }

    .control-board {
      padding: 16px;
      display: grid;
      gap: 12px;
    }

    .control-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }

    .control-head h2 {
      margin: 0;
      font-size: 18px;
    }

    .control-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    input, select {
      width: 100%;
      min-height: 40px;
      border: 1px solid rgba(126, 167, 199, 0.3);
      border-radius: 10px;
      background: rgba(8, 15, 22, 0.92);
      color: var(--text);
      padding: 8px 10px;
      outline: none;
      font: inherit;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }

    input:focus, select:focus {
      border-color: rgba(63, 213, 197, 0.8);
      box-shadow: 0 0 0 3px rgba(63, 213, 197, 0.16);
    }

    .toggle-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .toggle-card {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      min-height: 44px;
      padding: 8px 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: var(--text);
      font-size: 13px;
      font-weight: 600;
    }

    .toggle-card input { width: 18px; min-height: 18px; accent-color: var(--teal); }

    .actions {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }

    button {
      border: 1px solid rgba(126, 167, 199, 0.3);
      border-radius: 10px;
      min-height: 42px;
      padding: 9px 12px;
      color: var(--text);
      background: rgba(255,255,255,0.07);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }

    button:hover { transform: translateY(-1px); border-color: rgba(255,255,255,0.34); }
    button:disabled { opacity: 0.6; cursor: wait; transform: none; }

    .btn-primary {
      background: linear-gradient(135deg, #2f85ff, #3fd5c5);
      color: #031018;
      border-color: rgba(63, 213, 197, 0.6);
    }

    .btn-alt { background: rgba(87,164,255,0.14); }
    .btn-warn { background: rgba(246,179,91,0.18); color: #ffe7bf; }

    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }

    .kpi {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel);
      min-height: 108px;
      padding: 12px;
      position: relative;
      overflow: hidden;
    }

    .kpi::before {
      content: "";
      position: absolute;
      inset: 0 auto auto 0;
      width: 100%;
      height: 3px;
      background: linear-gradient(90deg, var(--teal), var(--blue));
    }

    .kpi-label {
      font-size: 11px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0.08em;
      font-weight: 700;
      margin-bottom: 8px;
    }

    .kpi-value {
      font-size: clamp(18px, 2vw, 26px);
      font-weight: 700;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }

    .kpi-sub {
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }

    .model-status-panel {
      padding: 14px;
      display: grid;
      gap: 12px;
    }

    .model-status-grid {
      display: grid;
      grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.2fr);
      gap: 14px;
      align-items: center;
    }

    .model-version-title {
      font-size: 24px;
      line-height: 1.15;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .model-progress-area {
      display: grid;
      gap: 8px;
    }

    .progress-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .progress-track {
      height: 12px;
      border-radius: 8px;
      border: 1px solid rgba(126, 167, 199, 0.28);
      background: rgba(7, 16, 24, 0.9);
      overflow: hidden;
    }

    .progress-fill {
      height: 100%;
      border-radius: 8px;
      background: linear-gradient(90deg, var(--teal), var(--green));
      transition: width 220ms ease;
    }

    .model-progress-sub {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }

    .model-metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .model-stat {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      min-height: 62px;
      padding: 9px 10px;
      display: grid;
      align-content: center;
      gap: 4px;
    }

    .model-stat-label {
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-weight: 700;
    }

    .model-stat-value {
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .chart-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .chart-panel {
      padding: 14px;
    }

    .panel-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 10px;
    }

    .panel-head h3, .panel-head h2 {
      margin: 0;
      font-size: 18px;
    }

    .panel-head p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }

    .chart-wrap {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #07121b;
      min-height: 360px;
      overflow: hidden;
    }

    canvas {
      width: 100%;
      height: 360px;
      display: block;
    }

    .tabs {
      display: grid;
      grid-template-columns: repeat(8, minmax(0, 1fr));
      gap: 8px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel);
    }

    .tab {
      min-height: 36px;
      background: rgba(255,255,255,0.03);
      border-color: transparent;
      color: var(--muted);
    }

    .tab.active {
      background: linear-gradient(135deg, #3fd5c5, #57a4ff);
      color: #031018;
      border-color: rgba(63,213,197,0.6);
    }

    .details-panel {
      padding: 14px;
    }

    .hidden { display: none !important; }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(7, 17, 26, 0.8);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 780px;
    }

    th, td {
      border-bottom: 1px solid rgba(126, 167, 199, 0.16);
      padding: 10px 11px;
      text-align: left;
      font-size: 12px;
      vertical-align: top;
    }

    th {
      background: rgba(14, 29, 42, 0.95);
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-size: 10px;
      position: sticky;
      top: 0;
      z-index: 1;
    }

    tr:hover td { background: rgba(255,255,255,0.03); }

    pre {
      margin: 0;
      background: rgba(6, 12, 18, 0.95);
      border: 1px solid var(--line);
      border-radius: 10px;
      color: #d8e8f6;
      padding: 12px;
      max-height: 380px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.45;
    }

    iframe {
      width: 100%;
      min-height: 720px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fff;
    }

    .muted { color: var(--muted); }

    .empty {
      border: 1px dashed rgba(126, 167, 199, 0.3);
      border-radius: 10px;
      padding: 24px;
      text-align: center;
      color: var(--muted);
    }

    .warning-stack {
      display: grid;
      gap: 8px;
      margin-bottom: 10px;
    }

    .validation-banner {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      margin: 10px 0 12px;
      display: grid;
      gap: 4px;
    }

    .validation-banner-title {
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }

    .validation-banner-text {
      font-size: 12px;
      line-height: 1.4;
    }

    .validation-banner.good {
      border-color: rgba(78,227,141,0.35);
      background: rgba(78,227,141,0.13);
      color: #b9f8d8;
    }

    .validation-banner.warn {
      border-color: rgba(246,179,91,0.35);
      background: rgba(246,179,91,0.13);
      color: #ffe5ba;
    }

    .validation-banner.bad {
      border-color: rgba(255,112,112,0.35);
      background: rgba(255,112,112,0.13);
      color: #ffc5c5;
    }

    .warning-item {
      border: 1px solid rgba(246,179,91,0.35);
      border-radius: 10px;
      background: rgba(246,179,91,0.13);
      color: #ffe2b2;
      padding: 9px 11px;
      font-size: 12px;
      line-height: 1.4;
    }

    .tiny-help {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      margin-top: 4px;
    }

    .mini-copy {
      min-height: 24px;
      padding: 3px 7px;
      font-size: 11px;
      border-radius: 8px;
      margin-left: 6px;
    }

    .signal-id-line {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
    }

    .signal-group-row td {
      vertical-align: middle;
    }

    .signal-group-start td {
      border-top: 1px solid rgba(126, 167, 199, 0.16);
    }

    .signal-variant-label {
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 700;
    }

    .signal-badge-cell {
      white-space: nowrap;
    }

    .signal-numeric {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .signal-actions {
      display: grid;
      gap: 6px;
      justify-items: start;
    }

    .signal-actions .mini-copy {
      margin-left: 0;
    }

    .signal-note-row td {
      padding-top: 6px;
      padding-bottom: 10px;
    }

    .signal-note {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }

    .signal-table-footer {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      gap: 10px;
    }

    .signal-pagination-left {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .signal-pagination-pages {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }

    .signal-pagination-right {
      margin-left: auto;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 4px;
      min-width: 250px;
      text-align: right;
    }

    .signal-page-size-field {
      min-width: 132px;
      max-width: 176px;
      margin: 0;
      text-align: left;
    }

    .worker-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }

    .worker-item {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      padding: 8px 10px;
      min-height: 66px;
      display: grid;
      align-content: center;
      gap: 4px;
    }

    .worker-name {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-weight: 700;
    }

    @media (max-width: 1280px) {
      .worker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .model-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }

    @media (max-width: 640px) {
      .worker-grid { grid-template-columns: 1fr; }
      .model-status-grid { grid-template-columns: 1fr; }
      .model-metrics { grid-template-columns: 1fr; }
    }

    .loader-overlay {
      position: fixed;
      inset: 0;
      z-index: 30;
      background: rgba(4, 8, 12, 0.62);
      backdrop-filter: blur(2px);
      display: grid;
      place-items: center;
    }

    .loader-card {
      width: min(320px, calc(100vw - 30px));
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(8, 18, 28, 0.95);
      box-shadow: var(--shadow);
      padding: 18px;
      display: grid;
      gap: 12px;
      place-items: center;
      text-align: center;
    }

    .spinner {
      width: 38px;
      height: 38px;
      border-radius: 999px;
      border: 3px solid rgba(87, 164, 255, 0.26);
      border-top-color: var(--teal);
      animation: spin 760ms linear infinite;
    }

    @keyframes spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 40;
      max-width: min(420px, calc(100vw - 28px));
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(8, 17, 26, 0.95);
      box-shadow: var(--shadow);
      color: var(--text);
      padding: 10px 12px;
      opacity: 0;
      transform: translateY(16px);
      pointer-events: none;
      transition: transform 140ms ease, opacity 140ms ease;
    }

    .toast.show { opacity: 1; transform: translateY(0); }

    @media (max-width: 1280px) {
      .control-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .tabs { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .topbar { grid-template-columns: 1fr; }
    }

    @media (max-width: 900px) {
      .chart-grid { grid-template-columns: 1fr; }
      .actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .toggle-row { grid-template-columns: 1fr; }
      .signal-pagination-right {
        width: 100%;
        margin-left: 0;
        align-items: flex-start;
        text-align: left;
      }
    }

    @media (max-width: 640px) {
      .shell { padding: 12px; }
      .control-grid { grid-template-columns: 1fr; }
      .kpi-grid { grid-template-columns: 1fr; }
      .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .actions { grid-template-columns: 1fr; }
      canvas { height: 300px; }
      .chart-wrap { min-height: 300px; }
    }

    /* Apple-inspired visual system override. Keeps all DOM IDs, handlers, and API mappings intact. */
    :root {
      color-scheme: light;
      --font-ui: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
      --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      --bg: #f5f5f7;
      --bg-2: #ffffff;
      --panel: rgba(255, 255, 255, 0.72);
      --panel-2: rgba(255, 255, 255, 0.9);
      --line: rgba(34, 34, 38, 0.12);
      --line-strong: rgba(34, 34, 38, 0.2);
      --text: #1d1d1f;
      --muted: #6e6e73;
      --teal: #00a889;
      --blue: #007aff;
      --amber: #bf7a00;
      --green: #248a3d;
      --red: #d70015;
      --indigo: #5856d6;
      --surface: rgba(255, 255, 255, 0.58);
      --surface-solid: #ffffff;
      --control: rgba(255, 255, 255, 0.82);
      --control-hover: rgba(255, 255, 255, 0.96);
      --control-pressed: rgba(235, 235, 240, 0.96);
      --radius: 22px;
      --radius-sm: 14px;
      --shadow: 0 24px 70px rgba(0, 0, 0, 0.12), 0 3px 12px rgba(0, 0, 0, 0.06);
      --shadow-soft: 0 10px 34px rgba(0, 0, 0, 0.08);
      --focus-ring: 0 0 0 4px rgba(0, 122, 255, 0.18);
    }

    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --bg: #101014;
        --bg-2: #18181d;
        --panel: rgba(34, 34, 40, 0.68);
        --panel-2: rgba(44, 44, 52, 0.86);
        --line: rgba(245, 245, 247, 0.14);
        --line-strong: rgba(245, 245, 247, 0.22);
        --text: #f5f5f7;
        --muted: #a1a1a6;
        --teal: #30d5c8;
        --blue: #0a84ff;
        --amber: #ffd60a;
        --green: #32d74b;
        --red: #ff453a;
        --indigo: #5e5ce6;
        --surface: rgba(38, 38, 46, 0.56);
        --surface-solid: #1f1f26;
        --control: rgba(58, 58, 66, 0.72);
        --control-hover: rgba(72, 72, 82, 0.86);
        --control-pressed: rgba(50, 50, 58, 0.96);
        --shadow: 0 26px 80px rgba(0, 0, 0, 0.45), 0 2px 18px rgba(0, 0, 0, 0.3);
        --shadow-soft: 0 12px 36px rgba(0, 0, 0, 0.34);
        --focus-ring: 0 0 0 4px rgba(10, 132, 255, 0.24);
      }
    }

    * { letter-spacing: 0; }

    body {
      font-family: var(--font-ui);
      color: var(--text);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0) 28%),
        linear-gradient(135deg, var(--bg) 0%, #eef1f6 46%, #f9f4ef 100%);
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }

    @media (prefers-color-scheme: dark) {
      body {
        background:
          linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0) 32%),
          linear-gradient(135deg, #101014 0%, #171822 48%, #201d1a 100%);
      }
    }

    .ambient {
      background:
        linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent),
        linear-gradient(180deg, rgba(255,255,255,0.28), transparent 42%);
      background-size: auto;
      opacity: 0.7;
      mask-image: none;
    }

    @media (prefers-color-scheme: dark) {
      .ambient {
        background:
          linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent),
          linear-gradient(180deg, rgba(255,255,255,0.08), transparent 44%);
        opacity: 1;
      }
    }

    .shell {
      max-width: 1600px;
      padding: 24px;
      gap: 18px;
    }

    .panel,
    .meta-card,
    .kpi,
    .model-stat,
    .worker-item,
    .toggle-card,
    .tabs,
    .table-wrap,
    .validation-banner,
    .warning-item,
    pre,
    iframe,
    .loader-card,
    .toast {
      border-color: var(--line);
      box-shadow: var(--shadow-soft);
      backdrop-filter: saturate(180%) blur(22px);
      -webkit-backdrop-filter: saturate(180%) blur(22px);
    }

    .panel {
      background: linear-gradient(180deg, var(--panel-2), var(--panel));
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }

    .topbar {
      padding: 24px;
      grid-template-columns: minmax(320px, 1.1fr) minmax(360px, 0.9fr);
      border-radius: 28px;
    }

    .brand h1 {
      font-size: clamp(28px, 3vw, 44px);
      font-weight: 700;
      letter-spacing: -0.01em;
    }

    .title-price {
      color: var(--blue);
      font-weight: 700;
      letter-spacing: 0;
    }

    .brand p,
    .panel-head p,
    .model-progress-sub,
    .kpi-sub,
    .tiny-help {
      color: var(--muted);
    }

    .meta-grid {
      gap: 12px;
    }

    .meta-card,
    .kpi,
    .model-stat,
    .worker-item,
    .toggle-card {
      background: var(--surface);
      border-radius: var(--radius-sm);
    }

    .meta-card {
      min-height: 82px;
      padding: 14px;
    }

    .meta-label,
    .kpi-label,
    .model-stat-label,
    .worker-name,
    .progress-row {
      color: var(--muted);
      letter-spacing: 0.04em;
      font-size: 10px;
    }

    .chip {
      border-color: var(--line);
      background: rgba(118, 118, 128, 0.11);
      color: var(--text);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.24);
    }

    .chip.good,
    .validation-banner.good {
      color: var(--green);
      border-color: color-mix(in srgb, var(--green) 34%, transparent);
      background: color-mix(in srgb, var(--green) 12%, transparent);
    }

    .chip.warn,
    .validation-banner.warn,
    .warning-item {
      color: var(--amber);
      border-color: color-mix(in srgb, var(--amber) 34%, transparent);
      background: color-mix(in srgb, var(--amber) 12%, transparent);
    }

    .chip.bad,
    .validation-banner.bad {
      color: var(--red);
      border-color: color-mix(in srgb, var(--red) 34%, transparent);
      background: color-mix(in srgb, var(--red) 12%, transparent);
    }

    .chip.info {
      color: var(--blue);
      border-color: color-mix(in srgb, var(--blue) 30%, transparent);
      background: color-mix(in srgb, var(--blue) 10%, transparent);
    }

    .control-board,
    .model-status-panel,
    .chart-panel,
    .details-panel {
      padding: 18px;
    }

    .control-head h2,
    .panel-head h2,
    .panel-head h3 {
      font-weight: 700;
      letter-spacing: -0.005em;
    }

    .control-grid {
      gap: 12px;
    }

    .field {
      color: var(--muted);
      letter-spacing: 0.01em;
    }

    input,
    select {
      min-height: 44px;
      border-radius: 13px;
      border-color: var(--line);
      background: var(--control);
      color: var(--text);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.22);
    }

    input:hover,
    select:hover {
      border-color: var(--line-strong);
      background: var(--control-hover);
    }

    input:focus,
    select:focus {
      border-color: var(--blue);
      box-shadow: var(--focus-ring);
    }

    .toggle-row,
    .actions {
      gap: 12px;
    }

    .toggle-card {
      min-height: 50px;
      padding: 10px 12px;
      color: var(--text);
    }

    .toggle-card input {
      accent-color: var(--blue);
      cursor: pointer;
    }

    button {
      min-height: 44px;
      border-radius: 14px;
      border-color: var(--line);
      background: var(--control);
      color: var(--text);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 8px 20px rgba(0,0,0,0.05);
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease, box-shadow 140ms ease, opacity 140ms ease;
    }

    button:hover {
      background: var(--control-hover);
      border-color: var(--line-strong);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.28), 0 12px 24px rgba(0,0,0,0.08);
    }

    button:active {
      transform: translateY(0) scale(0.985);
      background: var(--control-pressed);
    }

    button:focus-visible {
      outline: none;
      box-shadow: var(--focus-ring), 0 8px 20px rgba(0,0,0,0.05);
    }

    button:disabled {
      opacity: 0.48;
      cursor: not-allowed;
      box-shadow: none;
    }

    .btn-primary,
    .tab.active {
      background: linear-gradient(180deg, color-mix(in srgb, var(--blue) 84%, white), var(--blue));
      color: #ffffff;
      border-color: color-mix(in srgb, var(--blue) 70%, transparent);
      box-shadow: 0 14px 30px color-mix(in srgb, var(--blue) 24%, transparent);
    }

    .btn-alt {
      background: color-mix(in srgb, var(--blue) 10%, var(--control));
      color: var(--blue);
    }

    .btn-warn {
      background: color-mix(in srgb, var(--amber) 14%, var(--control));
      color: var(--amber);
    }

    .kpi-grid,
    .model-metrics,
    .worker-grid {
      gap: 12px;
    }

    .kpi {
      min-height: 116px;
      padding: 16px;
      overflow: hidden;
    }

    .kpi::before {
      height: 1px;
      background: linear-gradient(90deg, var(--blue), var(--teal), transparent);
      opacity: 0.7;
    }

    .kpi-value,
    .model-version-title {
      font-weight: 700;
      letter-spacing: -0.01em;
    }

    .progress-track {
      height: 10px;
      border-radius: 999px;
      border-color: var(--line);
      background: rgba(118, 118, 128, 0.16);
    }

    .progress-fill {
      border-radius: 999px;
      background: linear-gradient(90deg, var(--blue), var(--teal), var(--green));
    }

    .chart-wrap {
      border-radius: 18px;
      border-color: var(--line);
      background: color-mix(in srgb, var(--surface-solid) 74%, var(--bg));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.32);
    }

    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      border-radius: 18px;
      background: rgba(118, 118, 128, 0.12);
      box-shadow: none;
    }

    .tab {
      flex: 1 1 120px;
      min-height: 38px;
      border-radius: 12px;
      color: var(--muted);
      background: transparent;
      box-shadow: none;
    }

    .tab:not(.active):hover {
      color: var(--text);
      background: var(--control-hover);
      transform: none;
    }

    .table-wrap {
      border-radius: 16px;
      background: var(--surface);
    }

    th,
    td {
      border-bottom-color: var(--line);
      padding: 11px 12px;
    }

    th {
      background: color-mix(in srgb, var(--surface-solid) 84%, var(--bg));
      color: var(--muted);
      letter-spacing: 0.04em;
    }

    tr:hover td {
      background: rgba(118, 118, 128, 0.08);
    }

    pre {
      font-family: var(--font-mono);
      background: color-mix(in srgb, var(--surface-solid) 84%, var(--bg));
      color: var(--text);
      border-radius: 16px;
    }

    iframe {
      border-radius: 18px;
    }

    .empty {
      border-color: var(--line-strong);
      border-radius: 16px;
      color: var(--muted);
      background: rgba(118, 118, 128, 0.08);
    }

    .warning-item,
    .validation-banner {
      border-radius: 16px;
    }

    .mini-copy {
      min-height: 30px;
      border-radius: 10px;
      font-size: 11px;
    }

    .loader-overlay {
      background: rgba(242, 242, 247, 0.58);
      backdrop-filter: saturate(180%) blur(18px);
      -webkit-backdrop-filter: saturate(180%) blur(18px);
    }

    @media (prefers-color-scheme: dark) {
      .loader-overlay {
        background: rgba(0, 0, 0, 0.42);
      }
    }

    .loader-card,
    .toast {
      background: var(--panel-2);
      border-radius: 20px;
    }

    .spinner {
      border-color: color-mix(in srgb, var(--blue) 18%, transparent);
      border-top-color: var(--blue);
    }

    .toast {
      right: 22px;
      bottom: 22px;
      padding: 12px 14px;
    }

    @media (max-width: 1280px) {
      .topbar { grid-template-columns: 1fr; }
      .tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }

    @media (max-width: 640px) {
      .shell { padding: 12px; gap: 12px; }
      .topbar,
      .control-board,
      .model-status-panel,
      .chart-panel,
      .details-panel {
        padding: 14px;
      }
      .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
<div class="ambient"></div>

<div id="loader" class="loader-overlay hidden" aria-live="polite" aria-busy="true">
  <div class="loader-card">
    <div class="spinner" aria-hidden="true"></div>
    <div id="loaderText">Loading dashboard...</div>
  </div>
</div>

<div class="shell">
  <header class="topbar panel">
    <div class="brand">
          <h1>Kronos Live Signal Dashboard <span id="titlePrice" class="title-price">ETHUSD --</span></h1>
      <p>Professional market intelligence view with live price tracking, forecast quality, and signal lifecycle status.</p>
      <div class="status-strip" id="heroMeta">
        <span class="chip info">Loading market state</span>
      </div>
    </div>
    <div class="meta-grid">
      <article class="meta-card">
        <div class="meta-label">Runtime</div>
        <div class="meta-value" id="runtimeStatus">Loading</div>
      </article>
      <article class="meta-card">
        <div class="meta-label">Heartbeats</div>
        <div class="meta-value" id="heartbeatStatus">Waiting for status</div>
      </article>
      <article class="meta-card">
        <div class="meta-label">Display Timezone</div>
        <div class="meta-value">Asia/Amman</div>
      </article>
      <article class="meta-card">
        <div class="meta-label">Control Status</div>
        <div class="meta-value"><span id="controlBadge" class="chip info">Ready</span></div>
      </article>
    </div>
  </header>

  <section class="control-board panel" aria-label="Prediction controls">
    <div class="control-head">
      <h2>Live Controls</h2>
      <div class="muted">Auto mode is enabled for 5-minute candle-close prediction by default.</div>
    </div>

    <div class="control-grid">
      <label class="field">Market
        <input id="market" value="ETHUSD" autocomplete="off">
      </label>
      <label class="field">Resolution
        <select id="resolution">
          <option>MINUTE</option>
          <option selected>MINUTE_5</option>
          <option>MINUTE_15</option>
          <option>MINUTE_30</option>
          <option>HOUR</option>
        </select>
      </label>
      <label class="field">Prediction Length
        <input id="predLen" type="number" value="12" min="1" max="120">
      </label>
      <label class="field">Lookback
        <input id="lookback" type="number" value="512" min="50" max="512">
      </label>
      <label class="field">Feature Set
        <select id="featureSet">
          <option>auto</option>
          <option>ohlc</option>
          <option>ohlcv</option>
          <option>ohlcva</option>
        </select>
      </label>
      <label class="field">Auto Refresh
        <select id="autoRefresh">
          <option value="0">Off</option>
          <option value="5" selected>5 sec</option>
          <option value="10">10 sec</option>
          <option value="30">30 sec</option>
        </select>
      </label>
    </div>

    <div class="toggle-row">
      <label class="toggle-card"><span>Repair OHLC</span><input id="repairOhlc" type="checkbox" checked></label>
      <label class="toggle-card"><span>Auto Predict on Candle Close</span><input id="autoPredict" type="checkbox" checked></label>
    </div>

    <div class="actions">
      <button id="predict" class="btn-primary">Run Prediction</button>
      <button id="refresh" class="btn-alt">Refresh Snapshot</button>
      <button id="fetchActual" class="btn-warn">Fetch Actuals</button>
      <button id="validateActual" class="btn-warn">Validate Actuals</button>
      <button id="runBaselines" class="btn-alt">Run Baselines</button>
    </div>
  </section>

  <section id="modelStatusPanel" class="model-status-panel panel" aria-label="Model version and promotion progress"></section>

  <section id="summaryCards" class="kpi-grid" aria-label="Key metrics"></section>

  <section class="chart-grid">
    <article class="chart-panel panel">
      <div class="panel-head">
        <div>
          <h3>Forecast vs Actual Close</h3>
          <p>Blue is historical input, orange is forecast path, green is actual candles inside forecast window.</p>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="closeChart" width="1200" height="360"></canvas></div>
    </article>

    <article class="chart-panel panel">
      <div class="panel-head">
        <div>
          <h3>Historical and Forecast Candles</h3>
          <p>Left side is input candles, right side is forecast candles for fast visual sanity checks.</p>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="candleChart" width="1200" height="360"></canvas></div>
    </article>
  </section>

  <nav class="tabs" aria-label="Dashboard sections">
    <button class="tab active" data-tab="overview">Signals</button>
    <button class="tab" data-tab="validation">Validation</button>
    <button class="tab" data-tab="modelPerformance">Model Performance</button>
    <button class="tab" data-tab="risk">Risk</button>
    <button class="tab" data-tab="trades">Executed Signals</button>
    <button class="tab" data-tab="baselines">Baselines</button>
    <button class="tab" data-tab="history">History</button>
    <button class="tab" data-tab="files">Files</button>
    <button class="tab" data-tab="logs">Logs</button>
    <button class="tab" data-tab="report">Report</button>
  </nav>

  <section id="overview" class="details-panel panel tabPanel"></section>
  <section id="validation" class="details-panel panel tabPanel hidden"></section>
  <section id="modelPerformance" class="details-panel panel tabPanel hidden"></section>
  <section id="risk" class="details-panel panel tabPanel hidden"></section>
  <section id="trades" class="details-panel panel tabPanel hidden"></section>
  <section id="baselines" class="details-panel panel tabPanel hidden"></section>
  <section id="history" class="details-panel panel tabPanel hidden"></section>
  <section id="files" class="details-panel panel tabPanel hidden"></section>
  <section id="logs" class="details-panel panel tabPanel hidden">
    <div class="panel-head"><h2>Execution Logs</h2><span class="chip info">Action output</span></div>
    <pre id="log">No actions run in this browser session.</pre>
  </section>
  <section id="report" class="details-panel panel tabPanel hidden">
    <div class="panel-head">
      <div>
        <h2>Prediction Report</h2>
        <p class="muted">Generated HTML report is rendered inline after each successful prediction run.</p>
      </div>
      <div id="reportLink" class="chip info">No report yet</div>
    </div>
    <iframe id="reportFrame" class="hidden" title="Prediction report"></iframe>
  </section>
</div>

<div id="toast" class="toast" role="status" aria-live="polite"></div>

<script>
const DASHBOARD_TZ = 'Asia/Amman';

let latest = {};
let latestSignals = { rows: [], pagination: { page: 1, page_size: 10, total: 0, total_pages: 1, has_next: false, has_prev: false } };
let refreshTimer = null;
let refreshInFlight = false;
let autoPredictBusy = false;
let signalPage = 1;
let signalPageSize = 10;
let tradeExecutionPage = 1;
const TRADE_EXECUTION_PAGE_SIZE = 10;
let activeTab = 'overview';
let lastAutoPredictClosedBucket = null;
let lastOverviewHtml = '';
let lastOverviewRenderAtMs = 0;
const OVERVIEW_BACKGROUND_RENDER_INTERVAL_MS = 15000;
let lastRuntimeStatusKey = '';
let lastHeartbeatStatusKey = '';
let lastHeroMetaKey = '';
let lastModelStatusKey = '';
let lastSummaryCardsKey = '';
let selectedRunId = '';
let latestModelPerformance = null;
let signalFilters = {
  timeframe: '',
  dateFrom: '',
  dateTo: '',
  direction: '',
  status: '',
  signalId: '',
};
let tradeExecutionFilters = {
  lifecycle: '',
  status: '',
  outcome: '',
  side: '',
  signalId: '',
  transactionId: '',
};

const SIGNAL_FILTER_CONTROL_IDS = new Set([
  'signalsTimeframe',
  'signalsDateFrom',
  'signalsDateTo',
  'signalsDirection',
  'signalsStatus',
  'signalsSignalId',
  'signalsPageSize',
]);

const SIGNAL_FILTER_AUTO_APPLY_IDS = new Set([
  'signalsTimeframe',
  'signalsDateFrom',
  'signalsDateTo',
  'signalsDirection',
  'signalsStatus',
]);

const TRADE_FILTER_CONTROL_IDS = new Set([
  'tradeLifecycleFilter',
  'tradeStatusFilter',
  'tradeOutcomeFilter',
  'tradeSideFilter',
  'tradeSignalFilter',
  'tradeTransactionFilter',
]);

const TRADE_FILTER_AUTO_APPLY_IDS = new Set([
  'tradeLifecycleFilter',
  'tradeStatusFilter',
  'tradeOutcomeFilter',
  'tradeSideFilter',
]);

let signalIdFilterDebounceTimer = null;

const $ = id => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function fmtNumber(value, digits = 4) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? 'n/a' : Number(value).toFixed(digits);
}

function fmtCount(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString('en-US') : '0';
}

function toFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function pct01(value, digits = 2) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? 'n/a' : `${(Number(value) * 100).toFixed(digits)}%`;
}

function fmtDate(value) {
  if (!value) return 'n/a';
  const raw = String(value).trim().replace(' ', 'T');
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: DASHBOARD_TZ,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d).replace(',', '');
}

function parseTs(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function resolveLatestPrice(data) {
  const hs = data.human_summary || {};
  const pg = data.postgres_snapshot || {};
  const liveQuote = pg.live_quote || data.live_quote || {};
  const latestSignal = (pg.signals || [])[0] || {};
  if (!selectedRunId && latestSignal.run_id) selectedRunId = latestSignal.run_id;
  const candles = pg.candles || [];
  const latestCandle = candles.length ? candles[candles.length - 1] : {};
  const metadata = data.metadata || {};
  const candidates = [
    hs.latest_price,
    liveQuote.price,
    latestCandle.close,
    latestSignal.entry_price,
    metadata.last_input_close,
  ];
  for (const candidate of candidates) {
    const parsed = toFiniteNumber(candidate);
    if (parsed !== null) return parsed;
  }
  return null;
}

function resolveLatestPriceTime(data) {
  const hs = data.human_summary || {};
  const pg = data.postgres_snapshot || {};
  const liveQuote = pg.live_quote || data.live_quote || {};
  const candles = pg.candles || [];
  const latestCandle = candles.length ? candles[candles.length - 1] : {};
  return (
    hs.latest_price_time
    || hs.latest_candle_time
    || liveQuote.updated_at
    || liveQuote.timestamp_utc
    || latestCandle.timestamp_utc
    || null
  );
}

function statusClass(value) {
  const text = String(value || '').toUpperCase();
  if (['OK', 'VALIDATED', 'WIN', 'GOOD_HOLD', 'PROMISING', 'LONG', 'UP', 'APPROVED', 'PROMOTED', 'OPEN', 'COMPLETED', 'ACTIVE'].includes(text)) return 'good';
  if (['PENDING', 'PARTIAL', 'HOLD', 'EXPIRED', 'AMBIGUOUS', 'NEEDS_MORE_SAMPLES', 'FLAT', 'STALE', 'PENDING_REVIEW', 'SKIP', 'QUEUED', 'QUEUE', 'PROCESSING', 'SUBMITTED', 'CLOSE_REQUESTED'].includes(text)) return 'warn';
  if (['ERROR', 'LOSS', 'MISSED_MOVE', 'WEAK', 'NOT_TRADABLE', 'SHORT', 'DOWN', 'NOT_READY', 'FAILED', 'REJECTED', 'VALIDATION_FAILED', 'CLOSE_FAILED'].includes(text)) return 'bad';
  return 'info';
}

function chip(value, extra = '') {
  return `<span class="chip ${statusClass(value)} ${extra}">${escapeHtml(value ?? 'n/a')}</span>`;
}

function kpi(label, value, sub = '') {
  return `<article class="kpi"><div class="kpi-label">${escapeHtml(label)}</div><div class="kpi-value">${escapeHtml(value ?? 'n/a')}</div>${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function setTextIfChanged(element, text) {
  if (!element) return;
  if (element.textContent !== text) {
    element.textContent = text;
  }
}

function setTitleIfChanged(element, text) {
  if (!element) return;
  if (element.title !== text) {
    element.title = text;
  }
}

function setHtmlIfChanged(element, html) {
  if (!element) return;
  if (element.innerHTML !== html) {
    element.innerHTML = html;
  }
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 3400);
}

function showLoader(text = 'Loading dashboard...') {
  const loaderTextEl = $('loaderText');
  const loaderEl = $('loader');
  if (loaderTextEl) loaderTextEl.textContent = text;
  if (loaderEl) loaderEl.classList.remove('hidden');
}

function hideLoader() {
  const loaderEl = $('loader');
  if (loaderEl) loaderEl.classList.add('hidden');
}

function setBusy(isBusy, label = 'Working') {
  $('predict').disabled = isBusy;
  $('controlBadge').className = `chip ${isBusy ? 'warn' : 'info'}`;
  $('controlBadge').textContent = isBusy ? label : 'Ready';
}

function setTab(name) {
  activeTab = name;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tabPanel').forEach(p => p.classList.toggle('hidden', p.id !== name));
  renderActiveTabContent();
}

function isSignalsFilterInteracting() {
  const active = document.activeElement;
  return !!(active && SIGNAL_FILTER_CONTROL_IDS.has(active.id));
}

function isTradeExecutionFilterInteracting() {
  const active = document.activeElement;
  return !!(active && TRADE_FILTER_CONTROL_IDS.has(active.id));
}

function buildSignalPaginationButtons(currentPage, totalPages) {
  const page = Math.max(1, Number(currentPage || 1));
  const total = Math.max(1, Number(totalPages || 1));
  const radius = 2;
  let start = Math.max(1, page - radius);
  let end = Math.min(total, page + radius);

  if (end - start < radius * 2) {
    start = Math.max(1, end - (radius * 2));
    end = Math.min(total, start + (radius * 2));
  }

  const pieces = [];
  const pageButton = (p, active = false) => `<button type="button" class="${active ? 'btn-primary' : 'btn-alt'}" data-signal-page="${p}" style="min-height: 34px; padding: 6px 10px;">${p}</button>`;

  if (start > 1) {
    pieces.push(pageButton(1, page === 1));
    if (start > 2) pieces.push('<span class="muted">...</span>');
  }

  for (let p = start; p <= end; p += 1) {
    pieces.push(pageButton(p, p === page));
  }

  if (end < total) {
    if (end < total - 1) pieces.push('<span class="muted">...</span>');
    pieces.push(pageButton(total, page === total));
  }

  return pieces.join('');
}

function buildTradePaginationButtons(currentPage, totalPages) {
  const page = Math.max(1, Number(currentPage || 1));
  const total = Math.max(1, Number(totalPages || 1));
  const radius = 2;
  let start = Math.max(1, page - radius);
  let end = Math.min(total, page + radius);

  if (end - start < radius * 2) {
    start = Math.max(1, end - (radius * 2));
    end = Math.min(total, start + (radius * 2));
  }

  const pieces = [];
  const pageButton = (p, active = false) => `<button type="button" class="${active ? 'btn-primary' : 'btn-alt'}" data-trade-page="${p}" style="min-height: 34px; padding: 6px 10px;">${p}</button>`;

  if (start > 1) {
    pieces.push(pageButton(1, page === 1));
    if (start > 2) pieces.push('<span class="muted">...</span>');
  }

  for (let p = start; p <= end; p += 1) {
    pieces.push(pageButton(p, p === page));
  }

  if (end < total) {
    if (end < total - 1) pieces.push('<span class="muted">...</span>');
    pieces.push(pageButton(total, page === total));
  }

  return pieces.join('');
}

function resizeCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(320, rect.width);
  const cssHeight = Number.parseFloat(getComputedStyle(canvas).height) || 360;
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: cssWidth, h: cssHeight };
}

function drawEmptyChart(ctx, w, h, text) {
  ctx.fillStyle = '#90a9bc';
  ctx.font = '14px Space Grotesk';
  ctx.textAlign = 'center';
  ctx.fillText(text, w / 2, h / 2);
  ctx.textAlign = 'left';
}

function buildCloseSeries() {
  const inputTail = (latest.input_tail || []).slice(-120);
  const marketTail = (latest.market_tail || []).slice(-120);
  const history = inputTail.length ? inputTail : marketTail;
  const forecast = (latest.forecast || []).slice();
  const actual = (latest.actual_tail || []).slice();
  const forecastStart = parseTs(forecast[0]?.timestamps);
  const forecastEnd = parseTs(forecast[forecast.length - 1]?.timestamps);
  const actualWindow = (forecastStart && forecastEnd)
    ? actual.filter(row => {
      const t = parseTs(row.timestamps || row.timestamp_utc);
      return t && t >= forecastStart && t <= forecastEnd;
    })
    : [];
  return { history, forecast, actualWindow, forecastStart };
}

function drawCloseChart() {
  const canvas = $('closeChart');
  if (!canvas) return;
  const { ctx, w, h } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const { history, forecast, actualWindow, forecastStart } = buildCloseSeries();
  const allRows = [...history, ...forecast, ...actualWindow];
  if (!allRows.length) {
    drawEmptyChart(ctx, w, h, 'No close-price data available');
    return;
  }

  const allTimes = allRows.map(r => parseTs(r.timestamps || r.timestamp_utc)?.getTime()).filter(Boolean);
  const allPrices = allRows.map(r => Number(r.close)).filter(v => Number.isFinite(v));
  if (!allTimes.length || !allPrices.length) {
    drawEmptyChart(ctx, w, h, 'Unable to draw chart from current data');
    return;
  }

  const pad = 46;
  const minTs = Math.min(...allTimes);
  const maxTs = Math.max(...allTimes);
  const spanTs = Math.max(maxTs - minTs, 1);
  const minPriceRaw = Math.min(...allPrices);
  const maxPriceRaw = Math.max(...allPrices);
  const pricePad = Math.max((maxPriceRaw - minPriceRaw) * 0.08, 0.2);
  const minPrice = minPriceRaw - pricePad;
  const maxPrice = maxPriceRaw + pricePad;

  const x = t => pad + ((t - minTs) / spanTs) * (w - pad * 2);
  const y = v => h - pad - ((v - minPrice) / Math.max(maxPrice - minPrice, 1e-9)) * (h - pad * 2);

  ctx.strokeStyle = 'rgba(126,167,199,0.2)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const gy = pad + i * ((h - pad * 2) / 4);
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(w - pad, gy);
    ctx.stroke();
  }

  ctx.fillStyle = '#90a9bc';
  ctx.font = '12px IBM Plex Sans';
  ctx.fillText(fmtNumber(maxPrice, 2), 8, pad + 4);
  ctx.fillText(fmtNumber(minPrice, 2), 8, h - pad + 4);

  const drawSeries = (rows, color, width, dashed = false) => {
    const points = rows.map(row => {
      const t = parseTs(row.timestamps || row.timestamp_utc);
      return t ? { x: x(t.getTime()), y: y(Number(row.close)) } : null;
    }).filter(Boolean);
    if (points.length < 2) return;
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    if (dashed) ctx.setLineDash([6, 5]);
    points.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
    ctx.stroke();
    ctx.setLineDash([]);
  };

  drawSeries(history, '#57a4ff', 2.4);
  drawSeries(actualWindow, '#4ee38d', 2.1, true);
  drawSeries(forecast, '#f6b35b', 2.8);

  if (forecastStart) {
    const vx = x(forecastStart.getTime());
    ctx.strokeStyle = '#f6b35b';
    ctx.setLineDash([7, 6]);
    ctx.beginPath();
    ctx.moveTo(vx, pad);
    ctx.lineTo(vx, h - pad);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.fillStyle = '#dce9f8';
  ctx.font = '12px IBM Plex Sans';
  ctx.fillText('Input history', pad, 22);
  ctx.fillStyle = '#f6b35b';
  ctx.fillText('Forecast', pad + 94, 22);
  ctx.fillStyle = '#4ee38d';
  ctx.fillText('Actual in forecast window', pad + 160, 22);
}

function drawCandleChart() {
  const canvas = $('candleChart');
  if (!canvas) return;
  const { ctx, w, h } = resizeCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const inputTail = (latest.input_tail || []).slice(-72);
  const marketTail = (latest.market_tail || []).slice(-72);
  const history = inputTail.length ? inputTail : marketTail;
  const forecast = (latest.forecast || []).slice(-24);
  const rows = [...history.map(r => ({ ...r, kind: 'history' })), ...forecast.map(r => ({ ...r, kind: 'forecast' }))];

  if (!rows.length) {
    drawEmptyChart(ctx, w, h, 'No candlestick data available');
    return;
  }

  const priceValues = [];
  rows.forEach(r => {
    ['open', 'high', 'low', 'close'].forEach(k => {
      const val = Number(r[k]);
      if (Number.isFinite(val)) priceValues.push(val);
    });
  });
  if (!priceValues.length) {
    drawEmptyChart(ctx, w, h, 'No valid OHLC values available');
    return;
  }

  const pad = 46;
  const minPriceRaw = Math.min(...priceValues);
  const maxPriceRaw = Math.max(...priceValues);
  const pPad = Math.max((maxPriceRaw - minPriceRaw) * 0.08, 0.2);
  const minPrice = minPriceRaw - pPad;
  const maxPrice = maxPriceRaw + pPad;
  const y = v => h - pad - ((v - minPrice) / Math.max(maxPrice - minPrice, 1e-9)) * (h - pad * 2);

  ctx.strokeStyle = 'rgba(126,167,199,0.2)';
  for (let i = 0; i <= 4; i++) {
    const gy = pad + i * ((h - pad * 2) / 4);
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(w - pad, gy);
    ctx.stroke();
  }

  const step = (w - pad * 2) / Math.max(rows.length, 1);
  rows.forEach((r, i) => {
    const cx = pad + i * step + step / 2;
    const o = Number(r.open);
    const c = Number(r.close);
    const hi = Number(r.high);
    const lo = Number(r.low);
    if (![o, c, hi, lo].every(Number.isFinite)) return;
    const up = c >= o;
    const color = r.kind === 'forecast' ? (up ? '#f6b35b' : '#ff8a8a') : (up ? '#4ee38d' : '#57a4ff');
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, y(hi));
    ctx.lineTo(cx, y(lo));
    ctx.stroke();
    const top = Math.min(y(o), y(c));
    const body = Math.max(Math.abs(y(o) - y(c)), 2);
    ctx.fillRect(cx - Math.max(step * 0.25, 2), top, Math.max(step * 0.5, 3), body);
  });

  if (forecast.length) {
    const splitX = pad + history.length * step;
    ctx.strokeStyle = '#f6b35b';
    ctx.setLineDash([7, 6]);
    ctx.beginPath();
    ctx.moveTo(splitX, pad);
    ctx.lineTo(splitX, h - pad);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.fillStyle = '#dce9f8';
  ctx.font = '12px IBM Plex Sans';
  ctx.fillText('Input candles', pad, 22);
  ctx.fillStyle = '#f6b35b';
  ctx.fillText('Forecast candles', pad + 92, 22);
}

function renderHeartbeat(pg) {
  const workers = pg.worker_statuses || {};
  const keys = Object.keys(workers);
  if (!keys.length) return 'No workers yet';
  return keys
    .sort()
    .map(name => `${escapeHtml(name)} ${chip(workers[name]?.status || 'MISSING')}`)
    .join('<br>');
}

function modelStat(label, value) {
  return `<div class="model-stat"><div class="model-stat-label">${escapeHtml(label)}</div><div class="model-stat-value">${escapeHtml(value ?? 'n/a')}</div></div>`;
}

function renderModelStatus(autoStatus = {}, metadata = {}) {
  const rows = Number(autoStatus.dataset_rows || 0);
  const requiredRows = Number(autoStatus.required_dataset_rows || autoStatus.min_rows || 0);
  const sourceCounts = autoStatus.dataset_source_counts || {};
  const websocketRows = Number(autoStatus.websocket_rows ?? sourceCounts.websocket_ohlc ?? 0);
  const historicalRows = Number(autoStatus.historical_rows ?? Math.max(0, rows - websocketRows));
  const rawPct = Number(autoStatus.promotion_progress_pct);
  const progressPct = Number.isFinite(rawPct)
    ? Math.max(0, Math.min(100, rawPct))
    : (requiredRows > 0 ? Math.max(0, Math.min(100, (rows / requiredRows) * 100)) : 0);
  const rowsRemaining = Math.max(0, requiredRows - rows);
  const modelLabel = autoStatus.current_model_label || metadata.model_name || 'Kronos-base';
  const modelVersion = autoStatus.current_model_version || modelLabel;
  const candidateVersion = autoStatus.candidate_model_version || autoStatus.active_model_path || 'No candidate model';
  const promotionStatus = autoStatus.promotion_status || 'not_ready';
  const action = autoStatus.action || 'idle';
  const interval = Number(autoStatus.auto_finetune_interval_minutes || 5);
  const latestDatasetTs = autoStatus.latest_dataset_timestamp_utc || autoStatus.latest_websocket_timestamp_utc;
  const rowTarget = requiredRows > 0 ? `${fmtCount(rows)} / ${fmtCount(requiredRows)}` : fmtCount(rows);

  const html = `
    <div class="panel-head">
      <div>
        <h2>Model Version</h2>
        <p>Running ${escapeHtml(modelVersion)} for ${escapeHtml(autoStatus.symbol || metadata.epic || 'ETHUSD')} ${escapeHtml(autoStatus.resolution || metadata.resolution || 'MINUTE_5')}</p>
      </div>
      <div class="status-strip">${chip(promotionStatus)}${chip(action)}</div>
    </div>
    <div class="model-status-grid">
      <div>
        <div class="model-version-title">${escapeHtml(modelLabel)}</div>
        <div class="model-progress-sub">Candidate: ${escapeHtml(candidateVersion)}</div>
      </div>
      <div class="model-progress-area">
        <div class="progress-row"><span>Next promotion</span><strong>${fmtNumber(progressPct, 2)}%</strong></div>
        <div class="progress-track" aria-label="Next model promotion progress">
          <div class="progress-fill" style="width: ${progressPct}%;"></div>
        </div>
        <div class="model-progress-sub">${rowTarget} five-minute rows loaded, ${fmtCount(rowsRemaining)} remaining. Split: ${fmtCount(websocketRows)} websocket + ${fmtCount(historicalRows)} historical/current.</div>
      </div>
    </div>
    <div class="model-metrics">
      ${modelStat('Interval', `${Number.isFinite(interval) ? interval : 5} min`)}
      ${modelStat('Latest 5m Row', fmtDate(latestDatasetTs))}
      ${modelStat('Latest Websocket Row', fmtDate(autoStatus.latest_websocket_timestamp_utc))}
      ${modelStat('Last Check', fmtDate(autoStatus.last_checked_utc))}
    </div>`;

  const key = [
    modelVersion,
    candidateVersion,
    promotionStatus,
    action,
    rows,
    requiredRows,
    websocketRows,
    historicalRows,
    progressPct,
    latestDatasetTs || '',
    autoStatus.latest_websocket_timestamp_utc || '',
    autoStatus.last_checked_utc || '',
    interval,
  ].join('|');
  if (key !== lastModelStatusKey) {
    setHtmlIfChanged($('modelStatusPanel'), html);
    lastModelStatusKey = key;
  }
}

function currentStatusQuery() {
  const params = new URLSearchParams();
  params.set('symbol', $('market').value || 'ETHUSD');
  params.set('resolution', $('resolution').value || 'MINUTE');
  return params.toString();
}

function actionContextPayload(extra = {}) {
  return {
    run_id: selectedRunId || '',
    symbol: $('market').value || 'ETHUSD',
    resolution: $('resolution').value || 'MINUTE_5',
    ...extra,
  };
}

function getSignalQuery(page = 1) {
  const params = new URLSearchParams();
  params.set('symbol', $('market').value || 'ETHUSD');
  if (signalFilters.timeframe) params.set('timeframe', signalFilters.timeframe);
  if (signalFilters.direction) params.set('direction', signalFilters.direction);
  if (signalFilters.status) params.set('status', signalFilters.status);
  if (signalFilters.signalId) params.set('signal_id', signalFilters.signalId);
  if (signalFilters.dateFrom) params.set('date_from', signalFilters.dateFrom);
  if (signalFilters.dateTo) params.set('date_to', signalFilters.dateTo);
  params.set('page', String(page));
  params.set('page_size', String(signalPageSize));
  return params.toString();
}

function readSignalFiltersFromUi() {
  const timeframeEl = $('signalsTimeframe');
  const dateFromEl = $('signalsDateFrom');
  const dateToEl = $('signalsDateTo');
  const directionEl = $('signalsDirection');
  const statusEl = $('signalsStatus');
  const signalIdEl = $('signalsSignalId');
  if (!timeframeEl) return;
  signalFilters = {
    timeframe: timeframeEl.value || '',
    dateFrom: dateFromEl.value || '',
    dateTo: dateToEl.value || '',
    direction: directionEl.value || '',
    status: statusEl.value || '',
    signalId: signalIdEl.value || '',
  };
}

async function refreshSignals(page = 1, options = {}) {
  const { renderUi = true, forceRender = false } = options;
  try {
    const res = await fetch(`/api/signals?${getSignalQuery(page)}`, { cache: 'no-store' });
    latestSignals = await res.json();
    if (!res.ok) throw new Error(latestSignals.error?.message || `Signals HTTP ${res.status}`);
    signalPage = latestSignals.pagination?.page || page;
    if (renderUi && (forceRender || !isSignalsFilterInteracting())) {
      renderOverview({ force: forceRender, background: false });
    }
  } catch (err) {
    showToast(`Signals refresh failed: ${err.message}`);
  }
}

function renderOverview(options = {}) {
  const { force = false, background = false } = options;
  const pg = latest.postgres_snapshot || {};
  const warnings = latest.status_warnings || [];
  const workerStates = pg.worker_statuses || {};
  const outcomes = (pg.outcomes || []).map(r => `${escapeHtml(r.status)}: ${escapeHtml(r.count)}`).join(' | ') || 'No outcomes yet';
  const rows = latestSignals.rows || [];
  const pag = latestSignals.pagination || { page: 1, total: 0, total_pages: 1, has_prev: false, has_next: false };
  const pageButtons = buildSignalPaginationButtons(pag.page || 1, pag.total_pages || 1);
  const workerCards = Object.entries(workerStates)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, state]) => `<article class="worker-item"><div class="worker-name">${escapeHtml(name)}</div><div>${chip(state?.status || 'MISSING')}</div><div class="tiny-help">${state?.updated_at ? `Updated ${escapeHtml(fmtDate(state.updated_at))}` : 'No heartbeat yet'}</div></article>`)
    .join('');

  const badgeOrMuted = value => {
    const text = String(value || '').trim();
    return text ? chip(text) : '<span class="muted">n/a</span>';
  };

  const parseValidationSummary = value => {
    if (!value) return {};
    if (typeof value === 'object') return value;
    try {
      const parsed = JSON.parse(String(value));
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  };

  const bodyRows = rows.length
    ? rows.map(r => {
      const validatedCount = Number(r.outcomes_wins || 0) + Number(r.outcomes_losses || 0);
      const totalCount = validatedCount + Number(r.outcomes_pending || 0);
      const runBadge = badgeOrMuted(r.run_status || '');
      const activeDecision = badgeOrMuted(r.signal);
      const activeOutcome = badgeOrMuted(r.status);
      const activeStatus = badgeOrMuted(r.status_raw || r.status);
      const validationSummary = parseValidationSummary(r.validation_summary);
      const validationFinalSignal = String(validationSummary.final_signal || r.validation_status || '').trim();
      const validationBadge = badgeOrMuted(validationFinalSignal);
      const activeConfidence = pct01(r.confidence);
      const shadowDecision = badgeOrMuted(r.shadow_signal);
      const shadowOutcome = r.shadow_signal ? badgeOrMuted(r.shadow_status || 'PENDING') : '<span class="muted">n/a</span>';
      const shadowStatus = r.shadow_signal ? badgeOrMuted(r.shadow_status || 'PENDING') : '<span class="muted">n/a</span>';
      const shadowConfidence = r.shadow_signal ? pct01(r.shadow_confidence) : '<span class="muted">n/a</span>';
      const modelNoteParts = [];
      if (r.shadow_model_version_id || r.shadow_model_name) {
        modelNoteParts.push(String(r.shadow_model_version_id || r.shadow_model_name));
      }
      if (r.disagreement) {
        modelNoteParts.push('disagreement');
      }
      if (validationFinalSignal) {
        if (validationSummary.blocked) {
          modelNoteParts.push(`validation ${validationFinalSignal} (${validationSummary.block_reason || 'UNKNOWN'})`);
        } else {
          modelNoteParts.push(`validation ${validationFinalSignal}`);
        }
      }
      const modelNoteRow = modelNoteParts.length
        ? `<tr class="signal-note-row"><td colspan="15"><div class="signal-note">Model Note: ${escapeHtml(modelNoteParts.join(' | '))}</div></td></tr>`
        : '';
      return `<tr class="signal-group-row signal-group-start">
        <td rowspan="2">
          <div class="signal-id-line">${escapeHtml(r.signal_id || '')}</div>
          <div class="tiny-help">Run ID: ${escapeHtml(r.run_id || '')}</div>
        </td>
        <td rowspan="2">${fmtDate(r.timestamp_utc)}</td>
        <td rowspan="2">${escapeHtml(r.resolution || '')}</td>
        <td><span class="signal-variant-label">ACTIVE</span></td>
        <td class="signal-badge-cell">${activeDecision}</td>
        <td class="signal-badge-cell">${activeOutcome}</td>
        <td class="signal-badge-cell">${activeStatus}</td>
        <td rowspan="2" class="signal-badge-cell">${validationBadge}</td>
        <td class="signal-badge-cell">${runBadge}</td>
        <td rowspan="2" class="signal-numeric">${escapeHtml(String(validatedCount))}/${escapeHtml(String(totalCount))}</td>
        <td class="signal-numeric">${fmtNumber(r.entry_price)}</td>
        <td class="signal-numeric">${fmtNumber(r.tp_price)}</td>
        <td class="signal-numeric">${fmtNumber(r.sl_price)}</td>
        <td class="signal-numeric">${activeConfidence}</td>
        <td rowspan="2">
          <div class="signal-actions">
            <button class="mini-copy" data-copy="${escapeHtml(r.signal_id || '')}" data-copy-label="signal id">Copy Signal</button>
            <button class="mini-copy" data-copy="${escapeHtml(r.run_id || '')}" data-copy-label="run id">Copy Run</button>
            <button class="mini-copy" data-execute-signal="${escapeHtml(r.signal_id || r.run_id || '')}">Execute Signal</button>
            <button class="mini-copy" data-audit-run="${escapeHtml(r.run_id || '')}">Audit</button>
          </div>
        </td>
      </tr>
      <tr class="signal-group-row">
        <td><span class="signal-variant-label">SHADOW</span></td>
        <td class="signal-badge-cell">${shadowDecision}</td>
        <td class="signal-badge-cell">${shadowOutcome}</td>
        <td class="signal-badge-cell">${shadowStatus}</td>
        <td class="signal-badge-cell">${runBadge}</td>
        <td class="signal-numeric">${fmtNumber(r.shadow_entry_price)}</td>
        <td class="signal-numeric">${fmtNumber(r.shadow_tp_price)}</td>
        <td class="signal-numeric">${fmtNumber(r.shadow_sl_price)}</td>
        <td class="signal-numeric">${shadowConfidence}</td>
      </tr>
      ${modelNoteRow}`;
    }).join('')
    : '<tr><td colspan="15"><div class="empty">No signals found for current filters.</div></td></tr>';

  const warningHtml = warnings.length
    ? `<div class="warning-stack">${warnings.map(w => `<div class="warning-item">${escapeHtml(w)}</div>`).join('')}</div>`
    : '';

  const overviewHtml = `
    <div class="panel-head">
      <div>
        <h2>Signals Table</h2>
        <p>Filter old and new signals by timeframe, date, direction, status, and signal id.</p>
      </div>
      <span class="chip info">${escapeHtml(String(pag.total || 0))} records</span>
    </div>

    ${warningHtml}

    <div class="worker-grid">${workerCards || '<div class="empty">Worker states unavailable.</div>'}</div>

    <div class="control-grid" style="grid-template-columns: repeat(6, minmax(0, 1fr)); margin-bottom: 10px;">
      <label class="field">Timeframe
        <select id="signalsTimeframe">
          <option value="" ${signalFilters.timeframe === '' ? 'selected' : ''}>All</option>
          <option value="MINUTE" ${signalFilters.timeframe === 'MINUTE' ? 'selected' : ''}>MINUTE</option>
          <option value="MINUTE_5" ${signalFilters.timeframe === 'MINUTE_5' ? 'selected' : ''}>MINUTE_5</option>
          <option value="MINUTE_15" ${signalFilters.timeframe === 'MINUTE_15' ? 'selected' : ''}>MINUTE_15</option>
          <option value="MINUTE_30" ${signalFilters.timeframe === 'MINUTE_30' ? 'selected' : ''}>MINUTE_30</option>
          <option value="HOUR" ${signalFilters.timeframe === 'HOUR' ? 'selected' : ''}>HOUR</option>
        </select>
      </label>
      <label class="field">Date From (Asia/Amman)
        <input id="signalsDateFrom" type="date" value="${escapeHtml(signalFilters.dateFrom)}" title="Dates are interpreted in Asia/Amman timezone.">
      </label>
      <label class="field">Date To (Asia/Amman)
        <input id="signalsDateTo" type="date" value="${escapeHtml(signalFilters.dateTo)}" title="Dates are interpreted in Asia/Amman timezone.">
      </label>
      <label class="field">Direction
        <select id="signalsDirection">
          <option value="" ${signalFilters.direction === '' ? 'selected' : ''}>All</option>
          <option value="UP" ${signalFilters.direction === 'UP' ? 'selected' : ''}>UP</option>
          <option value="DOWN" ${signalFilters.direction === 'DOWN' ? 'selected' : ''}>DOWN</option>
          <option value="FLAT" ${signalFilters.direction === 'FLAT' ? 'selected' : ''}>FLAT</option>
        </select>
      </label>
      <label class="field">Status
        <select id="signalsStatus">
          <option value="" ${signalFilters.status === '' ? 'selected' : ''}>All</option>
          <option value="PENDING" ${signalFilters.status === 'PENDING' ? 'selected' : ''}>PENDING</option>
          <option value="PARTIAL" ${signalFilters.status === 'PARTIAL' ? 'selected' : ''}>PARTIAL (run)</option>
          <option value="VALIDATED" ${signalFilters.status === 'VALIDATED' ? 'selected' : ''}>VALIDATED (run)</option>
          <option value="WIN" ${signalFilters.status === 'WIN' ? 'selected' : ''}>WIN</option>
          <option value="LOSS" ${signalFilters.status === 'LOSS' ? 'selected' : ''}>LOSS</option>
          <option value="EXPIRED" ${signalFilters.status === 'EXPIRED' ? 'selected' : ''}>EXPIRED</option>
          <option value="GOOD_HOLD" ${signalFilters.status === 'GOOD_HOLD' ? 'selected' : ''}>GOOD_HOLD</option>
          <option value="MISSED_MOVE" ${signalFilters.status === 'MISSED_MOVE' ? 'selected' : ''}>MISSED_MOVE</option>
          <option value="AMBIGUOUS" ${signalFilters.status === 'AMBIGUOUS' ? 'selected' : ''}>AMBIGUOUS</option>
        </select>
      </label>
      <label class="field">Signal ID <input id="signalsSignalId" value="${escapeHtml(signalFilters.signalId)}" autocomplete="off"></label>
    </div>

    <div class="tiny-help">Press Esc to reset all signal filters instantly.</div>

    <div class="actions" style="grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 10px;">
      <button id="signalsApply" class="btn-alt">Apply Filters</button>
      <button id="signalsReset" class="btn-warn">Reset Filters</button>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Signal ID / Run ID</th><th>Generated</th><th>Timeframe</th><th>Variant</th><th>Decision</th><th>Outcome</th><th>Status</th><th>Validation</th><th>Run</th><th class="signal-numeric">Validated / Total</th><th class="signal-numeric">Entry</th><th class="signal-numeric">TP</th><th class="signal-numeric">SL</th><th class="signal-numeric">Confidence</th><th>Actions</th></tr>
        </thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>

    <div class="signal-table-footer">
      <div class="signal-pagination-left">
        <button id="signalsFirst" class="btn-alt" style="min-height: 34px; padding: 6px 10px;" ${pag.has_prev ? '' : 'disabled'}>First</button>
        <button id="signalsPrev" class="btn-alt" style="min-height: 34px; padding: 6px 10px;" ${pag.has_prev ? '' : 'disabled'}>Prev</button>
        <div class="signal-pagination-pages">${pageButtons}</div>
        <button id="signalsNext" class="btn-alt" style="min-height: 34px; padding: 6px 10px;" ${pag.has_next ? '' : 'disabled'}>Next</button>
        <button id="signalsLast" class="btn-alt" style="min-height: 34px; padding: 6px 10px;" ${pag.has_next ? '' : 'disabled'}>Last</button>
      </div>
      <div class="signal-pagination-right">
        <label class="field signal-page-size-field">Rows / Page
          <select id="signalsPageSize">
            <option value="10" ${signalPageSize === 10 ? 'selected' : ''}>10</option>
            <option value="20" ${signalPageSize === 20 ? 'selected' : ''}>20</option>
            <option value="50" ${signalPageSize === 50 ? 'selected' : ''}>50</option>
            <option value="100" ${signalPageSize === 100 ? 'selected' : ''}>100</option>
          </select>
        </label>
        <div class="tiny-help">Page ${escapeHtml(String(pag.page || 1))} / ${escapeHtml(String(pag.total_pages || 1))}</div>
        <div class="tiny-help">${escapeHtml(String(pag.total || 0))} total rows</div>
        <div class="tiny-help">Outcome mix: ${escapeHtml(outcomes)}</div>
      </div>
    </div>`;

  if (!force && background) {
    const now = Date.now();
    if (now - lastOverviewRenderAtMs < OVERVIEW_BACKGROUND_RENDER_INTERVAL_MS) {
      return;
    }
  }

  if (!force && overviewHtml === lastOverviewHtml) {
    return;
  }

  $('overview').innerHTML = overviewHtml;
  lastOverviewHtml = overviewHtml;
  lastOverviewRenderAtMs = Date.now();
}

function renderValidation(data) {
  const v = data.validation || {};
  const source = data.validation_source || 'none';
  const sv = data.signal_validation || {};
  const tf = data.timeframe_validations || [];
  const componentScores = sv.component_scores || {};
  const reasonCodes = sv.reason_codes || [];
  const reasonDetails = sv.reason_details || [];
  const matchedCandles = Number(v.matched_candles || 0);
  const blockedSignal = Boolean(sv.blocked);
  const metricsUnavailable = source === 'none' || (source === 'prediction_outcomes' && matchedCandles === 0);
  const metricPendingLabel = source === 'none'
    ? 'n/a (validation source unavailable)'
    : 'n/a (waiting for WIN/LOSS outcomes)';
  const metricsStatusNote = metricsUnavailable
    ? 'MAE/RMSE/MAPE/Expected move require matched WIN/LOSS outcomes.'
    : 'MAE/RMSE/MAPE/Expected move are based on matched WIN/LOSS outcomes.';
  const scoreStatusNote = blockedSignal
    ? `All component scores are 0.00 because this run is BLOCKED (${sv.block_reason || 'no block reason provided'}).`
    : 'Component scores reflect the latest external scoring pass.';
  const validationHealth = blockedSignal
    ? {
      tone: 'bad',
      title: 'Validation blocked',
      detail: `Scoring is blocked by ${sv.block_reason || 'one or more hard blockers'}.`,
    }
    : metricsUnavailable
      ? {
        tone: 'warn',
        title: 'Awaiting matched outcomes',
        detail: 'MAE/RMSE/MAPE/Expected move will populate after WIN/LOSS outcomes are recorded.',
      }
      : matchedCandles < 20
        ? {
          tone: 'warn',
          title: 'Metrics available with low sample size',
          detail: `Using ${matchedCandles} matched candles; treat direction accuracy as preliminary.`,
        }
        : {
          tone: 'good',
          title: 'Validation healthy',
          detail: `Using ${matchedCandles} matched candles from ${source}.`,
        };
  const validationBannerHtml = `<div class="validation-banner ${validationHealth.tone}">
      <div class="validation-banner-title">${escapeHtml(validationHealth.title)}</div>
      <div class="validation-banner-text">${escapeHtml(validationHealth.detail)}</div>
    </div>`;
  const accuracyHint = matchedCandles < 20
    ? `Low sample size (${matchedCandles}) - direction accuracy is noisy.`
    : `Sample size ${matchedCandles} - direction accuracy is more reliable.`;
  const qualityRows = [
    ['Source', source],
    ['Quality', v.quality_status],
    ['Direction', v.forecast_direction || sv.forecast_direction || 'n/a'],
    ['Matched candles', v.matched_candles],
    ['Direction accuracy', v.direction_accuracy_pct === undefined || v.direction_accuracy_pct === null ? metricPendingLabel : `${fmtNumber(v.direction_accuracy_pct, 2)}%`],
    ['Direction accuracy hint', accuracyHint],
    ['Metrics status', metricsStatusNote],
    ['MAE', v.mae === undefined || v.mae === null ? metricPendingLabel : fmtNumber(v.mae)],
    ['RMSE', v.rmse === undefined || v.rmse === null ? metricPendingLabel : fmtNumber(v.rmse)],
    ['MAPE', v.mape_pct === undefined || v.mape_pct === null ? metricPendingLabel : `${fmtNumber(v.mape_pct, 3)}%`],
    ['Expected move', v.max_abs_close_move_pct === undefined || v.max_abs_close_move_pct === null ? metricPendingLabel : `${fmtNumber(v.max_abs_close_move_pct, 3)}%`],
  ];

  const scoreRows = [
    ['Candidate signal', sv.candidate_signal || 'n/a'],
    ['Final signal', sv.final_signal || 'n/a'],
    ['Confidence level', sv.confidence_level || 'n/a'],
    ['Total score', sv.total_score === undefined || sv.total_score === null ? 'n/a' : fmtNumber(sv.total_score, 2)],
    ['Blocked', sv.blocked ? 'Yes' : 'No'],
    ['Block reason', sv.block_reason || 'n/a'],
    ['Net edge %', sv.net_edge_pct === undefined || sv.net_edge_pct === null ? 'n/a' : `${fmtNumber(sv.net_edge_pct, 4)}%`],
    ['Estimated cost %', sv.estimated_cost_pct === undefined || sv.estimated_cost_pct === null ? 'n/a' : `${fmtNumber(sv.estimated_cost_pct, 4)}%`],
  ];

  const componentRows = [
    ['Kronos forecast quality', fmtNumber(componentScores.kronos_forecast, 2)],
    ['Higher-timeframe alignment', fmtNumber(componentScores.higher_timeframe_alignment, 2)],
    ['Momentum confirmation', fmtNumber(componentScores.momentum, 2)],
    ['Volume confirmation', fmtNumber(componentScores.volume, 2)],
    ['Cost/liquidity quality', fmtNumber(componentScores.cost_liquidity, 2)],
    ['Volatility regime', fmtNumber(componentScores.volatility, 2)],
    ['Support/resistance location', fmtNumber(componentScores.support_resistance, 2)],
  ];

  const scoreStatusHtml = `<div class="tiny-help" style="margin: 8px 0 6px;">${escapeHtml(scoreStatusNote)}</div>`;

  const timeframeRows = tf.length
    ? tf.map(row => {
      const snap = row.indicator_snapshot || {};
      return `<tr>
        <td>${escapeHtml(row.timeframe || '')}</td>
        <td>${chip(row.trend || 'NEUTRAL')}</td>
        <td>${row.confirms_candidate ? 'Yes' : 'No'}</td>
        <td>${escapeHtml(row.alignment_state || 'n/a')}</td>
        <td>${fmtNumber(row.total_timeframe_score, 2)}</td>
        <td>${fmtNumber(snap.rsi14, 2)}</td>
        <td>${fmtNumber(snap.macd_hist, 4)}</td>
        <td>${fmtNumber(snap.ema20, 2)}</td>
        <td>${fmtNumber(snap.ema50, 2)}</td>
        <td>${fmtNumber(snap.atr14, 4)}</td>
        <td>${fmtNumber(snap.volume_zscore, 2)}</td>
        <td>${snap.distance_to_support_pct === undefined || snap.distance_to_support_pct === null ? 'n/a' : `${fmtNumber(snap.distance_to_support_pct, 2)}%`}</td>
        <td>${snap.distance_to_resistance_pct === undefined || snap.distance_to_resistance_pct === null ? 'n/a' : `${fmtNumber(snap.distance_to_resistance_pct, 2)}%`}</td>
      </tr>`;
    }).join('')
    : '<tr><td colspan="13">No higher-timeframe validation rows available.</td></tr>';

  const reasonHtml = (reasonDetails.length || reasonCodes.length)
    ? `<div class="warning-stack">
        ${reasonCodes.map(code => `<div class="warning-item">Reason code: ${escapeHtml(code)}</div>`).join('')}
        ${reasonDetails.map(item => `<div class="warning-item">${escapeHtml(item)}</div>`).join('')}
      </div>`
    : '<div class="tiny-help">No validation reasons attached for this run.</div>';

  $('validation').innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Validation Summary</h2>
        <p>Forecast quality plus external higher-timeframe validation and signal scoring.</p>
      </div>
      ${chip(sv.final_signal || v.quality_status || 'PENDING')}
    </div>

    ${validationBannerHtml}

    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${qualityRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">External Signal Validation</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${scoreRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Score Breakdown</h3>
    ${scoreStatusHtml}
    <div class="table-wrap"><table><thead><tr><th>Component</th><th>Score</th></tr></thead><tbody>
      ${componentRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Higher-Timeframe Context</h3>
    <div class="table-wrap"><table><thead>
      <tr>
        <th>Timeframe</th><th>Trend</th><th>Confirms</th><th>State</th><th>Score</th>
        <th>RSI</th><th>MACD Hist</th><th>EMA20</th><th>EMA50</th>
        <th>ATR</th><th>Volume Z</th><th>Dist Support</th><th>Dist Resistance</th>
      </tr>
    </thead><tbody>
      ${timeframeRows}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Decision Reasons</h3>
    ${reasonHtml}

    <details style="margin-top: 10px;">
      <summary class="muted">Show raw validation payload</summary>
      <pre>${escapeHtml(JSON.stringify({
        forecast_quality: v,
        signal_validation: sv,
        timeframe_validations: tf,
      }, null, 2))}</pre>
    </details>`;
}

function renderRisk(data) {
  const hs = data.human_summary || {};
  const v = data.validation || {};
  const te = data.trade_execution || {};
  const queue = te.queue || {};

  $('risk').innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Trade-Level Summary</h2>
        <p>Entry, target, stop, confidence, and risk notes for the latest signal.</p>
      </div>
      ${chip(hs.signal_status || 'PENDING')}
    </div>

    <div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>
      <tr><td>Signal</td><td>${escapeHtml(hs.signal || 'n/a')}</td></tr>
      <tr><td>Entry Price</td><td>${fmtNumber(hs.entry_price)}</td></tr>
      <tr><td>Take Profit (TP)</td><td>${fmtNumber(hs.tp_price)}</td></tr>
      <tr><td>Stop Loss (SL)</td><td>${fmtNumber(hs.sl_price)}</td></tr>
      <tr><td>Confidence</td><td>${hs.confidence_pct === null || hs.confidence_pct === undefined ? 'n/a' : `${fmtNumber(hs.confidence_pct, 2)}%`}</td></tr>
      <tr><td>Expected Move</td><td>${v.max_abs_close_move_pct === undefined || v.max_abs_close_move_pct === null ? 'n/a' : `${fmtNumber(v.max_abs_close_move_pct, 3)}%`}</td></tr>
      <tr><td>Cost Warning</td><td>${v.movement_after_cost_warning ? 'Yes' : 'No'}</td></tr>
      <tr><td>Execution Queue</td><td>${escapeHtml(JSON.stringify(queue.counts || {}))}</td></tr>
      <tr><td>Broker Execution Health</td><td>${te.ok ? 'OK' : escapeHtml(te.error || 'Unavailable')}</td></tr>
    </tbody></table></div>`;
}

function readTradeExecutionFiltersFromUi() {
  tradeExecutionFilters = {
    lifecycle: String($('tradeLifecycleFilter')?.value || '').toUpperCase(),
    status: String($('tradeStatusFilter')?.value || '').toUpperCase(),
    outcome: String($('tradeOutcomeFilter')?.value || '').toUpperCase(),
    side: String($('tradeSideFilter')?.value || '').toUpperCase(),
    signalId: String($('tradeSignalFilter')?.value || '').trim(),
    transactionId: String($('tradeTransactionFilter')?.value || '').trim(),
  };
}

function tradeFilterOption(value, label, selectedValue) {
  const selected = String(selectedValue || '').toUpperCase() === String(value || '').toUpperCase() ? ' selected' : '';
  return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label || value || 'All')}</option>`;
}

function tradeFilterOptions(rows, key) {
  return [...new Set(rows.map(row => String(row[key] || '').toUpperCase()).filter(Boolean))].sort();
}

function normalizeTradeExecutionRows(active, pending, historical, queueEntries) {
  const tradeRow = (trade, lifecycle) => ({
    source: 'TRADE',
    lifecycle,
    record_id: trade.id,
    signal_id: trade.signal_id || '',
    created_at: trade.created_at || '',
    updated_at: trade.updated_at || '',
    status: String(trade.status || 'PENDING').toUpperCase(),
    signal_status: String(trade.signal_status || '').toUpperCase(),
    signal_label: trade.signal_label || '',
    validation_status: trade.validation_status || '',
    transaction_id: trade.transaction_id || '',
    transaction_lookup_status: trade.transaction_lookup_status || '',
    transaction_lookup_error: trade.transaction_lookup_error || '',
    trade_outcome: String(trade.trade_outcome || '').toUpperCase(),
    trade_outcome_reason: trade.trade_outcome_reason || '',
    trade_close_source: trade.trade_close_source || '',
    trade_close_level: trade.trade_close_level,
    trade_outcome_lookup_error: trade.trade_outcome_lookup_error || '',
    epic: trade.epic || '',
    direction: String(trade.direction || '').toUpperCase(),
    requested_size: trade.requested_size,
    executed_size: trade.executed_size,
    recommended_entry: trade.recommended_entry,
    actual_entry: trade.actual_entry,
    take_profit: trade.take_profit,
    stop_loss: trade.stop_loss,
    deal_reference: trade.deal_reference || '',
    deal_id: trade.deal_id || '',
    requested_by: '',
    attempt_count: '',
    next_attempt_at: '',
    failure_reason: trade.failure_reason || trade.broker_rejection_reason || '',
    error_details: trade.error_details || trade.broker_rejection_reason || '',
    sort_ms: parseTs(trade.updated_at || trade.created_at)?.getTime() || 0,
  });
  const queueRow = entry => ({
    source: 'QUEUE',
    lifecycle: 'QUEUE',
    record_id: entry.id,
    signal_id: entry.signal_id || '',
    created_at: entry.created_at || '',
    updated_at: entry.updated_at || '',
    status: String(entry.status || 'QUEUED').toUpperCase(),
    signal_status: String(entry.signal_status || '').toUpperCase(),
    signal_label: entry.signal_label || '',
    validation_status: entry.validation_status || '',
    epic: entry.epic || entry.symbol || '',
    direction: String(entry.direction || '').toUpperCase(),
    requested_size: entry.requested_size,
    executed_size: '',
    recommended_entry: entry.recommended_entry,
    actual_entry: '',
    take_profit: entry.take_profit,
    stop_loss: entry.stop_loss,
    deal_reference: '',
    deal_id: '',
    requested_by: entry.requested_by || '',
    attempt_count: entry.attempt_count ?? 0,
    next_attempt_at: entry.next_attempt_at || '',
    failure_reason: entry.failure_reason || '',
    error_details: entry.error_details || '',
    sort_ms: parseTs(entry.updated_at || entry.created_at || entry.next_attempt_at)?.getTime() || 0,
  });

  return [
    ...active.map(row => tradeRow(row, 'ACTIVE')),
    ...pending.map(row => tradeRow(row, 'PENDING')),
    ...queueEntries.map(queueRow),
    ...historical.map(row => tradeRow(row, 'HISTORICAL')),
  ].sort((a, b) => b.sort_ms - a.sort_ms);
}

function filterTradeExecutionRows(rows) {
  const lifecycle = String(tradeExecutionFilters.lifecycle || '').toUpperCase();
  const status = String(tradeExecutionFilters.status || '').toUpperCase();
  const outcome = String(tradeExecutionFilters.outcome || '').toUpperCase();
  const side = String(tradeExecutionFilters.side || '').toUpperCase();
  const signalNeedle = String(tradeExecutionFilters.signalId || '').toLowerCase();
  const transactionNeedle = String(tradeExecutionFilters.transactionId || '').toLowerCase();

  return rows.filter(row => {
    if (lifecycle && row.lifecycle !== lifecycle) return false;
    if (status && row.status !== status) return false;
    if (outcome && row.trade_outcome !== outcome) return false;
    if (side && row.direction !== side) return false;
    if (signalNeedle) {
      const haystack = `${row.signal_id || ''} ${row.record_id ?? ''}`.toLowerCase();
      if (!haystack.includes(signalNeedle)) return false;
    }
    if (transactionNeedle) {
      const haystack = `${row.transaction_id || ''}`.toLowerCase();
      if (!haystack.includes(transactionNeedle)) return false;
    }
    return true;
  });
}

function tradeExecutionReason(row) {
  const reason = String(row.failure_reason || '').trim();
  const details = String(row.error_details || '').trim();
  const reasonText = details || reason;
  const isMarketClosed = reason === 'MarketNotTradeableError' || /not\s+TRADEABLE|market.*closed/i.test(reasonText);
  if (isMarketClosed) {
    const base = reasonText && reasonText !== 'MarketNotTradeableError'
      ? reasonText.replace(/\.$/, '')
      : 'Capital.com market is closed or not currently tradeable';
    const retryText = row.next_attempt_at
      ? `Retry scheduled ${fmtDate(row.next_attempt_at)}`
      : 'Queued for retry';
    return `${base}. ${retryText}.`;
  }
  return reasonText;
}

function tradeTransactionText(row) {
  if (row.source !== 'TRADE') return '';
  if (!row.deal_id) return 'n/a';
  if (row.transaction_id) return row.transaction_id;
  if (row.transaction_lookup_error) return 'lookup error';
  if (row.transaction_lookup_status) return row.transaction_lookup_status.toLowerCase();
  return 'not found';
}

function tradeOutcomeHtml(row) {
  if (row.source !== 'TRADE') return '<span class="muted">n/a</span>';
  const outcome = row.trade_outcome || (row.status === 'CLOSED' ? 'UNKNOWN' : row.status || 'PENDING');
  const detail = row.trade_close_source
    ? `Source ${row.trade_close_source}${row.trade_close_level ? ` @ ${fmtNumber(row.trade_close_level)}` : ''}`
    : (row.trade_outcome_reason || row.trade_outcome_lookup_error || '');
  return `${chip(outcome)}${detail ? `<br><span class="muted">${escapeHtml(detail)}</span>` : ''}`;
}

function tradeOutcomeCounts(rows) {
  const counts = { WIN: 0, LOSS: 0, UNKNOWN: 0, OPEN: 0, OTHER: 0, total: 0 };
  rows.forEach(row => {
    if (row.source !== 'TRADE') return;
    counts.total += 1;
    const outcome = String(row.trade_outcome || (row.status === 'CLOSED' ? 'UNKNOWN' : row.status || 'UNKNOWN')).toUpperCase();
    if (Object.prototype.hasOwnProperty.call(counts, outcome)) {
      counts[outcome] += 1;
    } else {
      counts.OTHER += 1;
    }
  });
  return counts;
}

function formatSignedCount(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${fmtCount(number)}`;
}

function tradeExecutionTableRows(rows) {
  if (!rows.length) {
    return '<tr><td colspan="16"><div class="empty">No trade execution records match the selected filters.</div></td></tr>';
  }

  return rows.map(row => {
    const isTrade = row.source === 'TRADE';
    const hasActualEntry = row.actual_entry !== undefined && row.actual_entry !== null && row.actual_entry !== '';
    const sizeText = isTrade
      ? `${fmtNumber(row.requested_size)} / ${fmtNumber(row.executed_size)}`
      : `${fmtNumber(row.requested_size)} / n/a`;
    const entryText = isTrade
      ? `${fmtNumber(row.recommended_entry)} / ${hasActualEntry ? fmtNumber(row.actual_entry) : 'not filled'}`
      : `${fmtNumber(row.recommended_entry)} / n/a`;
    const levelsText = `${fmtNumber(row.take_profit)} / ${fmtNumber(row.stop_loss)}`;
    const referenceHtml = isTrade
      ? `${escapeHtml(row.deal_reference || '')}<br><span class="muted">${escapeHtml(row.deal_id || '')}</span>`
      : `${escapeHtml(row.requested_by || 'manual/auto')}<br><span class="muted">${escapeHtml(row.attempt_count)} attempts</span>`;
    const timingHtml = isTrade
      ? `${fmtDate(row.updated_at || row.created_at)}<br><span class="muted">Created ${fmtDate(row.created_at)}</span>`
      : `${fmtDate(row.next_attempt_at)}<br><span class="muted">Updated ${fmtDate(row.updated_at || row.created_at)}</span>`;
    const actionButtons = [];
    if (isTrade && row.status === 'OPEN') {
      actionButtons.push(`<button class="mini-copy" data-force-close="${escapeHtml(row.record_id ?? '')}">Force Close</button>`);
    }
    const actionHtml = actionButtons.join('<br>');

    return `<tr>
      <td>${chip(row.lifecycle)}</td>
      <td>${escapeHtml(row.source)} #${escapeHtml(row.record_id ?? '')}</td>
      <td>${escapeHtml(row.signal_id || '')}<br><span class="muted">${fmtDate(row.created_at)}</span></td>
      <td>${chip(row.status || 'PENDING')}</td>
      <td>${tradeOutcomeHtml(row)}</td>
      <td>${chip(row.signal_status || 'n/a')}<br><span class="muted">${escapeHtml(row.signal_label || row.validation_status || '')}</span></td>
      <td>${escapeHtml(row.epic || '')}</td>
      <td>${escapeHtml(row.direction || '')}</td>
      <td>${sizeText}</td>
      <td>${entryText}</td>
      <td>${levelsText}</td>
      <td>${referenceHtml}</td>
      <td>${escapeHtml(tradeTransactionText(row))}</td>
      <td>${timingHtml}</td>
      <td>${escapeHtml(tradeExecutionReason(row) || row.transaction_lookup_error || '')}</td>
      <td>${actionHtml}</td>
    </tr>`;
  }).join('');
}

function renderTrades(data) {
  const te = data.trade_execution || {};
  const queue = te.queue || {};
  const trades = te.trades || [];
  const active = te.active_trades || trades.filter(t => ['OPEN', 'CLOSE_REQUESTED'].includes(String(t.status || '').toUpperCase()));
  const pending = te.pending_trades || trades.filter(t => ['PENDING', 'SUBMITTED'].includes(String(t.status || '').toUpperCase()));
  const historical = te.historical_trades || trades.filter(t => !['OPEN', 'CLOSE_REQUESTED', 'PENDING', 'SUBMITTED'].includes(String(t.status || '').toUpperCase()));
  const queueEntries = queue.entries || [];
  const allRows = normalizeTradeExecutionRows(active, pending, historical, queueEntries);
  const filteredRows = filterTradeExecutionRows(allRows);
  const allOutcomeCounts = tradeOutcomeCounts(allRows);
  const filteredOutcomeCounts = tradeOutcomeCounts(filteredRows);
  const outcomeKpiSub = key => `${fmtCount(filteredOutcomeCounts[key] || 0)} filtered / ${fmtCount(allOutcomeCounts[key] || 0)} loaded`;
  const filteredOutcomePnl = (filteredOutcomeCounts.WIN || 0) - (filteredOutcomeCounts.LOSS || 0);
  const allOutcomePnl = (allOutcomeCounts.WIN || 0) - (allOutcomeCounts.LOSS || 0);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / TRADE_EXECUTION_PAGE_SIZE));
  tradeExecutionPage = Math.min(Math.max(1, Number(tradeExecutionPage || 1)), totalPages);
  const pageStart = (tradeExecutionPage - 1) * TRADE_EXECUTION_PAGE_SIZE;
  const pageRows = filteredRows.slice(pageStart, pageStart + TRADE_EXECUTION_PAGE_SIZE);
  const statusOptions = tradeFilterOptions(allRows, 'status')
    .map(status => tradeFilterOption(status, status, tradeExecutionFilters.status))
    .join('');
  const outcomeOptions = tradeFilterOptions(allRows, 'trade_outcome')
    .filter(outcome => ['WIN', 'LOSS', 'OPEN', 'UNKNOWN'].includes(outcome))
    .map(outcome => tradeFilterOption(outcome, outcome, tradeExecutionFilters.outcome))
    .join('');
  const sideOptions = tradeFilterOptions(allRows, 'direction')
    .map(side => tradeFilterOption(side, side, tradeExecutionFilters.side))
    .join('');

  $('trades').innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Executed Signals</h2>
        <p>Capital.com demo executions, queue requests, transaction IDs, and historical outcomes in one filtered table.</p>
      </div>
      ${chip(te.ok ? 'Execution API OK' : te.error || 'Execution unavailable')}
    </div>
    <div class="kpi-grid" style="margin-bottom: 12px;">
      ${kpi('Active Trades', fmtCount(active.length), 'OPEN / close requested')}
      ${kpi('Pending Trades', fmtCount(pending.length), 'PENDING / submitted')}
      ${kpi('Queue Requests', fmtCount(queueEntries.length), JSON.stringify(queue.counts || {}))}
      ${kpi('Historical Trades', fmtCount(historical.length), 'Closed, failed, rejected')}
    </div>
    <div class="kpi-grid" style="margin-bottom: 12px;">
      ${kpi('Outcome Wins', fmtCount(filteredOutcomeCounts.WIN), outcomeKpiSub('WIN'))}
      ${kpi('Outcome Losses', fmtCount(filteredOutcomeCounts.LOSS), outcomeKpiSub('LOSS'))}
      ${kpi('Outcome PNL', formatSignedCount(filteredOutcomePnl), `${formatSignedCount(filteredOutcomePnl)} filtered / ${formatSignedCount(allOutcomePnl)} loaded`)}
      ${kpi('Unknown Outcomes', fmtCount(filteredOutcomeCounts.UNKNOWN), outcomeKpiSub('UNKNOWN'))}
      ${kpi('Open Outcomes', fmtCount(filteredOutcomeCounts.OPEN), outcomeKpiSub('OPEN'))}
    </div>

    <div class="control-grid" style="grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 10px;">
      <label class="field">Lifecycle
        <select id="tradeLifecycleFilter">
          ${tradeFilterOption('', 'All lifecycle states', tradeExecutionFilters.lifecycle)}
          ${tradeFilterOption('ACTIVE', 'Active trades', tradeExecutionFilters.lifecycle)}
          ${tradeFilterOption('PENDING', 'Pending trades', tradeExecutionFilters.lifecycle)}
          ${tradeFilterOption('QUEUE', 'Execution queue', tradeExecutionFilters.lifecycle)}
          ${tradeFilterOption('HISTORICAL', 'Historical trades', tradeExecutionFilters.lifecycle)}
        </select>
      </label>
      <label class="field">Status
        <select id="tradeStatusFilter">
          ${tradeFilterOption('', 'All statuses', tradeExecutionFilters.status)}
          ${statusOptions}
        </select>
      </label>
      <label class="field">Outcome
        <select id="tradeOutcomeFilter">
          ${tradeFilterOption('', 'All outcomes', tradeExecutionFilters.outcome)}
          ${outcomeOptions || `${tradeFilterOption('WIN', 'WIN', tradeExecutionFilters.outcome)}${tradeFilterOption('LOSS', 'LOSS', tradeExecutionFilters.outcome)}`}
        </select>
      </label>
      <label class="field">Side
        <select id="tradeSideFilter">
          ${tradeFilterOption('', 'All sides', tradeExecutionFilters.side)}
          ${sideOptions}
        </select>
      </label>
      <label class="field">Signal / Record ID
        <input id="tradeSignalFilter" value="${escapeHtml(tradeExecutionFilters.signalId)}" autocomplete="off">
      </label>
      <label class="field">Transaction ID
        <input id="tradeTransactionFilter" value="${escapeHtml(tradeExecutionFilters.transactionId)}" autocomplete="off">
      </label>
    </div>
    <div class="signal-table-footer" style="margin-bottom: 10px;">
      <div class="signal-pagination-left">
        <span class="chip info">${fmtCount(filteredRows.length)} of ${fmtCount(allRows.length)} records</span>
        <span class="chip">Page ${fmtCount(tradeExecutionPage)} / ${fmtCount(totalPages)}</span>
        <span class="muted">Showing ${filteredRows.length ? fmtCount(pageStart + 1) : 0}-${fmtCount(Math.min(pageStart + pageRows.length, filteredRows.length))} of ${fmtCount(filteredRows.length)}</span>
        <button id="tradeApply" class="btn-alt" style="min-height: 34px; padding: 6px 10px;">Apply Filters</button>
        <button id="tradeReset" class="btn-warn" style="min-height: 34px; padding: 6px 10px;">Reset Filters</button>
      </div>
      <div class="signal-pagination-right">
        <button id="tradePrev" class="btn-alt" ${tradeExecutionPage <= 1 ? 'disabled' : ''} style="min-height: 34px; padding: 6px 10px;">Prev</button>
        <div class="signal-pagination-pages">${buildTradePaginationButtons(tradeExecutionPage, totalPages)}</div>
        <button id="tradeNext" class="btn-alt" ${tradeExecutionPage >= totalPages ? 'disabled' : ''} style="min-height: 34px; padding: 6px 10px;">Next</button>
      </div>
    </div>

    <div class="table-wrap"><table><thead><tr><th>Lifecycle</th><th>Record</th><th>Signal</th><th>Status</th><th>Outcome</th><th>Signal Status</th><th>Epic</th><th>Side</th><th>Req / Exec Size</th><th>Signal / Actual Entry</th><th>TP / SL</th><th>Broker / Queue Ref</th><th>Transaction ID</th><th>Timing</th><th>Reason</th><th>Action</th></tr></thead><tbody>${tradeExecutionTableRows(pageRows)}</tbody></table></div>`;
}

function renderBaselines(data) {
  const entries = Object.entries(data.baseline_summary || {});
  const rows = entries.length
    ? entries.map(([name, value]) => `<tr>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(value.forecast_direction || 'n/a')}</td>
      <td>${escapeHtml(value.quality_status || 'n/a')}</td>
      <td>${value.direction_accuracy_pct === undefined || value.direction_accuracy_pct === null ? 'n/a' : `${fmtNumber(value.direction_accuracy_pct, 2)}%`}</td>
    </tr>`).join('')
    : '<tr><td colspan="4">No baseline reports yet.</td></tr>';

  $('baselines').innerHTML = `
    <div class="panel-head"><h2>Baselines</h2><span class="chip info">${entries.length} reports</span></div>
    <div class="table-wrap"><table><thead><tr><th>Baseline</th><th>Direction</th><th>Quality</th><th>Direction Accuracy</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderFiles(data) {
  const rows = Object.entries(data.files || {})
    .map(([k, p]) => p ? `<tr><td>${escapeHtml(k)}</td><td><a target="_blank" href="/file?path=${encodeURIComponent(p)}">${escapeHtml(p)}</a></td></tr>` : '')
    .join('');

  $('files').innerHTML = `
    <div class="panel-head"><h2>Generated Files</h2><span class="chip info">Artifacts</span></div>
    <div class="table-wrap"><table><thead><tr><th>Type</th><th>Path</th></tr></thead><tbody>${rows || '<tr><td colspan="2">No files found.</td></tr>'}</tbody></table></div>`;
}

function renderHistory(data, db) {
  const fileRows = (data.history || []).map(r => `<tr>
    <td>${fmtDate(r.generated_at_local)}</td>
    <td>${fmtDate(r.forecast_start)}<br>${fmtDate(r.forecast_end)}</td>
    <td>${escapeHtml(r.resolution || '')}</td>
    <td>${escapeHtml(r.direction || '')}</td>
    <td>${escapeHtml(r.quality_status || '')}</td>
    <td>${r.forecast_path ? `<a target="_blank" href="/file?path=${encodeURIComponent(r.forecast_path)}">CSV</a>` : ''}</td>
  </tr>`).join('');

  const dbRows = (db.recent_runs || []).map(r => `<tr>
    <td>${escapeHtml(r.signal_id || r.run_id || '')}<br><span class="muted">${escapeHtml(r.epic || '')} ${escapeHtml(r.resolution || '')}</span></td>
    <td>${fmtDate(r.forecast_start_timestamp_utc)}<br>${fmtDate(r.forecast_end_timestamp_utc)}</td>
    <td>${chip(r.run_status)}</td>
    <td>${chip(r.signal_status || r.signal || '')}</td>
    <td>${escapeHtml(r.wins || 0)}</td>
    <td>${escapeHtml(r.losses || 0)}</td>
    <td>${escapeHtml(r.pending || 0)}</td>
  </tr>`).join('');

  return `
    <h3>File Artifact History</h3>
    <div class="table-wrap"><table><thead><tr><th>Generated</th><th>Window</th><th>Resolution</th><th>Direction</th><th>Quality</th><th>Forecast</th></tr></thead><tbody>${fileRows || '<tr><td colspan="6">No file history found.</td></tr>'}</tbody></table></div>
    <h3 style="margin-top: 14px;">Database Run History</h3>
    <div class="table-wrap"><table><thead><tr><th>Run / Signal</th><th>Window</th><th>Run Status</th><th>Signal Status</th><th>WIN</th><th>LOSS</th><th>PENDING</th></tr></thead><tbody>${dbRows || '<tr><td colspan="7">No DB run history found.</td></tr>'}</tbody></table></div>`;
}

function renderActiveTabContent(options = {}) {
  const { background = false, forceOverview = false } = options;
  if (activeTab === 'overview') {
    if (!isSignalsFilterInteracting()) {
      renderOverview({ background, force: forceOverview });
    }
    return;
  }
  if (activeTab === 'validation') {
    renderValidation(latest);
    return;
  }
  if (activeTab === 'modelPerformance') {
    renderModelPerformance(latestModelPerformance || latest.postgres_snapshot || {});
    return;
  }
  if (activeTab === 'risk') {
    renderRisk(latest);
    return;
  }
  if (activeTab === 'trades') {
    if (!isTradeExecutionFilterInteracting()) {
      renderTrades(latest);
    }
    return;
  }
  if (activeTab === 'baselines') {
    renderBaselines(latest);
    return;
  }
  if (activeTab === 'history') {
    const db = latest.prediction_db || {};
    $('history').innerHTML = `<div class="panel-head"><h2>History</h2><span class="chip info">${(db.recent_runs || []).length} DB runs</span></div>${renderHistory(latest, db)}`;
    return;
  }
  if (activeTab === 'files') {
    renderFiles(latest);
  }
}

function renderModelPerformance(perf) {
  const active = perf.active_model || {};
  const shadow = perf.shadow_model || {};
  const disagreement = perf.disagreement || {};
  const comparison = perf.comparison || {};
  const matched = comparison.matched_runs || {};
  const statusCmp = comparison.signal_status || {};
  const activeMatched = matched.active || {};
  const shadowMatched = matched.shadow || {};
  const statusActiveAll = statusCmp.active_all_runs || {};
  const statusActiveCovered = statusCmp.active_shadow_covered_runs || {};
  const statusShadowRuns = statusCmp.shadow_runs || {};
  const horizons = perf.horizons || perf.horizon_metrics || [];
  const gates = perf.promotion_gates || [];
  const horizonRows = horizons.length
    ? horizons.map(h => `<tr><td>${escapeHtml(h.horizon_index)}</td><td>${fmtCount(h.samples)}</td><td>${h.active_accuracy_pct === null || h.active_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(h.active_accuracy_pct, 2)}%`}</td><td>${h.shadow_accuracy_pct === null || h.shadow_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(h.shadow_accuracy_pct, 2)}%`}</td><td>${h.mape_pct === null || h.mape_pct === undefined ? 'n/a' : `${fmtNumber(h.mape_pct, 4)}%`}</td></tr>`).join('')
    : '<tr><td colspan="5">No horizon metrics persisted yet.</td></tr>';
  const gateRows = gates.length
    ? gates.map(g => `<tr><td>${escapeHtml(g.gate_name)}</td><td>${chip(g.status)}</td><td>${fmtNumber(g.metric_value)}</td><td>${fmtNumber(g.threshold_value)}</td></tr>`).join('')
    : '<tr><td colspan="4">No promotion gates evaluated yet.</td></tr>';
  const matchedRows = `<tr><th>Wins / Losses</th><td>${fmtCount(activeMatched.wins)} / ${fmtCount(activeMatched.losses)}</td><td>${fmtCount(shadowMatched.wins)} / ${fmtCount(shadowMatched.losses)}</td></tr>
    <tr><th>Directional Samples</th><td>${fmtCount(activeMatched.samples)}</td><td>${fmtCount(shadowMatched.samples)}</td></tr>
    <tr><th>Win Rate</th><td>${activeMatched.win_rate_pct === null || activeMatched.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(activeMatched.win_rate_pct, 2)}%`}</td><td>${shadowMatched.win_rate_pct === null || shadowMatched.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(shadowMatched.win_rate_pct, 2)}%`}</td></tr>
    <tr><th>Shadow Lift</th><td colspan="2">${matched.shadow_minus_active_pct === null || matched.shadow_minus_active_pct === undefined ? 'n/a' : `${fmtNumber(matched.shadow_minus_active_pct, 2)}%`}</td></tr>
    <tr><th>Disagreements</th><td>${fmtCount(matched.disagreement?.active_wins_when_disagree)} active wins / ${fmtCount(matched.disagreement?.samples)} samples</td><td>${fmtCount(matched.disagreement?.shadow_wins_when_disagree)} shadow wins / ${fmtCount(matched.disagreement?.samples)} samples</td></tr>`;
  const statusRows = `<tr><th>Wins / Losses / Pending</th><td>${fmtCount(statusActiveAll.wins)} / ${fmtCount(statusActiveAll.losses)} / ${fmtCount(statusActiveAll.pending)}</td><td>${fmtCount(statusActiveCovered.wins)} / ${fmtCount(statusActiveCovered.losses)} / ${fmtCount(statusActiveCovered.pending)}</td><td>${fmtCount(statusShadowRuns.wins)} / ${fmtCount(statusShadowRuns.losses)} / ${fmtCount(statusShadowRuns.pending)}</td></tr>
    <tr><th>Run Count</th><td>${fmtCount(statusActiveAll.total)}</td><td>${fmtCount(statusActiveCovered.total)}</td><td>${fmtCount(statusShadowRuns.total)}</td></tr>
    <tr><th>Win Rate</th><td>${statusActiveAll.win_rate_pct === null || statusActiveAll.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusActiveAll.win_rate_pct, 2)}%`}</td><td>${statusActiveCovered.win_rate_pct === null || statusActiveCovered.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusActiveCovered.win_rate_pct, 2)}%`}</td><td>${statusShadowRuns.win_rate_pct === null || statusShadowRuns.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusShadowRuns.win_rate_pct, 2)}%`}</td></tr>`;
  $('modelPerformance').innerHTML = `
    <div class="panel-head"><h2>Model Performance</h2><span class="chip info">${escapeHtml(shadow.model_version_id || shadow.shadow_model_version_id || 'no shadow')}</span></div>
    <div class="kpi-grid" style="margin-bottom: 12px;">
      ${kpi('Active Accuracy', active.direction_accuracy_pct === null || active.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(active.direction_accuracy_pct, 2)}%`, `${fmtCount(active.samples)} samples`)}
      ${kpi('Shadow Accuracy', shadow.direction_accuracy_pct === null || shadow.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(shadow.direction_accuracy_pct, 2)}%`, `${fmtCount(shadow.samples)} samples`)}
      ${kpi('Shadow Lift', shadow.lift_pct === null || shadow.lift_pct === undefined ? 'n/a' : `${fmtNumber(shadow.lift_pct, 2)}%`, 'Shadow minus active')}
      ${kpi('Disagreements', fmtCount(disagreement.samples), `${fmtCount(disagreement.shadow_wins_when_disagree)} shadow wins`)}
    </div>
    <h3>Fair Comparison (Same Evaluated Windows)</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Active</th><th>Shadow</th></tr></thead><tbody>${matchedRows}</tbody></table></div>
    <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">Shadow model: ${escapeHtml(comparison.shadow_model_version_id || shadow.model_version_id || 'n/a')} · evaluation rows: ${fmtCount(matched.evaluation_rows)}</div>
    <h3 style="margin-top: 14px;">Signal Status Comparison (Run-level)</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Active (all runs)</th><th>Active (shadow-covered runs)</th><th>Shadow runs</th></tr></thead><tbody>${statusRows}</tbody></table></div>
    <h3>Horizon Metrics</h3>
    <div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Samples</th><th>Active Accuracy</th><th>Shadow Accuracy</th><th>MAPE</th></tr></thead><tbody>${horizonRows}</tbody></table></div>
    <h3 style="margin-top: 14px;">Promotion Gates</h3>
    <div class="table-wrap"><table><thead><tr><th>Gate</th><th>Status</th><th>Metric</th><th>Threshold</th></tr></thead><tbody>${gateRows}</tbody></table></div>`;
}

function render(data, options = {}) {
  const { background = false, forceOverview = false } = options;
  latest = data;
  const m = data.metadata || {};
  const v = data.validation || {};
  const db = data.prediction_db || {};
  const pg = data.postgres_snapshot || {};
  const hs = data.human_summary || {};
  const latestSignal = (pg.signals || [])[0] || {};
  const postgresOk = pg.postgres?.ok === true;
  const titleSymbol = data.selected_symbol || $('market').value || 'ETHUSD';
  const resolvedPrice = resolveLatestPrice(data);
  const titlePriceTime = resolveLatestPriceTime(data);
  const titleText = resolvedPrice === null ? `${titleSymbol} --` : `${titleSymbol} ${fmtNumber(resolvedPrice, 2)}`;
  const titleTooltip = titlePriceTime ? `Updated ${fmtDate(titlePriceTime)}` : 'Live quote unavailable';
  setTextIfChanged($('titlePrice'), titleText);
  setTitleIfChanged($('titlePrice'), titleTooltip);
  const browserTitle = `${titleText} | Kronos Signal Dashboard`;
  if (document.title !== browserTitle) {
    document.title = browserTitle;
  }

  const runtimeHtml = postgresOk ? chip('PostgreSQL OK') : chip('PostgreSQL Offline');
  const runtimeKey = postgresOk ? 'ok' : 'offline';
  if (runtimeKey !== lastRuntimeStatusKey) {
    setHtmlIfChanged($('runtimeStatus'), runtimeHtml);
    lastRuntimeStatusKey = runtimeKey;
  }

  const heartbeatStates = Object.entries(pg.worker_statuses || {})
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, state]) => `${name}:${String(state?.status || 'MISSING').toUpperCase()}`)
    .join('|');
  const heartbeatHtml = renderHeartbeat(pg);
  if (heartbeatStates !== lastHeartbeatStatusKey) {
    setHtmlIfChanged($('heartbeatStatus'), heartbeatHtml);
    lastHeartbeatStatusKey = heartbeatStates;
  }

  const websocketHealthLabel = hs.websocket_stale_alert ? 'websocket stale' : 'websocket fresh';
  const heroMetaHtml = [
    chip(hs.signal || latestSignal.signal || 'n/a'),
    chip(hs.signal_status || latestSignal.status || 'PENDING'),
    chip(v.forecast_direction || 'Direction pending'),
    chip(postgresOk ? 'PostgreSQL OK' : 'PostgreSQL Offline'),
    chip(hs.live_source || 'no_live_source'),
    chip(websocketHealthLabel),
    `<span class="chip info">${escapeHtml(data.selected_resolution || m.resolution || latestSignal.resolution || 'MINUTE')}</span>`,
  ].join('');
  const heroMetaKey = [
    hs.signal || latestSignal.signal || 'n/a',
    hs.signal_status || latestSignal.status || 'PENDING',
    v.forecast_direction || 'Direction pending',
    postgresOk ? 'ok' : 'offline',
    hs.live_source || 'no_live_source',
    websocketHealthLabel,
    data.selected_resolution || m.resolution || latestSignal.resolution || 'MINUTE',
  ].join('|');
  if (heroMetaKey !== lastHeroMetaKey) {
    setHtmlIfChanged($('heroMeta'), heroMetaHtml);
    lastHeroMetaKey = heroMetaKey;
  }

  renderModelStatus(data.auto_finetune || {}, m);

  const summaryCardsHtml = [
    kpi('Current Price', resolvedPrice === null ? 'n/a' : fmtNumber(resolvedPrice), titlePriceTime ? `Updated: ${fmtDate(titlePriceTime)}` : 'Latest stored candle close'),
    kpi('Signal', hs.signal || 'n/a', `Status: ${hs.signal_status || 'PENDING'}`),
    kpi('Entry / TP / SL', `${fmtNumber(hs.entry_price)} / ${fmtNumber(hs.tp_price)} / ${fmtNumber(hs.sl_price)}`, 'Trade levels'),
    kpi('Confidence', hs.confidence_pct === null || hs.confidence_pct === undefined ? 'n/a' : `${fmtNumber(hs.confidence_pct, 2)}%`, 'Model confidence'),
    kpi('Last Prediction', fmtDate(hs.last_prediction_time), hs.last_prediction_run_id ? `Run: ${hs.last_prediction_run_id}` : 'No run id'),
    kpi('Last Auto Prediction', fmtDate(hs.last_auto_prediction_time), 'Scheduler heartbeat timestamp'),
    kpi('Win Rate', db.win_rate_pct === null || db.win_rate_pct === undefined ? 'n/a' : `${Number(db.win_rate_pct).toFixed(2)}%`, `${db.wins ?? 0} WIN / ${db.losses ?? 0} LOSS`),
    kpi('Pending Candles', db.pending ?? 0, 'Awaiting actual candle close'),
  ].join('');
  const summaryCardsKey = [
    resolvedPrice === null ? 'n/a' : fmtNumber(resolvedPrice),
    titlePriceTime || '',
    hs.signal || 'n/a',
    hs.signal_status || 'PENDING',
    fmtNumber(hs.entry_price),
    fmtNumber(hs.tp_price),
    fmtNumber(hs.sl_price),
    hs.confidence_pct === null || hs.confidence_pct === undefined ? 'n/a' : fmtNumber(hs.confidence_pct, 2),
    hs.last_prediction_time || '',
    hs.last_prediction_run_id || '',
    hs.last_auto_prediction_time || '',
    db.win_rate_pct === null || db.win_rate_pct === undefined ? 'n/a' : Number(db.win_rate_pct).toFixed(2),
    String(db.pending ?? 0),
  ].join('|');
  if (summaryCardsKey !== lastSummaryCardsKey) {
    setHtmlIfChanged($('summaryCards'), summaryCardsHtml);
    lastSummaryCardsKey = summaryCardsKey;
  }

  renderActiveTabContent({ background, forceOverview });

  drawCloseChart();
  drawCandleChart();
}

function resolutionToMs(resolution) {
  const map = {
    MINUTE: 60 * 1000,
    MINUTE_5: 5 * 60 * 1000,
    MINUTE_15: 15 * 60 * 1000,
    MINUTE_30: 30 * 60 * 1000,
    HOUR: 60 * 60 * 1000,
    HOUR_4: 4 * 60 * 60 * 1000,
    DAY: 24 * 60 * 60 * 1000,
    WEEK: 7 * 24 * 60 * 60 * 1000,
  };
  return map[resolution] || 60 * 1000;
}

function candleClosedBucket(resolution) {
  const ms = resolutionToMs(resolution);
  return Math.floor(Date.now() / ms) - 1;
}

async function maybeAutoPredict() {
  if (!$('autoPredict').checked || autoPredictBusy) return;
  const resolution = $('resolution').value || 'MINUTE';
  const closedBucket = candleClosedBucket(resolution);

  if (lastAutoPredictClosedBucket === null) {
    lastAutoPredictClosedBucket = closedBucket;
    return;
  }

  if (closedBucket > lastAutoPredictClosedBucket) {
    lastAutoPredictClosedBucket = closedBucket;
    autoPredictBusy = true;
    try {
      await runPrediction({ auto: true, silent: true });
    } finally {
      autoPredictBusy = false;
    }
  }
}

async function refreshStatus(options = {}) {
  const { showSpinner = false, background = false } = options;
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    if (showSpinner) showLoader('Refreshing dashboard...');
    const res = await fetch(`/api/status?${currentStatusQuery()}`, { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || `Status HTTP ${res.status}`);
    const perfRes = await fetch(`/api/model-performance?${currentStatusQuery()}`, { cache: 'no-store' });
    latestModelPerformance = await perfRes.json();
    if (!perfRes.ok) latestModelPerformance = null;
    await refreshSignals(signalPage, { renderUi: false });
    render(data, { background, forceOverview: false });
    await maybeAutoPredict();
  } catch (err) {
    showToast(`Status refresh failed: ${err.message}`);
  } finally {
    refreshInFlight = false;
    if (showSpinner) hideLoader();
  }
}

async function postJson(url, payload = {}, options = {}) {
  const {
    loaderText = 'Working...',
    withLoader = true,
    silent = false,
  } = options;
  if (withLoader) showLoader(loaderText);
  try {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) {
      const message = data.error?.message || data.error || `HTTP ${res.status}`;
      throw new Error(message);
    }
    if (!silent) {
      const logEl = $('log');
      if (logEl) {
        logEl.textContent = data.output || data.error || JSON.stringify(data, null, 2);
      }
    }
    if (data.report_url) {
      $('reportFrame').src = data.report_url;
      $('reportFrame').classList.remove('hidden');
      $('reportLink').innerHTML = `<a target="_blank" href="${data.report_url}">Open generated report</a>`;
    }
    await refreshStatus();
    return data;
  } finally {
    if (withLoader) hideLoader();
  }
}

async function runPrediction(options = {}) {
  const auto = options.auto === true;
  const silent = options.silent === true;
  if (!auto) {
    setBusy(true, 'Running');
    $('log').textContent = 'Running prediction...';
  }

  try {
    await postJson('/api/predict', {
      market: $('market').value,
      resolution: $('resolution').value,
      pred_len: Number($('predLen').value),
      lookback: Number($('lookback').value),
      feature_set: $('featureSet').value,
      repair_ohlc: $('repairOhlc').checked,
      run_shadow: true,
    }, {
      loaderText: auto ? 'Auto prediction at candle close...' : 'Running prediction...',
      withLoader: !auto,
      silent: auto || silent,
    });

    if (!auto) showToast('Prediction complete');
  } catch (err) {
    if (!auto) {
      $('log').textContent = err.message;
      showToast(`Prediction failed: ${err.message}`);
    } else {
      console.warn('Auto prediction failed', err);
    }
  } finally {
    if (!auto) setBusy(false);
  }
}

function setupAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  const seconds = Number($('autoRefresh').value);
  if (seconds > 0) {
    refreshTimer = setInterval(() => {
      if (document.visibilityState === 'visible') refreshStatus({ background: true });
    }, seconds * 1000);
  }
}

document.addEventListener('click', async event => {
  const target = event.target;
  if (!target || !(target instanceof HTMLElement)) return;

  if (target.dataset.copy) {
    const text = String(target.dataset.copy || '').trim();
    if (text) {
      try {
        await navigator.clipboard.writeText(text);
        showToast(`Copied ${target.dataset.copyLabel || 'value'}: ${text}`);
      } catch (err) {
        showToast(`Copy failed: ${err.message}`);
      }
    }
  }

  if (target.dataset.auditRun) {
    selectedRunId = String(target.dataset.auditRun || '').trim();
    const row = (latestSignals.rows || []).find(item => item.run_id === selectedRunId) || {};
    $('logs').innerHTML = `<div class="panel-head"><h2>Signal Audit</h2>${chip(row.status || 'PENDING')}</div>
      <div class="table-wrap"><table><tbody>
        <tr><th>Run ID</th><td>${escapeHtml(selectedRunId)}</td></tr>
        <tr><th>Active Signal</th><td>${chip(row.signal || 'n/a')} ${chip(row.status || 'PENDING')}</td></tr>
        <tr><th>Shadow Signal</th><td>${row.shadow_signal ? `${chip(row.shadow_signal)} ${chip(row.shadow_status || 'PENDING')}` : 'n/a'}</td></tr>
        <tr><th>Quality</th><td>${escapeHtml(row.quality_grade || 'n/a')}</td></tr>
        <tr><th>Outcomes</th><td>${fmtCount(row.outcomes_wins)} WIN / ${fmtCount(row.outcomes_losses)} LOSS / ${fmtCount(row.outcomes_pending)} PENDING</td></tr>
        <tr><th>Reason</th><td>${escapeHtml(row.reason || '')}</td></tr>
      </tbody></table></div><pre id="log" class="hidden"></pre>`;
    setTab('logs');
    showToast(`Selected run ${selectedRunId}`);
  }

  if (target.dataset.executeSignal) {
    const signalId = String(target.dataset.executeSignal || '').trim();
    if (signalId) {
      try {
        const result = await postJson('/api/trade-execution/execute-signal', { signal_id: signalId }, { loaderText: 'Executing demo trade...' });
        const tradeStatus = result.trade?.status || result.status || 'submitted';
        showToast(result.message || `Demo execution ${tradeStatus}`);
        refreshStatus({ background: true });
      } catch (err) {
        showToast(`Execution failed: ${err.message}`);
      }
    }
  }

  if (target.dataset.forceClose) {
    const executedTradeId = Number(target.dataset.forceClose || 0);
    if (executedTradeId > 0) {
      try {
        const result = await postJson('/api/trade-execution/force-close', { executed_trade_id: executedTradeId }, { loaderText: 'Closing demo trade...' });
        showToast(result.message || 'Force close submitted');
      } catch (err) {
        showToast(`Force close failed: ${err.message}`);
      }
    }
  }

  if (target.id === 'tradeApply') {
    readTradeExecutionFiltersFromUi();
    tradeExecutionPage = 1;
    renderTrades(latest);
  }

  if (target.id === 'tradeReset') {
    tradeExecutionFilters = {
      lifecycle: '',
      status: '',
      outcome: '',
      side: '',
      signalId: '',
      transactionId: '',
    };
    tradeExecutionPage = 1;
    renderTrades(latest);
  }

  if (target.id === 'tradePrev') {
    tradeExecutionPage = Math.max(1, tradeExecutionPage - 1);
    renderTrades(latest);
  }

  if (target.id === 'tradeNext') {
    tradeExecutionPage += 1;
    renderTrades(latest);
  }

  const numberedTradePageButton = target.closest('[data-trade-page]');
  if (numberedTradePageButton instanceof HTMLElement) {
    const page = Number(numberedTradePageButton.dataset.tradePage || 0);
    if (Number.isFinite(page) && page >= 1) {
      tradeExecutionPage = page;
      renderTrades(latest);
    }
  }

  if (target.id === 'signalsApply') {
    readSignalFiltersFromUi();
    signalPage = 1;
    await refreshSignals(signalPage, { forceRender: true });
  }

  if (target.id === 'signalsReset') {
    signalFilters = {
      timeframe: '',
      dateFrom: '',
      dateTo: '',
      direction: '',
      status: '',
      signalId: '',
    };
    signalPage = 1;
    await refreshSignals(signalPage, { forceRender: true });
  }

  if (target.id === 'signalsFirst') {
    readSignalFiltersFromUi();
    signalPage = 1;
    await refreshSignals(signalPage, { forceRender: true });
  }

  if (target.id === 'signalsLast') {
    readSignalFiltersFromUi();
    const totalPages = Math.max(1, Number(latestSignals.pagination?.total_pages || 1));
    signalPage = totalPages;
    await refreshSignals(signalPage, { forceRender: true });
  }

  if (target.id === 'signalsPrev' && latestSignals.pagination?.has_prev) {
    readSignalFiltersFromUi();
    await refreshSignals(Math.max(1, signalPage - 1), { forceRender: true });
  }

  if (target.id === 'signalsNext' && latestSignals.pagination?.has_next) {
    readSignalFiltersFromUi();
    await refreshSignals(signalPage + 1, { forceRender: true });
  }

  const numberedPageButton = target.closest('[data-signal-page]');
  if (numberedPageButton instanceof HTMLElement) {
    const page = Number(numberedPageButton.dataset.signalPage || 0);
    if (Number.isFinite(page) && page >= 1) {
      readSignalFiltersFromUi();
      await refreshSignals(page, { forceRender: true });
    }
  }
});

document.addEventListener('change', async event => {
  const target = event.target;
  if (!target || !(target instanceof HTMLElement)) return;

  if (TRADE_FILTER_AUTO_APPLY_IDS.has(target.id)) {
    readTradeExecutionFiltersFromUi();
    tradeExecutionPage = 1;
    renderTrades(latest);
    return;
  }

  if (SIGNAL_FILTER_AUTO_APPLY_IDS.has(target.id)) {
    readSignalFiltersFromUi();
    signalPage = 1;
    await refreshSignals(signalPage, { forceRender: true });
    return;
  }

  if (target.id === 'signalsPageSize' && target instanceof HTMLSelectElement) {
    const parsed = Number(target.value || 10);
    signalPageSize = [10, 20, 50, 100].includes(parsed) ? parsed : 10;
    readSignalFiltersFromUi();
    signalPage = 1;
    await refreshSignals(signalPage, { forceRender: true });
  }
});

document.addEventListener('input', event => {
  const target = event.target;
  if (!target || !(target instanceof HTMLElement)) return;
  if (target.id === 'tradeSignalFilter' || target.id === 'tradeTransactionFilter') {
    if (target.id === 'tradeSignalFilter') {
      tradeExecutionFilters.signalId = target.value;
    } else {
      tradeExecutionFilters.transactionId = target.value;
    }
    return;
  }

  if (target.id !== 'signalsSignalId') return;

  readSignalFiltersFromUi();
  signalPage = 1;
  clearTimeout(signalIdFilterDebounceTimer);
  signalIdFilterDebounceTimer = setTimeout(() => {
    refreshSignals(signalPage, { forceRender: true });
  }, 300);
});

document.addEventListener('focusout', event => {
  const target = event.target;
  if (!target || !(target instanceof HTMLElement)) return;
  if (TRADE_FILTER_CONTROL_IDS.has(target.id)) {
    setTimeout(() => {
      if (activeTab === 'trades' && !isTradeExecutionFilterInteracting()) {
        readTradeExecutionFiltersFromUi();
        tradeExecutionPage = 1;
        renderTrades(latest);
      }
    }, 0);
    return;
  }

  if (!SIGNAL_FILTER_CONTROL_IDS.has(target.id)) return;
  setTimeout(() => {
    if (activeTab === 'overview' && !isSignalsFilterInteracting()) {
      renderOverview();
    }
  }, 0);
});

document.addEventListener('keydown', async event => {
  const target = event.target;
  if (event.key === 'Enter' && target instanceof HTMLElement && TRADE_FILTER_CONTROL_IDS.has(target.id)) {
    readTradeExecutionFiltersFromUi();
    tradeExecutionPage = 1;
    renderTrades(latest);
    return;
  }

  if (event.key !== 'Escape') return;
  if (activeTab === 'trades') {
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName)) {
      active.blur();
    }
    tradeExecutionFilters = {
      lifecycle: '',
      status: '',
      outcome: '',
      side: '',
      signalId: '',
      transactionId: '',
    };
    tradeExecutionPage = 1;
    renderTrades(latest);
    showToast('Trade filters reset');
    return;
  }

  const overviewPanel = $('overview');
  if (!overviewPanel || overviewPanel.classList.contains('hidden')) return;
  const active = document.activeElement;
  if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName)) {
    active.blur();
  }
  signalFilters = {
    timeframe: '',
    dateFrom: '',
    dateTo: '',
    direction: '',
    status: '',
    signalId: '',
  };
  signalPage = 1;
  await refreshSignals(signalPage, { forceRender: true });
  showToast('Signal filters reset');
});

document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => setTab(button.dataset.tab)));

$('predict').addEventListener('click', () => runPrediction());
$('refresh').addEventListener('click', () => refreshStatus({ showSpinner: true }));
$('fetchActual').addEventListener('click', () => postJson('/api/fetch-actual', actionContextPayload(), { loaderText: 'Fetching actual candles...' }).then(() => showToast('Actual fetch finished')));
$('validateActual').addEventListener('click', () => postJson('/api/validate-actual', actionContextPayload({ scoring_version: 'v1' }), { loaderText: 'Validating actuals...' }).then(() => showToast('Validation finished')));
$('runBaselines').addEventListener('click', () => postJson('/api/baselines', actionContextPayload(), { loaderText: 'Running baselines...' }).then(() => showToast('Baselines complete')));

$('autoRefresh').addEventListener('change', setupAutoRefresh);
$('autoPredict').addEventListener('change', () => { lastAutoPredictClosedBucket = null; });
$('market').addEventListener('change', () => {
  signalPage = 1;
  refreshStatus();
});
$('resolution').addEventListener('change', () => {
  lastAutoPredictClosedBucket = null;
  signalPage = 1;
  refreshStatus();
});

window.addEventListener('resize', () => {
  drawCloseChart();
  drawCandleChart();
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refreshStatus();
});

signalFilters.timeframe = '';
setupAutoRefresh();
refreshStatus({ showSpinner: true });
</script>
</body>
</html>"""
