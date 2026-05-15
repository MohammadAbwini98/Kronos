from __future__ import annotations

import os

from config import DEFAULT_INSTRUMENT_SYMBOL


def dashboard_html() -> str:
    default_symbol = os.getenv("SIGNAL_SYMBOL", DEFAULT_INSTRUMENT_SYMBOL).strip() or DEFAULT_INSTRUMENT_SYMBOL
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kronos Signal Dashboard</title>
  <style>

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
      grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
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

    .ai-stack-grid {
      grid-template-columns: repeat(6, minmax(0, 1fr));
      margin-bottom: 12px;
    }

    .ai-compact-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
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
      .ai-stack-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .ai-compact-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 640px) {
      .worker-grid { grid-template-columns: 1fr; }
      .model-status-grid { grid-template-columns: 1fr; }
      .model-metrics { grid-template-columns: 1fr; }
      .ai-stack-grid { grid-template-columns: 1fr; }
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

    :root {
      color-scheme: dark;
      --bg: #05070a;
      --bg-2: #0b1017;
      --bg-3: #111822;
      --panel: rgba(11, 16, 23, 0.9);
      --panel-2: rgba(17, 24, 34, 0.92);
      --panel-3: rgba(20, 30, 42, 0.94);
      --line: rgba(192, 161, 78, 0.18);
      --line-strong: rgba(192, 161, 78, 0.34);
      --text: #f7f1df;
      --text-2: #e8dfc5;
      --muted: #9ca7b6;
      --muted-2: #768395;
      --accent: #c0a14e;
      --accent-soft: rgba(192, 161, 78, 0.14);
      --accent-2: #f3d68a;
      --neutral: #43b0d8;
      --neutral-soft: rgba(67, 176, 216, 0.14);
      --bull: #38c172;
      --bull-soft: rgba(56, 193, 114, 0.14);
      --bear: #ff6b57;
      --bear-soft: rgba(255, 107, 87, 0.14);
      --warn: #ffb347;
      --warn-soft: rgba(255, 179, 71, 0.14);
      --shadow: 0 32px 70px rgba(0, 0, 0, 0.46);
      --shadow-soft: 0 18px 38px rgba(0, 0, 0, 0.32);
      --radius: 24px;
      --radius-sm: 16px;
    }

    html {
      background:
        radial-gradient(circle at top left, rgba(192, 161, 78, 0.12), transparent 36%),
        radial-gradient(circle at top right, rgba(67, 176, 216, 0.16), transparent 42%),
        linear-gradient(180deg, #040608 0%, #080c11 38%, #0b1017 100%);
    }

    body {
      min-height: 100vh;
      font-family: Bahnschrift, "Segoe UI Variable Display", "Segoe UI", sans-serif;
      color: var(--text);
      background: transparent;
      letter-spacing: 0.01em;
      overflow-x: hidden;
    }

    body::before,
    body::after {
      content: "";
      position: fixed;
      inset: auto;
      pointer-events: none;
      z-index: 0;
      filter: blur(16px);
      opacity: 0.8;
    }

    body::before {
      top: 90px;
      left: -110px;
      width: 360px;
      height: 360px;
      background: radial-gradient(circle, rgba(192, 161, 78, 0.18), transparent 70%);
    }

    body::after {
      right: -120px;
      bottom: 80px;
      width: 420px;
      height: 420px;
      background: radial-gradient(circle, rgba(67, 176, 216, 0.15), transparent 70%);
    }

    .ambient {
      background-image:
        linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px);
      background-size: 32px 32px;
      opacity: 0.4;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 1), rgba(0, 0, 0, 0.35));
    }

    .shell {
      position: relative;
      z-index: 1;
      max-width: 1680px;
      margin: 0 auto;
      padding: 20px 20px 40px;
      display: grid;
      gap: 16px;
    }

    .panel {
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.01)),
        linear-gradient(135deg, rgba(15, 21, 31, 0.97), rgba(8, 12, 18, 0.96));
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }

    .panel::before {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(135deg, rgba(192, 161, 78, 0.08), transparent 26%, transparent 70%, rgba(67, 176, 216, 0.06));
      opacity: 0.9;
    }

    .topbar,
    .control-board,
    .model-status-panel,
    .chart-panel,
    .details-panel {
      padding: 22px;
    }

    .topbar {
      display: grid;
      grid-template-columns: 1fr;
      position: relative;
      top: 0;
      z-index: 5;
      gap: 16px;
      padding: 20px;
      align-items: start;
      border-color: var(--line-strong);
      background:
        radial-gradient(circle at top left, rgba(192, 161, 78, 0.14), transparent 34%),
        linear-gradient(135deg, rgba(13, 19, 28, 0.98), rgba(7, 10, 15, 0.97));
      box-shadow: 0 26px 60px rgba(0, 0, 0, 0.5);
    }

    .topbar-main {
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1.22fr) minmax(280px, 0.98fr);
      align-items: start;
    }

    .brand {
      display: grid;
      gap: 10px;
    }

    .brand-kicker,
    .section-kicker,
    .hero-eyebrow {
      display: inline-flex;
      width: fit-content;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid rgba(192, 161, 78, 0.2);
      background: rgba(192, 161, 78, 0.08);
      color: var(--accent-2);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }

    .brand h1,
    .panel-head h2,
    .panel-head h3,
    .section-title {
      margin: 0;
      color: var(--text);
      line-height: 1.05;
      letter-spacing: -0.02em;
      font-weight: 700;
    }

    .brand h1 {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 12px;
      font-size: clamp(1.85rem, 3vw, 2.9rem);
    }

    .title-price {
      font-size: clamp(1.1rem, 2vw, 1.65rem);
      color: var(--accent-2);
      text-shadow: 0 0 18px rgba(192, 161, 78, 0.24);
    }

    .brand p,
    .panel-head p,
    .section-sub,
    .muted,
    .tiny-help,
    .meta-note,
    .kpi-sub,
    .score-inline-note,
    .model-support-detail,
    .hero-note,
    .health-sub,
    .risk-sub,
    .signal-history-meta,
    .signal-note {
      color: var(--muted);
      line-height: 1.5;
    }

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .meta-card,
    .kpi,
    .mini-stat,
    .risk-item,
    .health-item,
    .model-support-card,
    .signal-history-card,
    .quote-cell {
      position: relative;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 20px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.015)),
        linear-gradient(180deg, rgba(15, 21, 31, 0.94), rgba(10, 14, 20, 0.94));
      box-shadow: var(--shadow-soft);
    }

    .meta-card {
      padding: 16px;
      min-height: 96px;
    }

    .meta-label,
    .kpi-label,
    .mini-stat-label,
    .quote-label,
    .decision-label,
    .score-ring-label,
    .risk-label,
    .health-name,
    .model-support-name {
      color: var(--muted-2);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 11px;
      font-weight: 700;
    }

    .meta-value,
    .kpi-value,
    .mini-stat-value,
    .quote-value,
    .decision-value,
    .score-ring-value,
    .risk-value,
    .health-state {
      margin-top: 8px;
      color: var(--text);
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .meta-value {
      font-size: 1rem;
      line-height: 1.45;
    }

    .shell > *,
    .topbar-main > *,
    .command-ribbon > *,
    .chart-grid > *,
    .hero-terminal > *,
    .overview-primary > *,
    .overview-secondary > * {
      min-width: 0;
    }

    .command-ribbon {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(140px, 1fr)) minmax(260px, 1.05fr);
      align-items: end;
      padding-top: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.07);
    }

    .command-field {
      min-width: 0;
    }

    .command-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      min-height: auto;
      align-self: end;
      align-items: stretch;
    }

    .command-actions button {
      min-height: 52px;
      align-self: end;
    }

    .model-status-grid {
      display: grid;
      grid-template-columns: minmax(280px, 0.94fr) minmax(0, 1.06fr);
      gap: 14px;
      align-items: stretch;
    }

    .model-version-title {
      font-size: clamp(1.4rem, 2vw, 2rem);
      line-height: 1.15;
      font-weight: 700;
      letter-spacing: -0.02em;
      overflow-wrap: anywhere;
    }

    .model-progress-area {
      display: grid;
      gap: 12px;
      padding: 16px 18px;
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.022);
    }

    .progress-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted-2);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .progress-track {
      height: 10px;
      overflow: hidden;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.07);
      background: rgba(255, 255, 255, 0.06);
    }

    .progress-fill {
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--neutral), #8ddcf4);
      transition: width 220ms ease;
    }

    .model-progress-sub {
      color: var(--muted);
      line-height: 1.45;
    }

    .model-metrics,
    .ai-stack-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }

    .model-stat {
      padding: 14px 16px;
      min-height: 112px;
      display: grid;
      align-content: start;
      gap: 6px;
    }

    .model-stat-label {
      color: var(--muted-2);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .model-stat-value {
      color: var(--text);
      font-size: 1rem;
      font-weight: 700;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .control-head,
    .panel-head,
    .section-titlebar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }

    .control-grid,
    .toggle-row,
    .actions,
    .kpi-grid,
    .quote-grid,
    .hero-meta-grid,
    .ring-grid,
    .score-bar-list,
    .overview-primary,
    .overview-secondary,
    .stats-grid,
    .risk-grid,
    .health-grid,
    .model-support-grid,
    .signal-history-grid,
    .section-skeleton-grid,
    .summary-skeleton {
      display: grid;
      gap: 12px;
    }

    .control-grid {
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    }

    .field {
      display: grid;
      gap: 8px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.012));
      color: var(--text-2);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 700;
    }

    .field input,
    .field select {
      width: 100%;
      min-height: 46px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      background: rgba(8, 11, 16, 0.92);
      color: var(--text);
      padding: 10px 12px;
      font-family: inherit;
      font-size: 14px;
      text-transform: none;
      letter-spacing: normal;
      outline: none;
      transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
    }

    .field input:focus,
    .field select:focus,
    button:focus-visible,
    .tab:focus-visible,
    details summary:focus-visible {
      border-color: rgba(192, 161, 78, 0.4);
      box-shadow: 0 0 0 3px rgba(192, 161, 78, 0.12);
      outline: none;
    }

    .toggle-row {
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }

    .toggle-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.028), rgba(255, 255, 255, 0.012));
      color: var(--text-2);
      font-weight: 600;
    }

    .toggle-card input {
      inline-size: 18px;
      block-size: 18px;
      accent-color: var(--accent);
    }

    .actions {
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }

    button,
    .tab {
      border: 1px solid transparent;
      border-radius: 16px;
      min-height: 46px;
      padding: 12px 16px;
      font-family: inherit;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      cursor: pointer;
      transition: transform 150ms ease, border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
    }

    button:hover,
    .tab:hover {
      transform: translateY(-1px);
      border-color: rgba(255, 255, 255, 0.1);
    }

    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      transform: none;
    }

    .btn-primary {
      color: #120f09;
      background: linear-gradient(135deg, var(--accent), #f6dc94);
      box-shadow: 0 18px 32px rgba(192, 161, 78, 0.2);
    }

    .btn-alt,
    .tab {
      color: var(--text);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02));
      border-color: rgba(255, 255, 255, 0.08);
    }

    .btn-warn {
      color: #180f07;
      background: linear-gradient(135deg, var(--warn), #ffd48a);
      box-shadow: 0 16px 28px rgba(255, 179, 71, 0.2);
    }

    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      padding: 10px;
      border-radius: 22px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(8, 12, 18, 0.84);
      backdrop-filter: blur(12px);
    }

    .tab.active {
      color: #120f09;
      background: linear-gradient(135deg, var(--accent), #f1d182);
      box-shadow: 0 12px 26px rgba(192, 161, 78, 0.22);
    }

    .terminal-summary {
      min-height: 0;
    }

    .hero-terminal {
      display: grid;
      gap: 14px;
      grid-template-columns: minmax(0, 1.28fr) minmax(320px, 0.9fr);
      align-items: stretch;
    }

    .hero-decision,
    .hero-side,
    .section-card {
      position: relative;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 24px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.015)),
        linear-gradient(180deg, rgba(14, 20, 29, 0.96), rgba(9, 13, 19, 0.95));
      box-shadow: var(--shadow-soft);
      padding: 18px;
    }

    .hero-decision::after,
    .hero-side::after,
    .section-card::after {
      content: "";
      position: absolute;
      inset: auto 0 0 0;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(192, 161, 78, 0.4), transparent);
    }

    .hero-header {
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 0.56fr);
      align-items: start;
      margin-bottom: 16px;
    }

    .hero-signal {
      margin-top: 8px;
      font-size: clamp(2rem, 5vw, 4rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
      font-weight: 800;
    }

    .hero-signal.good { color: var(--bull); }
    .hero-signal.bad { color: var(--bear); }
    .hero-signal.warn { color: var(--warn); }
    .hero-signal.info { color: var(--accent-2); }

    .hero-note {
      margin-top: 12px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.025);
      font-size: 14px;
    }

    .hero-note strong,
    .decision-value.good,
    .risk-value.good,
    .health-state.good { color: var(--bull); }

    .decision-value.bad,
    .risk-value.bad,
    .health-state.bad { color: var(--bear); }

    .decision-value.warn,
    .risk-value.warn,
    .health-state.warn { color: var(--warn); }

    .decision-value.info,
    .risk-value.info,
    .health-state.info { color: var(--accent-2); }

    .hero-meta-grid,
    .quote-grid,
    .decision-levels {
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    }

    .quote-cell,
    .decision-level {
      padding: 14px 16px;
      min-height: 92px;
    }

    .quote-value,
    .decision-value,
    .score-ring-value,
    .kpi-value,
    .mini-stat-value,
    .risk-value,
    .health-state {
      font-size: clamp(1.1rem, 1.8vw, 1.5rem);
    }

    .ring-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .score-ring {
      display: grid;
      justify-items: center;
      gap: 8px;
      padding: 14px;
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.03);
    }

    .score-ring-body {
      position: relative;
      display: grid;
      place-items: center;
      inline-size: 108px;
      block-size: 108px;
      border-radius: 50%;
      background: conic-gradient(var(--ring-color, var(--accent)) calc(var(--pct, 0) * 1%), rgba(255, 255, 255, 0.08) 0);
    }

    .score-ring-body::after {
      content: "";
      position: absolute;
      inset: 10px;
      border-radius: 50%;
      background: rgba(8, 12, 18, 0.96);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }

    .score-ring-value {
      position: relative;
      z-index: 1;
      margin: 0;
      font-size: 1.35rem;
    }

    .score-ring-meta {
      position: relative;
      z-index: 1;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
      line-height: 1.45;
    }

    .score-breakdown {
      display: grid;
      gap: 12px;
      margin-top: 16px;
    }

    .score-bar-list {
      grid-template-columns: 1fr;
    }

    .score-bar {
      display: grid;
      gap: 8px;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.025);
    }

    .score-bar-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
    }

    .score-track,
    .distribution-bar {
      position: relative;
      overflow: hidden;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
    }

    .score-track {
      height: 10px;
    }

    .score-fill {
      display: block;
      height: 100%;
      width: calc(var(--score-pct, 0) * 1%);
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #f2d789);
    }

    .score-fill.good { background: linear-gradient(90deg, var(--bull), #82dca5); }
    .score-fill.bad { background: linear-gradient(90deg, var(--bear), #ff9a8d); }
    .score-fill.warn { background: linear-gradient(90deg, var(--warn), #ffd48a); }
    .score-fill.info { background: linear-gradient(90deg, var(--neutral), #76d2ef); }

    .kpi-grid,
    .stats-grid {
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }

    .kpi {
      padding: 16px;
      min-height: 128px;
    }

    .kpi-value {
      margin-top: 10px;
      font-size: clamp(1.2rem, 2vw, 1.65rem);
    }

    .chart-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.22fr) minmax(0, 0.88fr);
      gap: 16px;
    }

    .chart-panel {
      min-height: 470px;
    }

    .chart-wrap {
      position: relative;
      min-height: 360px;
      padding: 10px;
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0.008)),
        linear-gradient(180deg, rgba(8, 12, 17, 0.96), rgba(8, 11, 16, 0.96));
    }

    canvas {
      display: block;
      width: 100%;
      height: 360px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 28px;
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.07);
      background: rgba(255, 255, 255, 0.06);
      color: var(--text);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .chip.good { background: var(--bull-soft); color: #aef0c8; border-color: rgba(56, 193, 114, 0.22); }
    .chip.bad { background: var(--bear-soft); color: #ffc0b7; border-color: rgba(255, 107, 87, 0.22); }
    .chip.warn { background: var(--warn-soft); color: #ffe2aa; border-color: rgba(255, 179, 71, 0.22); }
    .chip.info { background: var(--neutral-soft); color: #b9e8f5; border-color: rgba(67, 176, 216, 0.22); }

    .status-strip,
    .inline-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .details-panel {
      min-height: 0;
    }

    .overview-layout {
      display: grid;
      gap: 14px;
    }

    .overview-primary {
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
      align-items: start;
    }

    .overview-secondary {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;
    }

    .section-card {
      min-height: 0;
    }

    .mini-stat {
      padding: 14px 16px;
    }

    .risk-grid,
    .health-grid,
    .model-support-grid,
    .signal-history-grid {
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    }

    .risk-item,
    .health-item,
    .model-support-card,
    .signal-history-card {
      padding: 14px 16px;
      min-height: 110px;
    }

    .model-support-head,
    .signal-history-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }

    .model-support-body,
    .signal-history-levels {
      display: grid;
      gap: 8px;
    }

    .distribution-row {
      display: grid;
      gap: 10px;
    }

    .distribution-item {
      display: grid;
      gap: 6px;
    }

    .distribution-bar {
      height: 8px;
    }

    .distribution-bar span {
      display: block;
      height: 100%;
      width: calc(var(--dist-pct, 0) * 1%);
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #f2d789);
    }

    .distribution-bar.good span { background: linear-gradient(90deg, var(--bull), #8cddb0); }
    .distribution-bar.bad span { background: linear-gradient(90deg, var(--bear), #ff9b8f); }
    .distribution-bar.warn span { background: linear-gradient(90deg, var(--warn), #ffd48a); }
    .distribution-bar.info span { background: linear-gradient(90deg, var(--neutral), #77d2ee); }

    .mini-chart-wrap {
      overflow: hidden;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.02);
      padding: 12px;
    }

    .mini-chart-wrap svg {
      display: block;
      width: 100%;
      height: 120px;
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 20px;
      background: rgba(7, 11, 16, 0.76);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }

    th,
    td {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      vertical-align: top;
      font-size: 13px;
      color: var(--text-2);
    }

    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: rgba(12, 18, 25, 0.96);
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 11px;
    }

    tr:hover td {
      background: rgba(255, 255, 255, 0.018);
    }

    a {
      color: #82d6f2;
      text-decoration: none;
    }

    a:hover {
      text-decoration: underline;
    }

    pre,
    iframe {
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(8, 11, 16, 0.92);
      color: var(--text-2);
    }

    pre {
      padding: 18px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }

    iframe {
      width: 100%;
      min-height: 560px;
    }

    .warning-stack,
    .error-banner {
      display: grid;
      gap: 10px;
    }

    .warning-item,
    .error-banner {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 179, 71, 0.2);
      background: rgba(255, 179, 71, 0.1);
      color: #ffdca5;
      line-height: 1.5;
    }

    .error-banner {
      position: relative;
      z-index: 28;
      max-width: 1680px;
      margin: 12px auto 0;
      border-color: rgba(255, 107, 87, 0.24);
      background: rgba(255, 107, 87, 0.12);
      color: #ffc7bf;
      box-shadow: var(--shadow-soft);
    }

    .validation-banner {
      display: grid;
      gap: 6px;
      margin: 10px 0 14px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.03);
      color: var(--text-2);
    }

    .validation-banner-title {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .validation-banner-text {
      line-height: 1.5;
    }

    .validation-banner.good {
      border-color: rgba(56, 193, 114, 0.22);
      background: rgba(56, 193, 114, 0.1);
      color: #b7f1cd;
    }

    .validation-banner.warn {
      border-color: rgba(255, 179, 71, 0.22);
      background: rgba(255, 179, 71, 0.1);
      color: #ffe0ad;
    }

    .validation-banner.bad {
      border-color: rgba(255, 107, 87, 0.24);
      background: rgba(255, 107, 87, 0.11);
      color: #ffc7bf;
    }

    .filter-grid--signals {
      grid-template-columns: repeat(6, minmax(0, 1fr));
      margin-bottom: 10px;
    }

    .filter-actions--signals {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 10px 0;
    }

    .field.signal-page-size-field {
      max-width: 180px;
    }

    .summary-skeleton,
    .section-skeleton-grid {
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }

    .skeleton-panel {
      min-height: 148px;
      border-radius: 22px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      background: linear-gradient(110deg, rgba(255, 255, 255, 0.03) 8%, rgba(255, 255, 255, 0.08) 18%, rgba(255, 255, 255, 0.03) 33%);
      background-size: 220% 100%;
      animation: terminalShimmer 1.8s linear infinite;
    }

    .skeleton-panel--hero,
    .skeleton-panel--wide {
      min-height: 220px;
      grid-column: span 2;
    }

    .signal-table-footer,
    .signal-pagination-left,
    .signal-pagination-right {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
    }

    .signal-group-start td {
      border-top: 1px solid rgba(192, 161, 78, 0.14);
    }

    .mini-copy {
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(255, 255, 255, 0.03);
      color: var(--text);
      padding: 8px 10px;
      font-size: 11px;
      letter-spacing: 0.08em;
    }

    .empty {
      display: grid;
      place-items: center;
      gap: 6px;
      padding: 26px 18px;
      color: var(--muted);
      text-align: center;
      border: 1px dashed rgba(255, 255, 255, 0.08);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.018);
    }

    .hidden {
      display: none !important;
    }

    .loader-overlay {
      position: fixed;
      inset: 0;
      z-index: 35;
      display: grid;
      place-items: center;
      background: rgba(4, 7, 10, 0.74);
      backdrop-filter: blur(12px);
    }

    .loader-card {
      width: min(340px, calc(100vw - 28px));
      display: grid;
      gap: 12px;
      place-items: center;
      text-align: center;
      border-radius: 26px;
      border: 1px solid rgba(192, 161, 78, 0.18);
      background: linear-gradient(180deg, rgba(12, 18, 25, 0.98), rgba(7, 10, 15, 0.97));
      color: var(--text);
      box-shadow: var(--shadow);
      padding: 22px 26px;
    }

    .spinner {
      width: 38px;
      height: 38px;
      border-radius: 999px;
      border: 3px solid rgba(255, 255, 255, 0.12);
      border-color: rgba(255, 255, 255, 0.12);
      border-top-color: var(--accent);
    }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 40;
      max-width: min(420px, calc(100vw - 28px));
      padding: 12px 14px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: linear-gradient(180deg, rgba(12, 18, 25, 0.98), rgba(7, 10, 15, 0.97));
      color: var(--text);
      box-shadow: var(--shadow-soft);
      opacity: 0;
      transform: translateY(16px);
      pointer-events: none;
      transition: transform 140ms ease, opacity 140ms ease;
    }

    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }

    details {
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.02);
      padding: 12px 14px;
    }

    summary {
      cursor: pointer;
      color: var(--text);
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    @keyframes terminalShimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }

    @media (max-width: 1240px) {
      .topbar-main,
      .hero-terminal,
      .overview-primary,
      .overview-secondary,
      .chart-grid {
        grid-template-columns: 1fr;
      }

      .command-ribbon {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .command-actions,
      .model-status-grid {
        grid-template-columns: 1fr;
      }

      .filter-grid--signals {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 820px) {
      .shell {
        padding: 14px 14px 28px;
      }

      .topbar {
        top: 0;
      }

      .topbar,
      .control-board,
      .model-status-panel,
      .chart-panel,
      .details-panel {
        padding: 16px;
      }

      .meta-grid,
      .ring-grid,
      .command-ribbon,
      .command-actions,
      .tabs,
      .hero-meta-grid,
      .quote-grid,
      .decision-levels,
      .model-status-grid,
      .filter-grid--signals,
      .filter-actions--signals {
        grid-template-columns: 1fr;
      }

      .tabs {
        display: grid;
      }

      .signal-table-footer,
      .signal-pagination-left,
      .signal-pagination-right {
        align-items: stretch;
        justify-content: flex-start;
      }

      .field.signal-page-size-field {
        max-width: none;
      }

      .skeleton-panel--hero,
      .skeleton-panel--wide {
        grid-column: auto;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
      }
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

<div id="errorBanner" class="error-banner hidden" role="alert"></div>

<div class="shell">
  <header class="topbar panel">
    <div class="topbar-main">
      <div class="brand">
        <div class="brand-kicker">Kronos Trading Terminal</div>
        <h1>Gold Signal Command Center <span id="titlePrice" class="title-price">__DEFAULT_SYMBOL__ --</span></h1>
        <p>Decision-first live analysis with market structure, AI support, execution risk, and pipeline health in one scan.</p>
        <div class="status-strip" id="heroMeta">
          <span class="chip info">Waiting for live snapshot</span>
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
          <div class="meta-label">Last Update</div>
          <div class="meta-value" id="lastUpdateStatus">Awaiting first snapshot</div>
          <div class="meta-note">Display timezone: Asia/Amman</div>
        </article>
        <article class="meta-card">
          <div class="meta-label">Control Status</div>
          <div class="meta-value"><span id="controlBadge" class="chip info">Ready</span></div>
          <div class="meta-note">Refresh and prediction actions stay on the live backend routes.</div>
        </article>
      </div>
    </div>

    <div class="command-ribbon" aria-label="Live command bar">
      <label class="field command-field">Instrument
        <input id="market" value="__DEFAULT_SYMBOL__" autocomplete="off">
      </label>
      <label class="field command-field">Timeframe
        <select id="resolution">
          <option>MINUTE</option>
          <option selected>MINUTE_5</option>
          <option>MINUTE_15</option>
          <option>MINUTE_30</option>
          <option>HOUR</option>
        </select>
      </label>
      <label class="field command-field">Auto Refresh
        <select id="autoRefresh">
          <option value="0">Off</option>
          <option value="5" selected>5 sec</option>
          <option value="10">10 sec</option>
          <option value="30">30 sec</option>
        </select>
      </label>
      <label class="field command-field">Prediction Length
        <input id="predLen" type="number" value="12" min="1" max="120">
      </label>
      <div class="command-actions">
        <button id="refresh" class="btn-alt">Refresh Snapshot</button>
        <button id="predict" class="btn-primary">Run Prediction</button>
      </div>
    </div>
  </header>

  <section class="control-board panel" aria-label="Prediction controls">
    <div class="control-head">
      <div>
        <h2>Advanced Control Dock</h2>
        <div class="muted">Secondary parameters, repair toggles, and validation actions stay available without crowding the live command bar.</div>
      </div>
      <span class="chip info">Frontend-only redesign</span>
    </div>

    <div class="control-grid">
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
    </div>

    <div class="toggle-row">
      <label class="toggle-card"><span>Repair OHLC</span><input id="repairOhlc" type="checkbox" checked></label>
      <label class="toggle-card"><span>Auto Predict on Candle Close</span><input id="autoPredict" type="checkbox" checked></label>
    </div>

    <div class="actions">
      <button id="fetchActual" class="btn-warn">Fetch Actuals</button>
      <button id="validateActual" class="btn-warn">Validate Actuals</button>
      <button id="runBaselines" class="btn-alt">Run Baselines</button>
    </div>
  </section>

  <section id="modelStatusPanel" class="model-status-panel panel" aria-label="Model version and promotion progress"></section>

  <section id="summaryCards" class="terminal-summary" aria-label="Decision and signal intelligence">
    <div class="summary-skeleton">
      <div class="skeleton-panel skeleton-panel--hero"></div>
      <div class="skeleton-panel"></div>
      <div class="skeleton-panel"></div>
      <div class="skeleton-panel"></div>
    </div>
  </section>

  <section class="chart-grid">
    <article class="chart-panel panel">
      <div class="panel-head">
        <div>
          <h3>Signal Price Tape</h3>
          <p>Read the full tape fast: history, projected path, and the actual close path inside the live forecast window.</p>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="closeChart" width="1200" height="360" role="img" aria-label="Forecast versus actual close chart"></canvas></div>
    </article>

    <article class="chart-panel panel">
      <div class="panel-head">
        <div>
          <h3>Market Structure Canvas</h3>
          <p>Historical candles stay on the left and forecast candles stay on the right for structure, bias, and transition checks.</p>
        </div>
      </div>
      <div class="chart-wrap"><canvas id="candleChart" width="1200" height="360" role="img" aria-label="Historical and forecast candlestick chart"></canvas></div>
    </article>
  </section>

  <nav class="tabs" aria-label="Dashboard sections">
    <button class="tab active" data-tab="overview">Command Center</button>
    <button class="tab" data-tab="validation">Validation</button>
    <button class="tab" data-tab="modelPerformance">Performance</button>
    <button class="tab" data-tab="aiStack">AI Support</button>
    <button class="tab" data-tab="risk">Risk Gate</button>
    <button class="tab" data-tab="trades">Execution</button>
    <button class="tab" data-tab="baselines">Baselines</button>
    <button class="tab" data-tab="history">History</button>
    <button class="tab" data-tab="files">Artifacts</button>
    <button class="tab" data-tab="logs">Console</button>
    <button class="tab" data-tab="report">Report</button>
  </nav>

  <section id="overview" class="details-panel panel tabPanel">
    <div class="section-skeleton-grid">
      <div class="skeleton-panel skeleton-panel--wide"></div>
      <div class="skeleton-panel"></div>
      <div class="skeleton-panel"></div>
    </div>
  </section>
  <section id="validation" class="details-panel panel tabPanel hidden"></section>
  <section id="modelPerformance" class="details-panel panel tabPanel hidden"></section>
  <section id="aiStack" class="details-panel panel tabPanel hidden"></section>
  <section id="risk" class="details-panel panel tabPanel hidden"></section>
  <section id="trades" class="details-panel panel tabPanel hidden"></section>
  <section id="baselines" class="details-panel panel tabPanel hidden"></section>
  <section id="history" class="details-panel panel tabPanel hidden"></section>
  <section id="files" class="details-panel panel tabPanel hidden"></section>
  <section id="logs" class="details-panel panel tabPanel hidden">
    <div class="panel-head"><h2>Execution Logs</h2><span class="chip info">Action output</span></div>
    <pre id="actionLog">No actions run in this browser session.</pre>
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
let sparklineIdCounter = 0;
let latestModelPerformance = null;
let latestAiStack = {
  forecasts: { runs: [], forecasts: [] },
  ensemble: { rows: [] },
  regime: { rows: [] },
  scorer: { rows: [] },
  validation: { rows: [] },
};
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
  dateFrom: '',
  dateTo: '',
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
  'tradeDateFromFilter',
  'tradeDateToFilter',
  'tradeStatusFilter',
  'tradeOutcomeFilter',
  'tradeSideFilter',
  'tradeSignalFilter',
  'tradeTransactionFilter',
]);

const TRADE_FILTER_AUTO_APPLY_IDS = new Set([
  'tradeLifecycleFilter',
  'tradeDateFromFilter',
  'tradeDateToFilter',
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
  if (['OK', 'VALIDATED', 'WIN', 'GOOD_HOLD', 'PROMISING', 'LONG', 'UP', 'BUY', 'APPROVED', 'PROMOTED', 'OPEN', 'COMPLETED', 'ACTIVE', 'ALLOW', 'SUPPORT', 'FRESH', 'ONLINE'].includes(text)) return 'good';
  if (['PENDING', 'PARTIAL', 'HOLD', 'NO_TRADE', 'NO TRADE', 'EXPIRED', 'AMBIGUOUS', 'NEEDS_MORE_SAMPLES', 'FLAT', 'STALE', 'PENDING_REVIEW', 'SKIP', 'SKIPPED', 'QUEUED', 'QUEUE', 'PROCESSING', 'SUBMITTED', 'CLOSE_REQUESTED', 'NEUTRAL'].includes(text)) return 'warn';
  if (['ERROR', 'LOSS', 'MISSED_MOVE', 'WEAK', 'NOT_TRADABLE', 'SHORT', 'DOWN', 'SELL', 'NOT_READY', 'FAILED', 'REJECTED', 'VALIDATION_FAILED', 'CLOSE_FAILED', 'BLOCK', 'AGAINST', 'OFFLINE'].includes(text)) return 'bad';
  return 'info';
}

function chip(value, extra = '') {
  return `<span class="chip ${statusClass(value)} ${extra}">${escapeHtml(value ?? 'n/a')}</span>`;
}

function kpi(label, value, sub = '') {
  return `<article class="kpi"><div class="kpi-label">${escapeHtml(label)}</div><div class="kpi-value">${escapeHtml(value ?? 'n/a')}</div>${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function displayValue(value, digits = 4) {
  if (value === null || value === undefined || value === '') return 'n/a';
  if (typeof value === 'number') return Number.isFinite(value) ? fmtNumber(value, digits) : 'n/a';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function metricRows(rows) {
  return rows.map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(displayValue(value))}</td></tr>`).join('');
}

function stringifyUiValue(value, fallback = '') {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function responseMessage(data, fallback = 'Unexpected response') {
  const direct = data?.error?.message || data?.message || data?.detail || data?.error;
  if (typeof direct === 'string' && direct.trim()) return direct.trim();
  if (direct !== null && direct !== undefined) {
    const serialized = stringifyUiValue(direct, '');
    if (serialized) return serialized;
  }
  return fallback;
}

async function parseJsonResponse(res) {
  const text = await res.text();
  if (!text || !text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    const endpoint = res.url ? new URL(res.url).pathname : 'endpoint';
    throw new Error(`${endpoint} returned invalid JSON`);
  }
}

function setLogText(value) {
  const logEl = $('actionLog') || $('auditLog');
  if (!logEl) return;
  logEl.textContent = stringifyUiValue(value, '');
}

function normalizeDecisionSignal(value) {
  const text = String(value || '').trim().toUpperCase();
  if (['BUY', 'LONG', 'UP'].includes(text)) return 'BUY';
  if (['SELL', 'SHORT', 'DOWN'].includes(text)) return 'SELL';
  if (['HOLD', 'FLAT', 'NO_TRADE', 'NO TRADE', 'NEUTRAL'].includes(text)) return 'NO_TRADE';
  return text || 'NO_TRADE';
}

function firstFinite(...values) {
  for (const value of values) {
    const parsed = toFiniteNumber(value);
    if (parsed !== null) return parsed;
  }
  return null;
}

function scorePercent(value, fraction = true) {
  const parsed = toFiniteNumber(value);
  if (parsed === null) return null;
  const normalized = fraction && parsed <= 1 ? parsed * 100 : parsed;
  return Math.max(0, Math.min(100, normalized));
}

function toneForPercent(value, options = {}) {
  const { inverse = false } = options;
  const pct = scorePercent(value, false);
  if (pct === null) return 'info';
  if (inverse) {
    if (pct <= 35) return 'good';
    if (pct <= 65) return 'warn';
    return 'bad';
  }
  if (pct >= 70) return 'good';
  if (pct >= 45) return 'warn';
  return 'bad';
}

function percentText(value, digits = 1) {
  const pct = scorePercent(value, false);
  return pct === null ? 'N/A' : `${fmtNumber(pct, digits)}%`;
}

function formatPrice(value, digits = 2) {
  return value === null || value === undefined ? 'N/A' : fmtNumber(value, digits);
}

function formatPercentFromFraction(value, digits = 2) {
  const parsed = toFiniteNumber(value);
  return parsed === null ? 'N/A' : (parsed <= 1 ? pct01(parsed, digits) : `${fmtNumber(parsed, digits)}%`);
}

function relativeMinutesFromNow(value) {
  const ts = parseTs(value);
  if (!ts) return null;
  return (Date.now() - ts.getTime()) / 60000;
}

function freshnessState(value) {
  const mins = relativeMinutesFromNow(value);
  if (mins === null) return { label: 'Awaiting data', tone: 'info' };
  if (mins <= 1.5) return { label: 'Fresh', tone: 'good' };
  if (mins <= 5) return { label: `${fmtNumber(mins, 1)} min delayed`, tone: 'warn' };
  return { label: `${fmtNumber(mins, 1)} min stale`, tone: 'bad' };
}

function riskRewardRatio(entry, target, stop) {
  const entryPrice = toFiniteNumber(entry);
  const targetPrice = toFiniteNumber(target);
  const stopPrice = toFiniteNumber(stop);
  if (entryPrice === null || targetPrice === null || stopPrice === null) return null;
  const risk = Math.abs(entryPrice - stopPrice);
  const reward = Math.abs(targetPrice - entryPrice);
  if (risk <= 0) return null;
  return reward / risk;
}

function toneClassForDecision(value) {
  const normalized = normalizeDecisionSignal(value);
  if (normalized === 'BUY') return 'good';
  if (normalized === 'SELL') return 'bad';
  return 'warn';
}

function scoreRing(label, value, meta = '', tone = null) {
  const pct = scorePercent(value, false);
  const resolvedTone = tone || toneForPercent(pct);
  return `<article class="score-ring">
    <div class="score-ring-body" style="--pct:${pct === null ? 0 : pct}; --ring-color: var(--${resolvedTone === 'good' ? 'bull' : resolvedTone === 'bad' ? 'bear' : resolvedTone === 'warn' ? 'warn' : 'accent'});">
      <div class="score-ring-value">${pct === null ? 'N/A' : `${fmtNumber(pct, 0)}%`}</div>
      <div class="score-ring-meta">${escapeHtml(meta || 'No score available')}</div>
    </div>
    <div class="score-ring-label">${escapeHtml(label)}</div>
  </article>`;
}

function scoreBar(label, value, meta = '', tone = null) {
  const pct = scorePercent(value, false);
  const resolvedTone = tone || toneForPercent(pct);
  return `<article class="score-bar">
    <div class="score-bar-head">
      <span>${escapeHtml(label)}</span>
      <span>${pct === null ? 'N/A' : `${fmtNumber(pct, 1)}%`}</span>
    </div>
    <div class="score-track"><span class="score-fill ${resolvedTone}" style="--score-pct:${pct === null ? 0 : pct}"></span></div>
    <div class="score-inline-note">${escapeHtml(meta || 'No supporting score')}</div>
  </article>`;
}

function miniStat(label, value, sub = '') {
  return `<article class="mini-stat"><div class="mini-stat-label">${escapeHtml(label)}</div><div class="mini-stat-value">${escapeHtml(value ?? 'N/A')}</div>${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function quoteCell(label, value, sub = '') {
  return `<article class="quote-cell"><div class="quote-label">${escapeHtml(label)}</div><div class="quote-value">${escapeHtml(value ?? 'N/A')}</div>${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function decisionCell(label, value, tone = 'info', sub = '') {
  return `<article class="decision-level"><div class="decision-label">${escapeHtml(label)}</div><div class="decision-value ${tone}">${escapeHtml(value ?? 'N/A')}</div>${sub ? `<div class="kpi-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function riskItem(label, value, sub = '', tone = 'info') {
  return `<article class="risk-item"><div class="risk-label">${escapeHtml(label)}</div><div class="risk-value ${tone}">${escapeHtml(value ?? 'N/A')}</div>${sub ? `<div class="risk-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function healthItem(label, value, sub = '', tone = 'info') {
  return `<article class="health-item"><div class="health-name">${escapeHtml(label)}</div><div class="health-state ${tone}">${escapeHtml(value ?? 'N/A')}</div>${sub ? `<div class="health-sub">${escapeHtml(sub)}</div>` : ''}</article>`;
}

function emptyState(title, text) {
  return `<div class="empty"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(text)}</span></div>`;
}

function sparklineSvg(values, lineColor = '#c0a14e') {
  const numeric = values.map(value => toFiniteNumber(value)).filter(value => value !== null);
  if (!numeric.length) {
    return `<div class="mini-chart-wrap">${emptyState('No trend data', 'Confidence and outcome points will appear after live runs are loaded.')}</div>`;
  }
  const width = 320;
  const height = 120;
  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  const range = Math.max(max - min, 1e-6);
  const step = numeric.length > 1 ? width / (numeric.length - 1) : width;
  const points = numeric.map((value, index) => `${(index * step).toFixed(2)},${(height - ((value - min) / range) * (height - 24) - 12).toFixed(2)}`).join(' ');
  const areaPoints = `0,${height - 8} ${points} ${width},${height - 8}`;
  const gradientId = `sparkArea_${++sparklineIdCounter}`;
  return `<div class="mini-chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Trend chart">
    <defs>
      <linearGradient id="${gradientId}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="${lineColor}" stop-opacity="0.35"></stop>
        <stop offset="100%" stop-color="${lineColor}" stop-opacity="0"></stop>
      </linearGradient>
    </defs>
    <polyline fill="url(#${gradientId})" stroke="none" points="${areaPoints}"></polyline>
    <polyline fill="none" stroke="${lineColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${points}"></polyline>
  </svg></div>`;
}

function distributionRows(items) {
  const total = items.reduce((sum, item) => sum + Number(item.value || 0), 0);
  if (!total) return emptyState('No distribution data', 'Outcome counts will appear after signals and trades accumulate.');
  return `<div class="distribution-row">${items.map(item => {
    const pct = total ? (Number(item.value || 0) / total) * 100 : 0;
    return `<div class="distribution-item">
      <div class="score-bar-head"><span>${escapeHtml(item.label)}</span><span>${fmtCount(item.value || 0)}</span></div>
      <div class="distribution-bar ${escapeHtml(item.tone || 'info')}" style="--dist-pct:${pct}"><span></span></div>
    </div>`;
  }).join('')}</div>`;
}

function signalHistoryCard(row) {
  const validationSummary = aiJsonObject(row.validation_summary || {});
  const decision = normalizeDecisionSignal(row.signal || row.direction || validationSummary.final_signal || 'NO_TRADE');
  const decisionTone = toneClassForDecision(decision);
  const confidence = scorePercent(row.confidence, true);
  return `<article class="signal-history-card">
    <div class="signal-history-head">
      <div>
        <div class="model-support-name">${escapeHtml(row.signal_id || row.run_id || 'Signal')}</div>
        <div class="signal-history-meta">${escapeHtml(fmtDate(row.timestamp_utc || row.created_at || row.updated_at))}</div>
      </div>
      ${chip(decision)}
    </div>
    <div class="signal-history-levels">
      <div><strong class="decision-value ${decisionTone}">${escapeHtml(row.status || row.signal_status || 'PENDING')}</strong></div>
      <div class="signal-history-meta">Entry ${formatPrice(firstFinite(row.entry_price, row.shadow_entry_price))} · TP ${formatPrice(firstFinite(row.tp_price, row.shadow_tp_price))} · SL ${formatPrice(firstFinite(row.sl_price, row.shadow_sl_price))}</div>
      <div class="signal-history-meta">Confidence ${confidence === null ? 'N/A' : `${fmtNumber(confidence, 1)}%`} · Validation ${escapeHtml(validationSummary.final_signal || row.validation_status || 'N/A')}</div>
    </div>
  </article>`;
}

function supportAlignmentStatus(decision, direction, fallbackStatus = '') {
  const normalizedDecision = normalizeDecisionSignal(decision);
  const normalizedDirection = normalizeDecisionSignal(direction);
  const fallback = String(fallbackStatus || '').trim().toUpperCase();
  if (['FAILED', 'ERROR'].includes(fallback)) return 'FAILED';
  if (['PENDING', 'SKIPPED'].includes(fallback)) return fallback;
  if (normalizedDecision === 'NO_TRADE') return 'NEUTRAL';
  if (normalizedDirection === normalizedDecision) return 'SUPPORT';
  if (['BUY', 'SELL'].includes(normalizedDirection) && normalizedDirection !== normalizedDecision) return 'AGAINST';
  return 'NEUTRAL';
}

function modelSupportCard({ name, status, direction, supportValue, confidence, detail }) {
  return `<article class="model-support-card">
    <div class="model-support-head">
      <div>
        <div class="model-support-name">${escapeHtml(name || 'Model')}</div>
        <div class="model-support-detail">${escapeHtml(detail || 'No recent model update')}</div>
      </div>
      ${chip(status || 'NEUTRAL')}
    </div>
    <div class="model-support-body">
      ${miniStat('Direction', normalizeDecisionSignal(direction || 'NO_TRADE'), '')}
      ${miniStat('Support Value', supportValue ?? 'N/A', '')}
      ${miniStat('Confidence', confidence ?? 'N/A', '')}
    </div>
  </article>`;
}

function setErrorBanner(message = '') {
  const banner = $('errorBanner');
  if (!banner) return;
  if (!message) {
    banner.classList.add('hidden');
    banner.textContent = '';
    return;
  }
  banner.textContent = message;
  banner.classList.remove('hidden');
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

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function drawEmptyChart(ctx, w, h, text) {
  ctx.fillStyle = cssVar('--muted', '#9ca7b6');
  ctx.font = '14px Bahnschrift';
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

  ctx.strokeStyle = 'rgba(192,161,78,0.12)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const gy = pad + i * ((h - pad * 2) / 4);
    ctx.beginPath();
    ctx.moveTo(pad, gy);
    ctx.lineTo(w - pad, gy);
    ctx.stroke();
  }

  ctx.fillStyle = cssVar('--muted', '#9ca7b6');
  ctx.font = '12px Bahnschrift';
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

  drawSeries(history, cssVar('--neutral', '#43b0d8'), 2.4);
  drawSeries(actualWindow, cssVar('--bull', '#38c172'), 2.1, true);
  drawSeries(forecast, cssVar('--accent', '#c0a14e'), 2.8);

  if (forecastStart) {
    const vx = x(forecastStart.getTime());
    ctx.strokeStyle = cssVar('--accent', '#c0a14e');
    ctx.setLineDash([7, 6]);
    ctx.beginPath();
    ctx.moveTo(vx, pad);
    ctx.lineTo(vx, h - pad);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.fillStyle = cssVar('--text-2', '#e8dfc5');
  ctx.font = '12px Bahnschrift';
  ctx.fillText('Input history', pad, 22);
  ctx.fillStyle = cssVar('--accent', '#c0a14e');
  ctx.fillText('Forecast', pad + 94, 22);
  ctx.fillStyle = cssVar('--bull', '#38c172');
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

  ctx.strokeStyle = 'rgba(192,161,78,0.12)';
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
    const color = r.kind === 'forecast'
      ? (up ? cssVar('--accent', '#c0a14e') : cssVar('--bear', '#ff6b57'))
      : (up ? cssVar('--bull', '#38c172') : cssVar('--neutral', '#43b0d8'));
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
    ctx.strokeStyle = cssVar('--accent', '#c0a14e');
    ctx.setLineDash([7, 6]);
    ctx.beginPath();
    ctx.moveTo(splitX, pad);
    ctx.lineTo(splitX, h - pad);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.fillStyle = cssVar('--text-2', '#e8dfc5');
  ctx.font = '12px Bahnschrift';
  ctx.fillText('Input candles', pad, 22);
  ctx.fillStyle = cssVar('--accent', '#c0a14e');
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
        <p>Running ${escapeHtml(modelVersion)} for ${escapeHtml(autoStatus.symbol || metadata.epic || '__DEFAULT_SYMBOL__')} ${escapeHtml(autoStatus.resolution || metadata.resolution || 'MINUTE_5')}</p>
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
  params.set('symbol', $('market').value || '__DEFAULT_SYMBOL__');
  params.set('resolution', $('resolution').value || 'MINUTE');
  return params.toString();
}

function resolutionToAiTf(resolution) {
  const map = {
    MINUTE: '1m',
    MINUTE_5: '5m',
    MINUTE_15: '15m',
    MINUTE_30: '30m',
    HOUR: '1h',
  };
  return map[resolution] || resolution || '5m';
}

function currentAiQuery(limit = 50) {
  const params = new URLSearchParams(currentStatusQuery());
  params.set('tf', resolutionToAiTf($('resolution').value || 'MINUTE_5'));
  params.set('limit', String(limit));
  return params.toString();
}

function actionContextPayload(extra = {}) {
  return {
    run_id: selectedRunId || '',
    symbol: $('market').value || '__DEFAULT_SYMBOL__',
    resolution: $('resolution').value || 'MINUTE_5',
    ...extra,
  };
}

function getSignalQuery(page = 1) {
  const params = new URLSearchParams();
  params.set('symbol', $('market').value || '__DEFAULT_SYMBOL__');
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
    latestSignals = await parseJsonResponse(res);
    if (!res.ok) throw new Error(responseMessage(latestSignals, `Signals HTTP ${res.status}`));
    setErrorBanner('');
    signalPage = latestSignals.pagination?.page || page;
    if (renderUi && (forceRender || !isSignalsFilterInteracting())) {
      renderOverview({ force: forceRender, background: false });
    }
  } catch (err) {
    setErrorBanner(`Signals refresh failed: ${err.message}`);
    showToast(`Signals refresh failed: ${err.message}`);
  }
}

async function fetchAiEndpoint(path, fallback) {
  try {
    const res = await fetch(`${path}?${currentAiQuery()}`, { cache: 'no-store' });
    const data = await parseJsonResponse(res);
    if (!res.ok) {
      return { ...fallback, warning: responseMessage(data, `HTTP ${res.status}`) };
    }
    return data;
  } catch (err) {
    return { ...fallback, warning: err.message };
  }
}

async function refreshAiStack() {
  const [forecasts, ensemble, regime, scorer, validation] = await Promise.all([
    fetchAiEndpoint('/api/forecasts', { runs: [], forecasts: [] }),
    fetchAiEndpoint('/api/ensemble', { rows: [] }),
    fetchAiEndpoint('/api/regime', { rows: [] }),
    fetchAiEndpoint('/api/scorer', { rows: [] }),
    fetchAiEndpoint('/api/forecast-validation', { rows: [] }),
  ]);
  latestAiStack = { forecasts, ensemble, regime, scorer, validation };
}

function renderOverview(options = {}) {
  const { force = false, background = false } = options;
  const hs = latest.human_summary || {};
  const v = latest.validation || {};
  const sv = latest.signal_validation || {};
  const db = latest.prediction_db || {};
  const pg = latest.postgres_snapshot || {};
  const trust = latest.dashboard_trust || {};
  const execPerf = trust.executed_trade_performance || {};
  const warnings = latest.status_warnings || [];
  const workerStates = pg.worker_statuses || {};
  const liveQuote = pg.live_quote || latest.live_quote || {};
  const outcomes = (pg.outcomes || []).map(r => `${escapeHtml(r.status)}: ${escapeHtml(r.count)}`).join(' | ') || 'No outcomes yet';
  const rows = latestSignals.rows || [];
  const pag = latestSignals.pagination || { page: 1, total: 0, total_pages: 1, has_prev: false, has_next: false };
  const pageButtons = buildSignalPaginationButtons(pag.page || 1, pag.total_pages || 1);
  const latestRow = rows[0] || (pg.signals || [])[0] || {};
  const validationSummary = aiJsonObject(latestRow.validation_summary || {});
  const ensemble = aiRows(latestAiStack.ensemble)[0] || {};
  const regime = aiRows(latestAiStack.regime)[0] || {};
  const scorer = aiRows(latestAiStack.scorer)[0] || {};
  const scorerFeatures = aiJsonObject(scorer.features_json || scorer.features);
  const finalDecision = aiJsonObject(scorerFeatures.final_decision || {});
  const decision = normalizeDecisionSignal(sv.final_signal || hs.signal || latestRow.signal || scorer.decision || finalDecision.decision || 'NO_TRADE');
  const decisionTone = toneClassForDecision(decision);
  const latestPrice = resolveLatestPrice(latest);
  const latestPriceTime = resolveLatestPriceTime(latest);
  const freshness = freshnessState(latestPriceTime);
  const bid = firstFinite(liveQuote.bid);
  const ask = firstFinite(liveQuote.ask);
  const spreadAbs = firstFinite(liveQuote.spread, bid !== null && ask !== null ? ask - bid : null, regime.spread);
  const entryPrice = firstFinite(hs.entry_price, latestRow.entry_price, latestRow.recommended_entry);
  const stopPrice = firstFinite(hs.sl_price, latestRow.sl_price, latestRow.stop_loss);
  const tp1Price = firstFinite(hs.tp_price, latestRow.tp_price, latestRow.take_profit);
  const tp2Price = firstFinite(hs.tp2_price, latestRow.tp2_price);
  const rewardRisk = riskRewardRatio(entryPrice, tp1Price, stopPrice);
  const strategyScore = scorePercent(sv.total_score ?? hs.confidence_pct, true);
  const aiSupportScore = scorePercent(ensemble.agreement_score, true);
  const finalScore = scorePercent(scorer.probability_win ?? hs.confidence_pct, true);
  const riskScore = scorer.probability_loss === null || scorer.probability_loss === undefined
    ? null
    : Math.max(0, 100 - (scorePercent(scorer.probability_loss, true) || 0));
  const riskScoreTone = toneForPercent(riskScore, { inverse: false });
  const trendBias = normalizeDecisionSignal(ensemble.ensemble_direction || v.forecast_direction || latestRow.direction || 'NO_TRADE');
  const modelLabel = scorer.scorer_model || latest.auto_finetune?.current_model_label || latest.metadata?.model_name || 'N/A';
  const blockReason = sv.block_reason || validationSummary.block_reason || latestRow.execution_block_reason || '';
  const reasonNarrative = [
    ...(Array.isArray(sv.reason_details) ? sv.reason_details : []),
    finalDecision.reason,
    validationSummary.reason,
    blockReason ? `Blocked by ${blockReason}` : '',
  ].filter(Boolean)[0] || 'Waiting for a fully scored snapshot to attach a richer decision narrative.';
  const confidenceValues = rows.slice(0, 12).reverse().map(row => scorePercent(row.confidence, true)).filter(value => value !== null);
  const aggregatedWins = rows.reduce((sum, row) => sum + Number(row.outcomes_wins || row.wins || 0), 0);
  const aggregatedLosses = rows.reduce((sum, row) => sum + Number(row.outcomes_losses || row.losses || 0), 0);
  const aggregatedPending = rows.reduce((sum, row) => sum + Number(row.outcomes_pending || row.pending || 0), 0);
  const buyCount = rows.filter(row => normalizeDecisionSignal(row.signal || row.direction) === 'BUY').length;
  const sellCount = rows.filter(row => normalizeDecisionSignal(row.signal || row.direction) === 'SELL').length;
  const workerCards = Object.entries(workerStates)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([name, state]) => {
      const stateText = String(state?.status || 'MISSING').toUpperCase();
      return healthItem(name, stateText, state?.updated_at ? `Updated ${fmtDate(state.updated_at)}` : 'No heartbeat yet', statusClass(stateText));
    })
    .join('');

  const buildSupportCard = (label, aliases) => {
    const run = aiFindRun(aliases);
    const point = aiFindForecast(aliases);
    const direction = point.predicted_direction || run.raw_json?.direction || '';
    const status = supportAlignmentStatus(decision, direction, run.status || (point.id ? 'READY' : 'PENDING'));
    const supportValue = point.predicted_return === null || point.predicted_return === undefined
      ? 'N/A'
      : formatPercentFromFraction(point.predicted_return, 2);
    const confidenceText = point.confidence === null || point.confidence === undefined
      ? 'N/A'
      : formatPercentFromFraction(point.confidence, 1);
    const detail = run.error_message || fmtDate(point.forecast_for_ts || run.created_at);
    return modelSupportCard({
      name: label,
      status,
      direction: direction || 'N/A',
      supportValue,
      confidence: confidenceText,
      detail: detail || 'No recent model output',
    });
  };

  const garchStatus = (() => {
    const riskState = String(regime.risk_state || '').toUpperCase();
    if (!riskState) return 'NEUTRAL';
    if (['LOW', 'LOW_RISK', 'NORMAL'].includes(riskState)) return 'SUPPORT';
    if (['HIGH', 'HIGH_RISK', 'EXTREME', 'NO_TRADE'].includes(riskState)) return 'AGAINST';
    return 'NEUTRAL';
  })();

  const modelSupportCards = [
    buildSupportCard('Kronos', ['kronos']),
    buildSupportCard('Chronos-2', ['chronos2', 'chronos-2']),
    buildSupportCard('TimesFM', ['timesfm', 'times-fm']),
    buildSupportCard('Moirai', ['moirai']),
    buildSupportCard('PatchTST', ['patchtst', 'patch-tst']),
    buildSupportCard('iTransformer', ['itransformer', 'i-transformer']),
    modelSupportCard({
      name: 'GARCH',
      status: garchStatus,
      direction: regime.regime || regime.risk_state || 'N/A',
      supportValue: regime.garch_volatility === null || regime.garch_volatility === undefined ? 'N/A' : fmtNumber(regime.garch_volatility, 4),
      confidence: regime.realized_volatility === null || regime.realized_volatility === undefined ? 'N/A' : fmtNumber(regime.realized_volatility, 4),
      detail: regime.risk_state ? `Risk state ${regime.risk_state}` : 'No regime volatility snapshot',
    }),
  ].join('');

  const badgeOrMuted = value => {
    const text = String(value || '').trim();
    return text ? chip(text) : '<span class="muted">n/a</span>';
  };

  const bodyRows = rows.length
    ? rows.map(r => {
      const validatedCount = Number(r.outcomes_wins || 0) + Number(r.outcomes_losses || 0);
      const totalCount = validatedCount + Number(r.outcomes_pending || 0);
      const runBadge = badgeOrMuted(r.run_status || '');
      const activeDecision = badgeOrMuted(r.signal);
      const activeOutcome = badgeOrMuted(r.status);
      const activeStatus = badgeOrMuted(r.status_raw || r.status);
      const rowValidationSummary = aiJsonObject(r.validation_summary || {});
      const validationFinalSignal = String(rowValidationSummary.final_signal || r.validation_status || '').trim();
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
        if (rowValidationSummary.blocked) {
          modelNoteParts.push(`validation ${validationFinalSignal} (${rowValidationSummary.block_reason || 'UNKNOWN'})`);
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

  const statsCards = [
    kpi('Executed Win Rate', execPerf.executed_trade_win_rate_pct === null || execPerf.executed_trade_win_rate_pct === undefined ? 'N/A' : `${fmtNumber(execPerf.executed_trade_win_rate_pct, 2)}%`, `${fmtCount(execPerf.closed_trade_count || 0)} closed trades`),
    kpi('Expectancy', execPerf.expectancy === null || execPerf.expectancy === undefined ? 'N/A' : fmtNumber(execPerf.expectancy, 4), 'Average net P/L per finalized trade'),
    kpi('Max Drawdown', execPerf.max_drawdown === null || execPerf.max_drawdown === undefined ? 'N/A' : fmtNumber(execPerf.max_drawdown, 4), 'From finalized trade sequence'),
    kpi('Directional Accuracy', latestModelPerformance?.active_model?.direction_accuracy_pct === null || latestModelPerformance?.active_model?.direction_accuracy_pct === undefined ? 'N/A' : `${fmtNumber(latestModelPerformance.active_model.direction_accuracy_pct, 2)}%`, `${fmtCount(latestModelPerformance?.active_model?.samples || 0)} active samples`),
    kpi('Buy vs Sell Load', `${fmtCount(buyCount)} / ${fmtCount(sellCount)}`, 'Recent BUY / SELL signals loaded'),
    kpi('Signal Backlog', `${fmtCount(aggregatedPending)}`, `${fmtCount(aggregatedWins)} wins · ${fmtCount(aggregatedLosses)} losses`),
  ].join('');

  const healthCards = [
    healthItem('PostgreSQL', pg.postgres?.ok ? 'ONLINE' : 'OFFLINE', pg.postgres?.ok ? 'Persistence responding' : 'Status endpoint reported offline', pg.postgres?.ok ? 'good' : 'bad'),
    healthItem('Price Feed', freshness.label.toUpperCase(), latestPriceTime ? fmtDate(latestPriceTime) : 'Awaiting latest candle', freshness.tone),
    healthItem('Websocket', hs.websocket_stale_alert ? 'STALE' : 'FRESH', hs.live_source || 'No live source', hs.websocket_stale_alert ? 'bad' : 'good'),
    healthItem('Latest Prediction', hs.last_prediction_time ? fmtDate(hs.last_prediction_time) : 'N/A', hs.last_prediction_run_id || 'No run id', hs.last_prediction_time ? 'info' : 'warn'),
    healthItem('Warnings', warnings.length ? `${fmtCount(warnings.length)} open` : 'CLEAR', warnings.length ? 'Review status warnings' : 'No status warnings', warnings.length ? 'warn' : 'good'),
    healthItem('Live Source', hs.live_source || 'N/A', db.pending === null || db.pending === undefined ? 'Pending candles N/A' : `${fmtCount(db.pending)} candles pending`, hs.live_source ? 'info' : 'warn'),
  ].join('');

  const recentSignalsHtml = rows.length
    ? rows.slice(0, 6).map(signalHistoryCard).join('')
    : emptyState('No signals loaded', 'Run a prediction or widen the signal filters to populate recent signal history.');

  const summaryOverview = `
    <div class="overview-layout">
      ${warningHtml}

      <div class="overview-primary">
        <section class="section-card">
          <div class="section-kicker">Decision Snapshot</div>
          <div class="section-titlebar">
            <div>
              <h2 class="section-title">Latest Market Call</h2>
              <p class="section-sub">The latest signal, score stack, and trade levels rendered from the existing live backend snapshot.</p>
            </div>
            ${chip(decision)}
          </div>
          <div class="hero-note"><strong>Reason:</strong> ${escapeHtml(reasonNarrative)}</div>
          <div class="decision-levels" style="margin-top: 14px;">
            ${decisionCell('Signal', decision, decisionTone, `Status ${hs.signal_status || latestRow.status || 'PENDING'}`)}
            ${decisionCell('Regime', regime.regime || 'N/A', statusClass(regime.risk_state || regime.regime || 'info'), `Risk ${regime.risk_state || 'N/A'}`)}
            ${decisionCell('Trend Bias', trendBias, toneClassForDecision(trendBias), `Agreement ${ensemble.agreement_score === null || ensemble.agreement_score === undefined ? 'N/A' : pct01(ensemble.agreement_score)}`)}
            ${decisionCell('Strategy Type', modelLabel, 'info', 'Using current scorer/model label')}
            ${decisionCell('Blocked By', blockReason || 'None', blockReason ? 'bad' : 'good', blockReason ? 'Signal could not clear all gates' : 'No active hard block')}
            ${decisionCell('Confidence', hs.confidence_pct === null || hs.confidence_pct === undefined ? 'N/A' : `${fmtNumber(hs.confidence_pct, 2)}%`, toneForPercent(hs.confidence_pct, { inverse: false }), 'Model confidence from status snapshot')}
          </div>
        </section>

        <section class="section-card">
          <div class="section-kicker">Scoreboard</div>
          <div class="section-titlebar">
            <div>
              <h2 class="section-title">Strategy, AI, Risk, Final</h2>
              <p class="section-sub">Displayed from the current status, scorer, validation, and AI support payloads. Missing backend fields stay N/A.</p>
            </div>
            <span class="chip info">${escapeHtml(modelLabel)}</span>
          </div>
          <div class="ring-grid">
            ${scoreRing('Strategy Score', strategyScore, sv.total_score === null || sv.total_score === undefined ? 'Validation score unavailable' : 'Validation / candidate scoring', toneForPercent(strategyScore))}
            ${scoreRing('Final Score', finalScore, scorer.probability_win === null || scorer.probability_win === undefined ? 'Scorer probability unavailable' : 'Derived from win probability', toneForPercent(finalScore))}
          </div>
          <div class="score-breakdown">
            <div class="score-bar-list">
              ${scoreBar('Strategy Score', strategyScore, sv.total_score === null || sv.total_score === undefined ? 'No explicit validation score returned' : 'Latest validation total score')}
              ${scoreBar('AI Support Score', aiSupportScore, ensemble.agreement_score === null || ensemble.agreement_score === undefined ? 'No ensemble agreement returned' : 'Ensemble agreement / alignment')}
              ${scoreBar('Risk Score', riskScore, scorer.probability_loss === null || scorer.probability_loss === undefined ? 'Risk score unavailable from current payload' : 'Derived from inverse loss probability', riskScoreTone)}
              ${scoreBar('Final Score', finalScore, scorer.expected_return === null || scorer.expected_return === undefined ? 'Expected return unavailable' : `Expected return ${formatPercentFromFraction(scorer.expected_return, 2)}`)}
            </div>
          </div>
        </section>
      </div>

      <div class="overview-secondary">
        <section class="section-card">
          <div class="section-kicker">Statistics</div>
          <div class="section-titlebar">
            <div>
              <h2 class="section-title">Performance Readout</h2>
              <p class="section-sub">High-value execution and model stats, plus a recent confidence trend and outcome distribution.</p>
            </div>
            <span class="chip info">${fmtCount(aggregatedWins)}W / ${fmtCount(aggregatedLosses)}L / ${fmtCount(aggregatedPending)}P</span>
          </div>
          <div class="stats-grid">${statsCards}</div>
          <div class="section-titlebar" style="margin-top: 14px; margin-bottom: 8px;"><strong class="section-sub">Confidence Trend</strong><span class="chip info">Last ${fmtCount(confidenceValues.length)} points</span></div>
          ${sparklineSvg(confidenceValues, '#43b0d8')}
          <div class="section-titlebar" style="margin-top: 14px; margin-bottom: 8px;"><strong class="section-sub">Outcome Mix</strong><span class="chip info">Recent rows</span></div>
          ${distributionRows([
            { label: 'Wins', value: aggregatedWins, tone: 'good' },
            { label: 'Losses', value: aggregatedLosses, tone: 'bad' },
            { label: 'Pending', value: aggregatedPending, tone: 'warn' },
          ])}
        </section>

        <section class="section-card">
          <div class="section-kicker">Risk Management</div>
          <div class="section-titlebar">
            <div>
              <h2 class="section-title">Trade Gate Readout</h2>
              <p class="section-sub">Spread, volatility, stop distance, reward profile, and execution readiness for the current signal.</p>
            </div>
            ${chip(regime.risk_state || 'N/A')}
          </div>
          <div class="risk-grid">
            ${riskItem('Spread Status', spreadAbs === null ? 'N/A' : fmtNumber(spreadAbs, 4), v.movement_after_cost_warning ? 'Movement after cost warning is active' : 'No cost warning flagged', v.movement_after_cost_warning ? 'bad' : 'good')}
            ${riskItem('Volatility', regime.garch_volatility === null || regime.garch_volatility === undefined ? 'N/A' : fmtNumber(regime.garch_volatility, 4), regime.realized_volatility === null || regime.realized_volatility === undefined ? 'Realized vol N/A' : `Realized ${fmtNumber(regime.realized_volatility, 4)}`, statusClass(regime.risk_state || 'info'))}
            ${riskItem('Stop Distance', entryPrice === null || stopPrice === null ? 'N/A' : fmtNumber(Math.abs(entryPrice - stopPrice), 2), entryPrice === null || stopPrice === null ? 'No stop distance available' : `${fmtNumber((Math.abs(entryPrice - stopPrice) / Math.max(entryPrice, 1e-9)) * 100, 3)}% of entry`, 'info')}
            ${riskItem('Risk / Reward', rewardRisk === null ? 'N/A' : `${fmtNumber(rewardRisk, 2)} R`, rewardRisk === null ? 'TP1 or stop missing' : 'Based on current entry / TP1 / stop', rewardRisk !== null && rewardRisk >= 1.5 ? 'good' : rewardRisk !== null && rewardRisk >= 1 ? 'warn' : 'bad')}
            ${riskItem('Expected Move', v.max_abs_close_move_pct === null || v.max_abs_close_move_pct === undefined ? 'N/A' : `${fmtNumber(v.max_abs_close_move_pct, 3)}%`, 'From latest validation payload', v.max_abs_close_move_pct === null || v.max_abs_close_move_pct === undefined ? 'info' : 'good')}
            ${riskItem('Execution Health', latest.trade_execution?.ok ? 'READY' : 'LIMITED', latest.trade_execution?.ok ? 'Trade execution endpoint is reporting OK' : (latest.trade_execution?.error || 'Execution service unavailable'), latest.trade_execution?.ok ? 'good' : 'bad')}
          </div>
        </section>

        <section class="section-card">
          <div class="section-kicker">System Health</div>
          <div class="section-titlebar">
            <div>
              <h2 class="section-title">Pipeline Freshness</h2>
              <p class="section-sub">Runtime state, worker heartbeats, data freshness, and live feed health.</p>
            </div>
            ${chip(freshness.label)}
          </div>
          <div class="health-grid">${healthCards}${workerCards}</div>
        </section>
      </div>

      <section class="section-card">
        <div class="section-kicker">AI Support</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Model Alignment Matrix</h2>
            <p class="section-sub">Kronos, Chronos-2, TimesFM, Moirai, PatchTST, iTransformer, and GARCH shown as support, neutral, or against.</p>
          </div>
          ${chip(ensemble.ensemble_direction || 'N/A')}
        </div>
        <div class="model-support-grid">${modelSupportCards}</div>
      </section>

      <section class="section-card">
        <div class="section-kicker">Recent Signals</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Signal History Snapshot</h2>
            <p class="section-sub">A fast read on the latest runs before you drop into the full signal ledger.</p>
          </div>
          <span class="chip info">${fmtCount(rows.length)} loaded</span>
        </div>
        <div class="signal-history-grid">${recentSignalsHtml}</div>
      </section>

      <section class="section-card">
        <div class="section-kicker">Signal Ledger</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Filterable Run History</h2>
            <p class="section-sub">The original detailed signal table is preserved for audit, execution, and copy actions.</p>
          </div>
          <span class="chip info">${escapeHtml(String(pag.total || 0))} rows</span>
        </div>

        <div class="control-grid filter-grid--signals">
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

        <div class="actions filter-actions--signals">
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

        <div class="signal-table-footer" style="margin-top: 12px;">
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
        </div>
      </section>
    </div>`;

  if (!force && background) {
    const now = Date.now();
    if (now - lastOverviewRenderAtMs < OVERVIEW_BACKGROUND_RENDER_INTERVAL_MS) {
      return;
    }
  }

  if (!force && summaryOverview === lastOverviewHtml) {
    return;
  }

  $('overview').innerHTML = summaryOverview;
  lastOverviewHtml = summaryOverview;
  lastOverviewRenderAtMs = Date.now();
}

function renderValidation(data) {
  const v = data.validation || {};
  const source = data.validation_source || 'none';
  const sv = data.signal_validation || {};
  const trust = data.dashboard_trust || {};
  const forecastTrust = trust.forecast_quality || {};
  const signalTrust = trust.signal_quality || {};
  const inputTrust = trust.data_input_health || {};
  const latestState = trust.latest_state || {};
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
    ['Partial / final status', forecastTrust.partial_or_final || 'UNKNOWN'],
    ['Actual future horizon complete', forecastTrust.actual_future_horizon_complete],
    ['Quality', v.quality_status],
    ['Direction', v.forecast_direction || sv.forecast_direction || 'n/a'],
    ['Matched candles', v.matched_candles],
    ['Directional Forecast Hit Rate', forecastTrust.directional_forecast_hit_rate_pct === undefined || forecastTrust.directional_forecast_hit_rate_pct === null ? metricPendingLabel : `${fmtNumber(forecastTrust.directional_forecast_hit_rate_pct, 2)}%`],
    ['Per-horizon direction accuracy', v.direction_accuracy_pct === undefined || v.direction_accuracy_pct === null ? metricPendingLabel : `${fmtNumber(v.direction_accuracy_pct, 2)}%`],
    ['Directional hit-rate hint', accuracyHint],
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

  const inputHealthRows = [
    ['Latest prediction time', latestState.latest_prediction_time],
    ['Latest input candle time', latestState.latest_input_candle_time || inputTrust.latest_input_candle_time],
    ['Latest input complete', latestState.latest_input_complete],
    ['Missing candle count', inputTrust.missing_candle_count],
    ['Largest gap minutes', inputTrust.largest_gap_minutes],
    ['Source counts', inputTrust.source_counts || {}],
    ['Amount available', inputTrust.amount_available],
    ['Feature mode', inputTrust.feature_mode],
    ['Requested lookback', inputTrust.requested_lookback],
    ['Actual lookback used', inputTrust.actual_lookback || inputTrust.actual_rows_used],
    ['Max supported lookback', inputTrust.max_supported_lookback],
    ['Lookback honored', inputTrust.lookback_honored],
    ['Stale/unclosed warning', inputTrust.stale_or_unclosed_warning || 'none'],
  ];

  const horizonRows = (forecastTrust.per_horizon || data.horizon_metrics || []).length
    ? (forecastTrust.per_horizon || data.horizon_metrics || []).map(row => `<tr>
      <td>${escapeHtml(row.horizon_index || row.horizon || '')}</td>
      <td>${fmtCount(row.samples || row.sample_count || 0)}</td>
      <td>${row.directional_forecast_hit_rate_pct === null || row.directional_forecast_hit_rate_pct === undefined ? 'n/a' : `${fmtNumber(row.directional_forecast_hit_rate_pct, 2)}%`}</td>
      <td>${row.mae === null || row.mae === undefined ? 'n/a' : fmtNumber(row.mae)}</td>
      <td>${row.rmse === null || row.rmse === undefined ? 'n/a' : fmtNumber(row.rmse)}</td>
      <td>${row.mape_pct === null || row.mape_pct === undefined ? 'n/a' : `${fmtNumber(row.mape_pct, 4)}%`}</td>
      <td>${row.enough_samples ? 'Yes' : 'No'}</td>
    </tr>`).join('')
    : '<tr><td colspan="7">No per-horizon forecast quality rows available.</td></tr>';

  const baselineRows = ((forecastTrust.baseline_comparison || {}).rows || []).length
    ? forecastTrust.baseline_comparison.rows.map(row => `<tr>
      <td>${escapeHtml(row.baseline_name || '')}</td>
      <td>${escapeHtml(row.metric_name || '')}</td>
      <td>${row.model_metric === null || row.model_metric === undefined ? 'n/a' : fmtNumber(row.model_metric, 2)}</td>
      <td>${row.baseline_metric === null || row.baseline_metric === undefined ? 'n/a' : fmtNumber(row.baseline_metric, 2)}</td>
      <td>${row.delta === null || row.delta === undefined ? 'n/a' : fmtNumber(row.delta, 2)}</td>
      <td>${fmtCount(row.sample_count || 0)}</td>
      <td>${row.enough_samples ? 'Yes' : 'No'}</td>
    </tr>`).join('')
    : '<tr><td colspan="7">No stored baseline comparison rows available.</td></tr>';

  const distributionRows = [
    ['Raw signal distribution', signalTrust.raw_signal_distribution || {}],
    ['Signal status distribution', signalTrust.signal_status_distribution || {}],
    ['Validation status distribution', signalTrust.validation_status_distribution || {}],
    ['Average validation score', signalTrust.average_validation_score],
    ['Blocked / watch / hold counts', signalTrust.blocked_watch_hold_counts || {}],
    ['Direction vs validation mismatch count', signalTrust.raw_signal_validation_mismatch_count],
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
        <td>${escapeHtml(row.timeframe_role_label || snap.timeframe_role_label || row.timeframe_role || 'validation')}</td>
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
    : '<tr><td colspan="14">No multi-timeframe validation rows available.</td></tr>';

  const reasonHtml = (reasonDetails.length || reasonCodes.length)
    ? `<div class="warning-stack">
        ${reasonCodes.map(code => `<div class="warning-item">Reason code: ${escapeHtml(code)}</div>`).join('')}
        ${reasonDetails.map(item => `<div class="warning-item">${escapeHtml(item)}</div>`).join('')}
      </div>`
    : '<div class="tiny-help">No validation reasons attached for this run.</div>';

  $('validation').innerHTML = `
    <div class="panel-head">
      <div>
        <h2>Forecast Quality</h2>
        <p>Directional forecast hit rate, per-horizon quality, final/partial state, and baseline context.</p>
      </div>
      ${chip(sv.final_signal || v.quality_status || 'PENDING')}
    </div>

    ${validationBannerHtml}

    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${qualityRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Per-Horizon Forecast Quality</h3>
    <div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Samples</th><th>Directional Forecast Hit Rate</th><th>MAE</th><th>RMSE</th><th>MAPE</th><th>Enough Samples</th></tr></thead><tbody>${horizonRows}</tbody></table></div>

    <h3 style="margin-top: 12px;">Baseline Comparison</h3>
    <div class="table-wrap"><table><thead><tr><th>Baseline</th><th>Metric</th><th>Model</th><th>Baseline</th><th>Delta</th><th>Samples</th><th>Enough Samples</th></tr></thead><tbody>${baselineRows}</tbody></table></div>

    <h3 style="margin-top: 12px;">Signal Quality</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${metricRows(distributionRows)}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">External Signal Validation</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${scoreRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Data/Input Health</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>
      ${metricRows(inputHealthRows)}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Score Breakdown</h3>
    ${scoreStatusHtml}
    <div class="table-wrap"><table><thead><tr><th>Component</th><th>Score</th></tr></thead><tbody>
      ${componentRows.map(([k, val]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val ?? 'n/a')}</td></tr>`).join('')}
    </tbody></table></div>

    <h3 style="margin-top: 12px;">Multi-Timeframe Context</h3>
    <div class="table-wrap"><table><thead>
      <tr>
        <th>Timeframe</th><th>Role</th><th>Trend</th><th>Confirms</th><th>State</th><th>Score</th>
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
  const pg = data.postgres_snapshot || {};
  const liveQuote = pg.live_quote || data.live_quote || {};
  const regime = aiRows(latestAiStack.regime)[0] || {};
  const scorer = aiRows(latestAiStack.scorer)[0] || {};
  const entryPrice = firstFinite(hs.entry_price, te.recommended_entry);
  const targetPrice = firstFinite(hs.tp_price, te.take_profit);
  const stopPrice = firstFinite(hs.sl_price, te.stop_loss);
  const spreadAbs = firstFinite(liveQuote.spread, firstFinite(liveQuote.ask) !== null && firstFinite(liveQuote.bid) !== null ? firstFinite(liveQuote.ask) - firstFinite(liveQuote.bid) : null, regime.spread);
  const stopDistance = entryPrice === null || stopPrice === null ? null : Math.abs(entryPrice - stopPrice);
  const stopDistancePct = entryPrice === null || stopPrice === null ? null : (Math.abs(entryPrice - stopPrice) / Math.max(entryPrice, 1e-9)) * 100;
  const rewardRisk = riskRewardRatio(entryPrice, targetPrice, stopPrice);
  const lossProbabilityPct = scorer.probability_loss === null || scorer.probability_loss === undefined ? null : scorePercent(scorer.probability_loss, true);
  const executionCounts = queue.counts || {};

  $('risk').innerHTML = `
    <div class="section-kicker">Risk Gate</div>
    <div class="section-titlebar">
      <div>
        <h2 class="section-title">Execution Risk Console</h2>
        <p class="section-sub">The live trade gate view for the latest signal, current spread environment, and execution queue pressure.</p>
      </div>
      ${chip(hs.signal_status || regime.risk_state || 'PENDING')}
    </div>

    <div class="risk-grid" style="margin-bottom: 14px;">
      ${riskItem('Signal', normalizeDecisionSignal(hs.signal || 'NO_TRADE'), hs.signal_status || 'PENDING', toneClassForDecision(hs.signal || 'NO_TRADE'))}
      ${riskItem('Entry / TP / SL', `${formatPrice(entryPrice)} / ${formatPrice(targetPrice)} / ${formatPrice(stopPrice)}`, 'Current level stack from status / execution payload', 'info')}
      ${riskItem('Stop Distance', stopDistance === null ? 'N/A' : fmtNumber(stopDistance, 2), stopDistancePct === null ? 'No stop distance available' : `${fmtNumber(stopDistancePct, 3)}% of entry`, 'info')}
      ${riskItem('Risk / Reward', rewardRisk === null ? 'N/A' : `${fmtNumber(rewardRisk, 2)} R`, rewardRisk === null ? 'Cannot derive from current levels' : 'Based on TP1 and stop loss', rewardRisk !== null && rewardRisk >= 1.5 ? 'good' : rewardRisk !== null && rewardRisk >= 1 ? 'warn' : 'bad')}
      ${riskItem('Spread', spreadAbs === null ? 'N/A' : fmtNumber(spreadAbs, 4), v.movement_after_cost_warning ? 'Movement-after-cost warning is active' : 'No cost warning flagged', v.movement_after_cost_warning ? 'bad' : 'good')}
      ${riskItem('Expected Move', v.max_abs_close_move_pct === null || v.max_abs_close_move_pct === undefined ? 'N/A' : `${fmtNumber(v.max_abs_close_move_pct, 3)}%`, 'Latest validation expected move', v.max_abs_close_move_pct === null || v.max_abs_close_move_pct === undefined ? 'info' : 'good')}
      ${riskItem('Loss Probability', lossProbabilityPct === null ? 'N/A' : `${fmtNumber(lossProbabilityPct, 2)}%`, scorer.probability_loss === null || scorer.probability_loss === undefined ? 'No loss probability in scorer payload' : 'From current scorer output', lossProbabilityPct === null ? 'info' : toneForPercent(lossProbabilityPct, { inverse: true }))}
      ${riskItem('Broker Health', te.ok ? 'READY' : 'LIMITED', te.ok ? 'Execution backend is available' : (te.error || 'Execution backend unavailable'), te.ok ? 'good' : 'bad')}
      ${riskItem('Queue Pressure', fmtCount((queue.entries || []).length), JSON.stringify(executionCounts || {}), (queue.entries || []).length > 0 ? 'warn' : 'good')}
      ${riskItem('Volatility State', regime.risk_state || 'N/A', regime.garch_volatility === null || regime.garch_volatility === undefined ? 'GARCH volatility unavailable' : `GARCH ${fmtNumber(regime.garch_volatility, 4)} · Realized ${fmtNumber(regime.realized_volatility, 4)}`, statusClass(regime.risk_state || 'info'))}
    </div>

    <div class="overview-primary">
      <section class="section-card">
        <div class="section-kicker">Queue Snapshot</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Execution Queue & Health</h2>
            <p class="section-sub">Queue counts, broker status, and latest execution validation context.</p>
          </div>
          ${chip(te.ok ? 'READY' : 'LIMITED')}
        </div>
        <div class="stats-grid">
          ${kpi('Queue Entries', fmtCount((queue.entries || []).length), 'Queued execution requests')}
          ${kpi('Queued By State', JSON.stringify(executionCounts || {}), 'Raw queue counts object')}
          ${kpi('Validation Status', hs.signal_status || 'N/A', v.movement_after_cost_warning ? 'Cost warning active' : 'No cost warning')}
          ${kpi('Confidence', hs.confidence_pct === null || hs.confidence_pct === undefined ? 'N/A' : `${fmtNumber(hs.confidence_pct, 2)}%`, 'Status endpoint confidence')}
        </div>
      </section>

      <section class="section-card">
        <div class="section-kicker">Raw Risk Values</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Detailed Risk Table</h2>
            <p class="section-sub">Raw values remain available for audit even after the redesign.</p>
          </div>
          ${chip(regime.regime || 'N/A')}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>
          <tr><td>Signal</td><td>${escapeHtml(hs.signal || 'N/A')}</td></tr>
          <tr><td>Signal Status</td><td>${escapeHtml(hs.signal_status || 'N/A')}</td></tr>
          <tr><td>Entry Price</td><td>${formatPrice(entryPrice)}</td></tr>
          <tr><td>Take Profit (TP1)</td><td>${formatPrice(targetPrice)}</td></tr>
          <tr><td>Stop Loss</td><td>${formatPrice(stopPrice)}</td></tr>
          <tr><td>Confidence</td><td>${hs.confidence_pct === null || hs.confidence_pct === undefined ? 'N/A' : `${fmtNumber(hs.confidence_pct, 2)}%`}</td></tr>
          <tr><td>Expected Move</td><td>${v.max_abs_close_move_pct === undefined || v.max_abs_close_move_pct === null ? 'N/A' : `${fmtNumber(v.max_abs_close_move_pct, 3)}%`}</td></tr>
          <tr><td>Cost Warning</td><td>${v.movement_after_cost_warning ? 'Yes' : 'No'}</td></tr>
          <tr><td>Execution Queue</td><td>${escapeHtml(JSON.stringify(executionCounts || {}))}</td></tr>
          <tr><td>Broker Execution Health</td><td>${te.ok ? 'OK' : escapeHtml(te.error || 'Unavailable')}</td></tr>
          <tr><td>Regime</td><td>${escapeHtml(regime.regime || 'N/A')}</td></tr>
          <tr><td>Risk State</td><td>${escapeHtml(regime.risk_state || 'N/A')}</td></tr>
          <tr><td>Loss Probability</td><td>${lossProbabilityPct === null ? 'N/A' : `${fmtNumber(lossProbabilityPct, 2)}%`}</td></tr>
        </tbody></table></div>
      </section>
    </div>`;
}

function readTradeExecutionFiltersFromUi() {
  tradeExecutionFilters = {
    lifecycle: String($('tradeLifecycleFilter')?.value || '').toUpperCase(),
    dateFrom: String($('tradeDateFromFilter')?.value || '').trim(),
    dateTo: String($('tradeDateToFilter')?.value || '').trim(),
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

function normalizeTradeExecutionRows(active, pending, historical, queueEntries, decisions) {
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
    validation_status: trade.validation_status_at_execution || trade.validation_status || '',
    validation_score_at_execution: trade.validation_score_at_execution,
    expected_move_pct_at_execution: trade.expected_move_pct_at_execution,
    entry_spread_pct: trade.entry_spread_pct,
    execution_decision: String(trade.execution_decision || '').toUpperCase(),
    execution_block_reason: trade.execution_block_reason || '',
    execution_decision_details: trade.execution_decision_details || {},
    execution_net_expected_edge_pct: trade.execution_net_expected_edge_pct,
    execution_spread_pct: trade.execution_spread_pct,
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
    net_pnl: trade.net_pnl,
    gross_pnl: trade.gross_pnl,
    fee_amount: trade.fee_amount,
    spread_cost: trade.spread_cost,
    slippage_estimate: trade.slippage_estimate,
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
    execution_decision: String(entry.execution_decision || '').toUpperCase(),
    execution_block_reason: entry.execution_block_reason || '',
    execution_decision_details: entry.execution_decision_details || {},
    execution_net_expected_edge_pct: entry.execution_net_expected_edge_pct,
    execution_spread_pct: entry.execution_spread_pct,
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
  const coveredSignals = new Set([
    ...active,
    ...pending,
    ...historical,
    ...queueEntries,
  ].map(row => String(row.signal_id || '')).filter(Boolean));
  const decisionRow = decision => ({
    source: 'DECISION',
    lifecycle: String(decision.execution_decision || 'DECISION').toUpperCase() === 'BLOCK' ? 'BLOCKED' : 'DECISION',
    record_id: decision.id,
    signal_id: decision.signal_id || '',
    created_at: decision.evaluated_at || '',
    updated_at: decision.evaluated_at || '',
    status: String(decision.execution_decision || 'UNKNOWN').toUpperCase(),
    signal_status: String(decision.signal_status || '').toUpperCase(),
    signal_label: decision.signal_label || decision.raw_signal || '',
    validation_status: decision.validation_status || decision.signal_validation_status || '',
    execution_decision: String(decision.execution_decision || '').toUpperCase(),
    execution_block_reason: decision.block_reason || '',
    execution_decision_details: decision.details || {},
    execution_net_expected_edge_pct: decision.net_expected_edge_pct,
    execution_spread_pct: decision.spread_pct,
    epic: decision.epic || decision.symbol || '',
    direction: String(decision.direction || '').toUpperCase(),
    requested_size: '',
    executed_size: '',
    recommended_entry: decision.recommended_entry,
    actual_entry: '',
    take_profit: decision.take_profit,
    stop_loss: decision.stop_loss,
    deal_reference: '',
    deal_id: '',
    requested_by: '',
    attempt_count: '',
    next_attempt_at: '',
    failure_reason: decision.block_reason || '',
    error_details: '',
    trade_outcome: '',
    sort_ms: parseTs(decision.evaluated_at)?.getTime() || 0,
  });

  return [
    ...active.map(row => tradeRow(row, 'ACTIVE')),
    ...pending.map(row => tradeRow(row, 'PENDING')),
    ...queueEntries.map(queueRow),
    ...historical.map(row => tradeRow(row, 'HISTORICAL')),
    ...(decisions || []).filter(row => !coveredSignals.has(String(row.signal_id || ''))).map(decisionRow),
  ].sort((a, b) => b.sort_ms - a.sort_ms);
}

function filterTradeExecutionRows(rows) {
  const lifecycle = String(tradeExecutionFilters.lifecycle || '').toUpperCase();
  const dateFrom = String(tradeExecutionFilters.dateFrom || '');
  const dateTo = String(tradeExecutionFilters.dateTo || '');
  const status = String(tradeExecutionFilters.status || '').toUpperCase();
  const outcome = String(tradeExecutionFilters.outcome || '').toUpperCase();
  const side = String(tradeExecutionFilters.side || '').toUpperCase();
  const signalNeedle = String(tradeExecutionFilters.signalId || '').toLowerCase();
  const transactionNeedle = String(tradeExecutionFilters.transactionId || '').toLowerCase();

  return rows.filter(row => {
    const rowTime = parseTs(row.updated_at || row.created_at || row.next_attempt_at)?.getTime();
    if (dateFrom) {
      const fromTime = parseTs(`${dateFrom}T00:00:00+03:00`)?.getTime();
      if (Number.isFinite(fromTime) && (!Number.isFinite(rowTime) || rowTime < fromTime)) return false;
    }
    if (dateTo) {
      const toTime = parseTs(`${dateTo}T23:59:59+03:00`)?.getTime();
      if (Number.isFinite(toTime) && (!Number.isFinite(rowTime) || rowTime > toTime)) return false;
    }
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
  const executionReason = String(row.execution_block_reason || '').trim();
  const reason = String(executionReason || row.failure_reason || '').trim();
  const details = String(row.error_details || '').trim();
  const edge = row.execution_net_expected_edge_pct === null || row.execution_net_expected_edge_pct === undefined
    ? ''
    : `Net edge ${fmtNumber(row.execution_net_expected_edge_pct, 4)}%`;
  const spread = row.execution_spread_pct === null || row.execution_spread_pct === undefined
    ? ''
    : `Spread ${fmtNumber(row.execution_spread_pct, 4)}%`;
  const decisionContext = [edge, spread].filter(Boolean).join(' · ');
  const validationContext = row.validation_status
    ? `Validation ${row.validation_status}${row.validation_score_at_execution === null || row.validation_score_at_execution === undefined ? '' : ` (${fmtNumber(row.validation_score_at_execution, 2)})`}`
    : '';
  const costContext = [
    row.expected_move_pct_at_execution === null || row.expected_move_pct_at_execution === undefined ? '' : `Expected ${fmtNumber(row.expected_move_pct_at_execution, 4)}%`,
    row.spread_cost === null || row.spread_cost === undefined ? '' : `Spread cost ${fmtNumber(row.spread_cost, 4)}`,
    row.slippage_estimate === null || row.slippage_estimate === undefined ? '' : `Slippage ${fmtNumber(row.slippage_estimate, 4)}`,
  ].filter(Boolean).join(' · ');
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
  return [reasonText, validationContext, decisionContext, costContext].filter(Boolean).join(' · ');
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
  if (row.source !== 'TRADE') return '<span class="muted">not a trade</span>';
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
      <td>${chip(row.status || 'PENDING')}${row.execution_decision ? `<br><span class="muted">${escapeHtml(row.execution_decision)}</span>` : ''}</td>
      <td>${tradeOutcomeHtml(row)}</td>
      <td>${chip(row.signal_status || 'UNKNOWN')}<br><span class="muted">${escapeHtml(row.signal_label || row.validation_status || '')}</span></td>
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
  const execPerf = ((data.dashboard_trust || {}).executed_trade_performance) || {};
  const queue = te.queue || {};
  const trades = te.trades || [];
  const active = te.active_trades || trades.filter(t => ['OPEN', 'CLOSE_REQUESTED'].includes(String(t.status || '').toUpperCase()));
  const pending = te.pending_trades || trades.filter(t => ['PENDING', 'SUBMITTED'].includes(String(t.status || '').toUpperCase()));
  const historical = te.historical_trades || trades.filter(t => !['OPEN', 'CLOSE_REQUESTED', 'PENDING', 'SUBMITTED'].includes(String(t.status || '').toUpperCase()));
  const queueEntries = queue.entries || [];
  const decisions = te.execution_decisions || [];
  const allRows = normalizeTradeExecutionRows(active, pending, historical, queueEntries, decisions);
  const filteredRows = filterTradeExecutionRows(allRows);
  const allOutcomeCounts = tradeOutcomeCounts(allRows);
  const filteredOutcomeCounts = tradeOutcomeCounts(filteredRows);
  const outcomeKpiSub = key => `${fmtCount(filteredOutcomeCounts[key] || 0)} filtered / ${fmtCount(allOutcomeCounts[key] || 0)} loaded`;
  const filteredOutcomePnl = (filteredOutcomeCounts.WIN || 0) - (filteredOutcomeCounts.LOSS || 0);
  const allOutcomePnl = (allOutcomeCounts.WIN || 0) - (allOutcomeCounts.LOSS || 0);
  const closedCount = Number(execPerf.closed_trade_count || 0);
  const finalizedCount = Number(execPerf.finalized_trade_count || 0);
  const unknownOutcomeCount = Number(execPerf.unknown_outcome_count || 0);
  const brokerLookupBlocked = te.trade_outcome_lookup_error || te.transaction_lookup_error;
  const pendingOutcomeText = closedCount > 0
    ? (brokerLookupBlocked ? 'Broker lookup blocked' : 'Awaiting broker outcome')
    : 'No closed trades yet';
  const pendingOutcomeSub = brokerLookupBlocked
    ? 'Capital.com close activity lookup failed'
    : `${fmtCount(unknownOutcomeCount)} closed trades need finalized P/L`;
  const perfValue = (value, formatter = v => fmtNumber(v, 4)) =>
    value === null || value === undefined ? pendingOutcomeText : formatter(value);
  const perfSub = fallback => (finalizedCount > 0 ? fallback : pendingOutcomeSub);
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
  const decisionRows = (((data.dashboard_trust || {}).execution_decision_reasons || {}).rows || []).slice(0, 12);
  const decisionTableRows = decisionRows.length
    ? decisionRows.map(row => `<tr>
      <td>${fmtDate(row.evaluated_at || row.created_at || '')}</td>
      <td>${escapeHtml(row.signal_id || '')}</td>
      <td>${chip(row.execution_decision || 'UNKNOWN')}</td>
      <td>${escapeHtml(row.block_reason || '')}</td>
      <td>${escapeHtml(row.validation_status || '')}</td>
      <td>${row.validation_score === null || row.validation_score === undefined ? 'not stored' : fmtNumber(row.validation_score, 2)}</td>
      <td>${row.net_expected_edge_pct === null || row.net_expected_edge_pct === undefined ? 'not evaluated' : `${fmtNumber(row.net_expected_edge_pct, 4)}%`}</td>
      <td>${row.spread_pct === null || row.spread_pct === undefined ? 'not evaluated' : `${fmtNumber(row.spread_pct, 4)}%`}</td>
      <td>${row.estimated_fee_pct === null || row.estimated_fee_pct === undefined ? 'not evaluated' : `${fmtNumber(row.estimated_fee_pct, 4)}%`}</td>
      <td>${row.estimated_slippage_pct === null || row.estimated_slippage_pct === undefined ? 'not evaluated' : `${fmtNumber(row.estimated_slippage_pct, 4)}%`}</td>
    </tr>`).join('')
    : '<tr><td colspan="10">No execution decision audit rows available.</td></tr>';

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
      ${kpi('Executed Win Rate', perfValue(execPerf.executed_trade_win_rate_pct, v => `${fmtNumber(v, 2)}%`), perfSub('Closed finalized executed trades only'))}
      ${kpi('Total Net P/L', perfValue(execPerf.total_net_pnl), `${fmtCount(finalizedCount)} finalized / ${fmtCount(closedCount)} closed`)}
      ${kpi('Expectancy', perfValue(execPerf.expectancy), perfSub('Average net P/L per finalized trade'))}
      ${kpi('Average Win', perfValue(execPerf.average_win), `${fmtCount(execPerf.wins || 0)} wins`)}
      ${kpi('Average Loss', perfValue(execPerf.average_loss), `${fmtCount(execPerf.losses || 0)} losses`)}
      ${kpi('Drawdown', perfValue(execPerf.max_drawdown), perfSub('From finalized trade net P/L sequence'))}
      ${kpi('Spread Impact', perfValue(execPerf.average_spread_cost), perfSub('Average finalized spread cost'))}
      ${kpi('Slippage Impact', perfValue(execPerf.average_slippage_estimate), perfSub('Average finalized slippage estimate'))}
      ${kpi('Finalization Pending', fmtCount(execPerf.unknown_outcome_count || 0), 'Closed trades missing finalized P/L outcome')}
    </div>

    <h3 style="margin-top: 12px;">Execution Decision Reasons</h3>
    <div class="table-wrap" style="margin-bottom: 12px;"><table><thead><tr><th>Date / Time</th><th>Signal</th><th>Decision</th><th>Block Reason</th><th>Validation</th><th>Score</th><th>Net Edge</th><th>Spread</th><th>Fee</th><th>Slippage</th></tr></thead><tbody>${decisionTableRows}</tbody></table></div>

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
      <label class="field">From Date
        <input id="tradeDateFromFilter" type="date" value="${escapeHtml(tradeExecutionFilters.dateFrom)}" title="Dates are interpreted in Asia/Amman timezone.">
      </label>
      <label class="field">To Date
        <input id="tradeDateToFilter" type="date" value="${escapeHtml(tradeExecutionFilters.dateTo)}" title="Dates are interpreted in Asia/Amman timezone.">
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
    <div class="table-wrap"><table><thead><tr><th>Baseline</th><th>Direction</th><th>Quality</th><th>Directional Forecast Hit Rate</th></tr></thead><tbody>${rows}</tbody></table></div>`;
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

function aiRows(payload) {
  return Array.isArray(payload?.rows) ? payload.rows : [];
}

function aiForecastRows() {
  return Array.isArray(latestAiStack.forecasts?.forecasts) ? latestAiStack.forecasts.forecasts : [];
}

function aiForecastRuns() {
  return Array.isArray(latestAiStack.forecasts?.runs) ? latestAiStack.forecasts.runs : [];
}

function aiJsonObject(value) {
  if (!value) return {};
  if (typeof value === 'object') return value;
  try {
    const parsed = JSON.parse(String(value));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_err) {
    return {};
  }
}

function aiModelKey(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function aiMatchesModel(row, aliases) {
  const key = aiModelKey(row.model_key || row.scorer_model || row.model || '');
  return aliases.some(alias => key.includes(aiModelKey(alias)));
}

function aiFindRun(aliases) {
  return aiForecastRuns().find(row => aiMatchesModel(row, aliases)) || {};
}

function aiFindForecast(aliases) {
  return aiForecastRows().find(row => aiMatchesModel(row, aliases)) || {};
}

function aiForecastModelRow(label, aliases) {
  const run = aiFindRun(aliases);
  const point = aiFindForecast(aliases);
  const status = run.status || (point.id ? 'OK' : 'PENDING');
  const direction = point.predicted_direction || run.raw_json?.direction || 'n/a';
  const band = point.lower_bound !== null && point.lower_bound !== undefined || point.upper_bound !== null && point.upper_bound !== undefined
    ? `${fmtNumber(point.lower_bound)} / ${fmtNumber(point.upper_bound)}`
    : 'n/a';
  const message = run.error_message || point.raw_json?.message || '';
  return `<tr>
    <td>${escapeHtml(label)}<br><span class="muted">${escapeHtml(run.model_key || point.model_key || aliases[0])}</span></td>
    <td>${chip(status)}</td>
    <td>${chip(direction)}</td>
    <td>${fmtNumber(point.predicted_close)}</td>
    <td>${point.predicted_return === null || point.predicted_return === undefined ? 'n/a' : pct01(point.predicted_return)}</td>
    <td>${band}</td>
    <td>${point.confidence === null || point.confidence === undefined ? 'n/a' : pct01(point.confidence)}</td>
    <td>${escapeHtml(message || fmtDate(point.forecast_for_ts || run.created_at))}</td>
  </tr>`;
}

function aiVoteRows(ensemble) {
  const votes = aiJsonObject(ensemble.model_votes_json || ensemble.model_votes);
  const entries = Object.entries(votes);
  if (!entries.length) {
    return '<tr><td colspan="4">No model votes persisted yet.</td></tr>';
  }
  return entries.map(([model, vote]) => {
    const body = vote && typeof vote === 'object' ? vote : {};
    return `<tr>
      <td>${escapeHtml(model)}</td>
      <td>${chip(body.direction || 'n/a')}</td>
      <td>${body.predicted_return === null || body.predicted_return === undefined ? 'n/a' : pct01(body.predicted_return)}</td>
      <td>${body.confidence === null || body.confidence === undefined ? 'n/a' : pct01(body.confidence)}</td>
    </tr>`;
  }).join('');
}

function aiPerformanceRows(perf) {
  const active = perf?.active_model || {};
  const shadow = perf?.shadow_model || {};
  const matched = perf?.comparison?.matched_runs || {};
  return `
    <tr><th>Active Directional Hit Rate</th><td>${active.direction_accuracy_pct === null || active.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(active.direction_accuracy_pct, 2)}%`}</td></tr>
    <tr><th>Shadow Directional Hit Rate</th><td>${shadow.direction_accuracy_pct === null || shadow.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(shadow.direction_accuracy_pct, 2)}%`}</td></tr>
    <tr><th>Shadow Lift</th><td>${shadow.lift_pct === null || shadow.lift_pct === undefined ? 'n/a' : `${fmtNumber(shadow.lift_pct, 2)}%`}</td></tr>
    <tr><th>Evaluation Rows</th><td>${fmtCount(matched.evaluation_rows)}</td></tr>`;
}

function aiValidationRows() {
  const rows = aiRows(latestAiStack.validation).slice(0, 8);
  if (!rows.length) {
    return '<tr><td colspan="8">No forecast validation rows persisted yet.</td></tr>';
  }
  return rows.map(row => `<tr>
    <td>${escapeHtml(row.model_key || '')}</td>
    <td>${escapeHtml(row.horizon_bar ?? '')}</td>
    <td>${fmtCount(row.n_samples)}</td>
    <td>${row.direction_accuracy === null || row.direction_accuracy === undefined ? 'n/a' : pct01(row.direction_accuracy)}</td>
    <td>${fmtNumber(row.mae)}</td>
    <td>${fmtNumber(row.rmse)}</td>
    <td>${row.hit_rate_after_spread === null || row.hit_rate_after_spread === undefined ? 'n/a' : pct01(row.hit_rate_after_spread)}</td>
    <td>${fmtDate(row.evaluated_at)}</td>
  </tr>`).join('');
}

function aiTradeOutcomeRows() {
  const rows = (latestSignals.rows || []).slice(0, 8);
  if (!rows.length) {
    return '<tr><td colspan="6">No recent signal outcomes loaded yet.</td></tr>';
  }
  return rows.map(row => `<tr>
    <td>${escapeHtml(row.signal_id || row.run_id || '')}</td>
    <td>${chip(row.signal || row.direction || 'n/a')}</td>
    <td>${chip(row.status || row.signal_status || 'PENDING')}</td>
    <td>${escapeHtml(row.validation_status || row.trade_outcome || row.outcome || 'n/a')}</td>
    <td>${fmtCount(row.outcomes_wins || row.wins)} / ${fmtCount(row.outcomes_losses || row.losses)} / ${fmtCount(row.outcomes_pending || row.pending)}</td>
    <td>${fmtDate(row.created_at || row.timestamp_utc || row.updated_at)}</td>
  </tr>`).join('');
}

function resolveAiSpread(data, regime) {
  const pg = data.postgres_snapshot || {};
  const liveQuote = pg.live_quote || data.live_quote || {};
  const bid = toFiniteNumber(liveQuote.bid);
  const ask = toFiniteNumber(liveQuote.ask);
  if (bid !== null && ask !== null) return Math.max(0, ask - bid);
  const quoteSpread = toFiniteNumber(liveQuote.spread);
  if (quoteSpread !== null) return quoteSpread;
  return toFiniteNumber(regime.spread);
}

function renderAiStack(data = latest) {
  const ensemble = aiRows(latestAiStack.ensemble)[0] || {};
  const regime = aiRows(latestAiStack.regime)[0] || {};
  const score = aiRows(latestAiStack.scorer)[0] || {};
  const scoreFeatures = aiJsonObject(score.features_json || score.features);
  const finalDecision = aiJsonObject(scoreFeatures.final_decision || {});
  const price = resolveLatestPrice(data);
  const spread = resolveAiSpread(data, regime);
  const warnings = ['forecasts', 'ensemble', 'regime', 'scorer', 'validation']
    .map(name => latestAiStack[name]?.warning ? `${name}: ${latestAiStack[name].warning}` : '')
    .filter(Boolean);
  const warningHtml = warnings.length
    ? `<div class="warning-stack">${warnings.map(item => `<div class="warning-item">${escapeHtml(item)}</div>`).join('')}</div>`
    : '';

  const decision = normalizeDecisionSignal(score.decision || finalDecision.decision || data.human_summary?.signal || 'NO_TRADE');

  const buildSupportCard = (label, aliases) => {
    const run = aiFindRun(aliases);
    const point = aiFindForecast(aliases);
    const direction = point.predicted_direction || run.raw_json?.direction || '';
    const status = supportAlignmentStatus(decision, direction, run.status || (point.id ? 'READY' : 'PENDING'));
    return modelSupportCard({
      name: label,
      status,
      direction: direction || 'N/A',
      supportValue: point.predicted_return === null || point.predicted_return === undefined ? 'N/A' : formatPercentFromFraction(point.predicted_return, 2),
      confidence: point.confidence === null || point.confidence === undefined ? 'N/A' : formatPercentFromFraction(point.confidence, 1),
      detail: run.error_message || fmtDate(point.forecast_for_ts || run.created_at) || 'No recent model output',
    });
  };

  const garchStatus = (() => {
    const riskState = String(regime.risk_state || '').toUpperCase();
    if (!riskState) return 'NEUTRAL';
    if (['LOW', 'LOW_RISK', 'NORMAL'].includes(riskState)) return 'SUPPORT';
    if (['HIGH', 'HIGH_RISK', 'EXTREME', 'NO_TRADE'].includes(riskState)) return 'AGAINST';
    return 'NEUTRAL';
  })();

  const supportGrid = [
    buildSupportCard('Kronos', ['kronos']),
    buildSupportCard('Chronos-2', ['chronos2', 'chronos-2']),
    buildSupportCard('TimesFM', ['timesfm', 'times-fm']),
    buildSupportCard('Moirai', ['moirai']),
    buildSupportCard('PatchTST', ['patchtst', 'patch-tst']),
    buildSupportCard('iTransformer', ['itransformer', 'i-transformer']),
    modelSupportCard({
      name: 'GARCH',
      status: garchStatus,
      direction: regime.regime || regime.risk_state || 'N/A',
      supportValue: regime.garch_volatility === null || regime.garch_volatility === undefined ? 'N/A' : fmtNumber(regime.garch_volatility, 4),
      confidence: regime.realized_volatility === null || regime.realized_volatility === undefined ? 'N/A' : fmtNumber(regime.realized_volatility, 4),
      detail: regime.risk_state ? `Risk state ${regime.risk_state}` : 'No volatility regime snapshot',
    }),
  ].join('');

  const foundationRows = [
    aiForecastModelRow('Kronos Forecast', ['kronos']),
    aiForecastModelRow('Chronos-2 Forecast', ['chronos2', 'chronos-2']),
    aiForecastModelRow('TimesFM Forecast', ['timesfm', 'times-fm']),
    aiForecastModelRow('Moirai Uncertainty Band', ['moirai']),
    aiForecastModelRow('PatchTST Local Forecast', ['patchtst', 'patch-tst']),
    aiForecastModelRow('iTransformer Local Forecast', ['itransformer', 'i-transformer']),
  ].join('');

  $('aiStack').innerHTML = `
    <div class="section-kicker">AI Support</div>
    <div class="section-titlebar">
      <div>
        <h2 class="section-title">Model Support Console</h2>
        <p class="section-sub">Forecast models, ensemble direction, volatility regime, and scorer outputs rendered from the existing AI endpoints.</p>
      </div>
      <span class="chip info">${escapeHtml($('resolution').value || 'MINUTE_5')}</span>
    </div>
    ${warningHtml}
    <div class="kpi-grid ai-stack-grid" style="margin-bottom: 14px;">
      ${kpi('Current Price', price === null ? 'N/A' : fmtNumber(price, 2), spread === null ? 'Spread N/A' : `Spread ${fmtNumber(spread, 4)}`)}
      ${kpi('Active Regime', regime.regime || 'N/A', `Risk ${regime.risk_state || 'N/A'}`)}
      ${kpi('Ensemble Direction', normalizeDecisionSignal(ensemble.ensemble_direction || 'NO_TRADE'), `Agreement ${ensemble.agreement_score === null || ensemble.agreement_score === undefined ? 'N/A' : pct01(ensemble.agreement_score)}`)}
      ${kpi('GARCH / Realized Vol', regime.garch_volatility === null || regime.garch_volatility === undefined ? 'N/A' : fmtNumber(regime.garch_volatility, 4), regime.realized_volatility === null || regime.realized_volatility === undefined ? 'Realized N/A' : `Realized ${fmtNumber(regime.realized_volatility, 4)}`)}
      ${kpi('Win Probability', score.probability_win === null || score.probability_win === undefined ? 'N/A' : pct01(score.probability_win), `Loss ${score.probability_loss === null || score.probability_loss === undefined ? 'N/A' : pct01(score.probability_loss)} · ${score.scorer_model || 'fallback scorer'}`)}
      ${kpi('Final Decision', normalizeDecisionSignal(score.decision || finalDecision.decision || 'NO_TRADE'), finalDecision.reason || `Expected return ${score.expected_return === null || score.expected_return === undefined ? 'N/A' : pct01(score.expected_return)}`)}
    </div>

    <section class="section-card" style="margin-bottom: 14px;">
      <div class="section-kicker">Alignment Grid</div>
      <div class="section-titlebar">
        <div>
          <h2 class="section-title">Support / Neutral / Against</h2>
          <p class="section-sub">Each model card shows direction, support value, and confidence using the current AI stack payloads.</p>
        </div>
        ${chip(decision)}
      </div>
      <div class="model-support-grid">${supportGrid}</div>
    </section>

    <div class="overview-primary">
      <section class="section-card">
        <div class="section-kicker">Forecast Table</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Model Forecasts</h2>
            <p class="section-sub">Latest forecast rows from Kronos and the other model surfaces.</p>
          </div>
          ${chip(aiForecastRows().length ? 'READY' : 'PENDING')}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Model</th><th>Status</th><th>Direction</th><th>Close</th><th>Return</th><th>Band</th><th>Confidence</th><th>Time / Message</th></tr></thead><tbody>${foundationRows}</tbody></table></div>
      </section>

      <section class="section-card">
        <div class="section-kicker">Votes & Quality</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Ensemble Votes</h2>
            <p class="section-sub">Current model votes plus stored performance and validation quality.</p>
          </div>
          ${chip(ensemble.ensemble_direction || 'N/A')}
        </div>
        <div class="table-wrap" style="margin-bottom: 12px;"><table><thead><tr><th>Model</th><th>Vote</th><th>Return</th><th>Confidence</th></tr></thead><tbody>${aiVoteRows(ensemble)}</tbody></table></div>
        <div class="table-wrap"><table><tbody>${aiPerformanceRows(latestModelPerformance || {})}</tbody></table></div>
      </section>
    </div>

    <section class="section-card" style="margin-top: 14px;">
      <div class="section-kicker">Validation</div>
      <div class="section-titlebar">
        <div>
          <h2 class="section-title">Recent Forecast Validation</h2>
          <p class="section-sub">Stored forecast validation rows for the current timeframe.</p>
        </div>
        <span class="chip info">${fmtCount(aiRows(latestAiStack.validation).length)} rows</span>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Model</th><th>Horizon</th><th>Samples</th><th>Direction Accuracy</th><th>MAE</th><th>RMSE</th><th>Hit After Spread</th><th>Evaluated</th></tr></thead><tbody>${aiValidationRows()}</tbody></table></div>
    </section>

    <section class="section-card" style="margin-top: 14px;">
      <div class="section-kicker">Trade Outcomes</div>
      <div class="section-titlebar">
        <div>
          <h2 class="section-title">Recent Signal Outcomes</h2>
          <p class="section-sub">Outcome snapshots remain visible beside the AI stack so you can compare model support with realized result flow.</p>
        </div>
        <span class="chip info">${fmtCount((latestSignals.rows || []).length)} rows</span>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Signal / Run</th><th>Signal</th><th>Status</th><th>Outcome</th><th>WIN / LOSS / PENDING</th><th>Time</th></tr></thead><tbody>${aiTradeOutcomeRows()}</tbody></table></div>
    </section>`;
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
  if (activeTab === 'aiStack') {
    renderAiStack(latest);
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
  const matchedRows = `<tr><th>Directional Wins / Losses</th><td>${fmtCount(activeMatched.wins)} / ${fmtCount(activeMatched.losses)}</td><td>${fmtCount(shadowMatched.wins)} / ${fmtCount(shadowMatched.losses)}</td></tr>
    <tr><th>Directional Samples</th><td>${fmtCount(activeMatched.samples)}</td><td>${fmtCount(shadowMatched.samples)}</td></tr>
    <tr><th>Matched Directional Hit Rate</th><td>${activeMatched.win_rate_pct === null || activeMatched.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(activeMatched.win_rate_pct, 2)}%`}</td><td>${shadowMatched.win_rate_pct === null || shadowMatched.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(shadowMatched.win_rate_pct, 2)}%`}</td></tr>
    <tr><th>Shadow Lift</th><td colspan="2">${matched.shadow_minus_active_pct === null || matched.shadow_minus_active_pct === undefined ? 'n/a' : `${fmtNumber(matched.shadow_minus_active_pct, 2)}%`}</td></tr>
    <tr><th>Disagreements</th><td>${fmtCount(matched.disagreement?.active_wins_when_disagree)} active wins / ${fmtCount(matched.disagreement?.samples)} samples</td><td>${fmtCount(matched.disagreement?.shadow_wins_when_disagree)} shadow wins / ${fmtCount(matched.disagreement?.samples)} samples</td></tr>`;
  const statusRows = `<tr><th>Wins / Losses / Pending</th><td>${fmtCount(statusActiveAll.wins)} / ${fmtCount(statusActiveAll.losses)} / ${fmtCount(statusActiveAll.pending)}</td><td>${fmtCount(statusActiveCovered.wins)} / ${fmtCount(statusActiveCovered.losses)} / ${fmtCount(statusActiveCovered.pending)}</td><td>${fmtCount(statusShadowRuns.wins)} / ${fmtCount(statusShadowRuns.losses)} / ${fmtCount(statusShadowRuns.pending)}</td></tr>
    <tr><th>Run Count</th><td>${fmtCount(statusActiveAll.total)}</td><td>${fmtCount(statusActiveCovered.total)}</td><td>${fmtCount(statusShadowRuns.total)}</td></tr>
    <tr><th>Signal Outcome Hit Rate</th><td>${statusActiveAll.win_rate_pct === null || statusActiveAll.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusActiveAll.win_rate_pct, 2)}%`}</td><td>${statusActiveCovered.win_rate_pct === null || statusActiveCovered.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusActiveCovered.win_rate_pct, 2)}%`}</td><td>${statusShadowRuns.win_rate_pct === null || statusShadowRuns.win_rate_pct === undefined ? 'n/a' : `${fmtNumber(statusShadowRuns.win_rate_pct, 2)}%`}</td></tr>`;
  $('modelPerformance').innerHTML = `
    <div class="panel-head"><h2>Model Performance</h2><span class="chip info">${escapeHtml(shadow.model_version_id || shadow.shadow_model_version_id || 'no shadow')}</span></div>
    <div class="kpi-grid" style="margin-bottom: 12px;">
      ${kpi('Active Directional Hit Rate', active.direction_accuracy_pct === null || active.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(active.direction_accuracy_pct, 2)}%`, `${fmtCount(active.samples)} samples`)}
      ${kpi('Shadow Directional Hit Rate', shadow.direction_accuracy_pct === null || shadow.direction_accuracy_pct === undefined ? 'n/a' : `${fmtNumber(shadow.direction_accuracy_pct, 2)}%`, `${fmtCount(shadow.samples)} samples`)}
      ${kpi('Shadow Lift', shadow.lift_pct === null || shadow.lift_pct === undefined ? 'n/a' : `${fmtNumber(shadow.lift_pct, 2)}%`, 'Shadow minus active')}
      ${kpi('Disagreements', fmtCount(disagreement.samples), `${fmtCount(disagreement.shadow_wins_when_disagree)} shadow wins`)}
    </div>
    <h3>Fair Comparison (Same Evaluated Windows)</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Active</th><th>Shadow</th></tr></thead><tbody>${matchedRows}</tbody></table></div>
    <div style="margin-top: 6px; font-size: 12px; opacity: 0.85;">Shadow model: ${escapeHtml(comparison.shadow_model_version_id || shadow.model_version_id || 'n/a')} · evaluation rows: ${fmtCount(matched.evaluation_rows)}</div>
    <h3 style="margin-top: 14px;">Signal Status Comparison (Run-level)</h3>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Active (all runs)</th><th>Active (shadow-covered runs)</th><th>Shadow runs</th></tr></thead><tbody>${statusRows}</tbody></table></div>
    <h3>Horizon Metrics</h3>
    <div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Samples</th><th>Active Per-Horizon Hit Rate</th><th>Shadow Per-Horizon Hit Rate</th><th>MAPE</th></tr></thead><tbody>${horizonRows}</tbody></table></div>
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
  const latestRow = (latestSignals.rows || [])[0] || latestSignal;
  const liveQuote = pg.live_quote || data.live_quote || {};
  const ensemble = aiRows(latestAiStack.ensemble)[0] || {};
  const regime = aiRows(latestAiStack.regime)[0] || {};
  const scorer = aiRows(latestAiStack.scorer)[0] || {};
  const scorerFeatures = aiJsonObject(scorer.features_json || scorer.features);
  const finalDecision = aiJsonObject(scorerFeatures.final_decision || {});
  const signalValidation = data.signal_validation || {};
  const postgresOk = pg.postgres?.ok === true;
  const titleSymbol = data.selected_symbol || $('market').value || '__DEFAULT_SYMBOL__';
  const resolvedPrice = resolveLatestPrice(data);
  const titlePriceTime = resolveLatestPriceTime(data);
  const priceFreshness = freshnessState(titlePriceTime);
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

  const lastUpdateHtml = titlePriceTime
    ? `${escapeHtml(fmtDate(titlePriceTime))}<br><span class="muted">${escapeHtml(priceFreshness.label)} · Asia/Amman</span>`
    : 'Awaiting first snapshot';
  setHtmlIfChanged($('lastUpdateStatus'), lastUpdateHtml);

  const websocketHealthLabel = hs.websocket_stale_alert ? 'websocket stale' : 'websocket fresh';
  const bid = firstFinite(liveQuote.bid);
  const ask = firstFinite(liveQuote.ask);
  const spreadAbs = firstFinite(liveQuote.spread, bid !== null && ask !== null ? ask - bid : null, regime.spread);
  const heroMetaHtml = [
    chip(normalizeDecisionSignal(hs.signal || latestSignal.signal || finalDecision.decision || 'n/a')),
    chip(hs.signal_status || latestSignal.status || 'PENDING'),
    chip(regime.regime || v.forecast_direction || 'Direction pending'),
    chip(postgresOk ? 'PostgreSQL OK' : 'PostgreSQL Offline'),
    chip(hs.live_source || 'no_live_source'),
    chip(websocketHealthLabel),
    bid === null ? '' : `<span class="chip info">Bid ${escapeHtml(fmtNumber(bid, 2))}</span>`,
    ask === null ? '' : `<span class="chip info">Ask ${escapeHtml(fmtNumber(ask, 2))}</span>`,
    spreadAbs === null ? '' : `<span class="chip ${hs.websocket_stale_alert ? 'warn' : 'info'}">Spread ${escapeHtml(fmtNumber(spreadAbs, 4))}</span>`,
    `<span class="chip info">${escapeHtml(data.selected_resolution || m.resolution || latestSignal.resolution || 'MINUTE')}</span>`,
    `<span class="chip ${priceFreshness.tone}">${escapeHtml(priceFreshness.label)}</span>`,
  ].filter(Boolean).join('');
  const heroMetaKey = [
    hs.signal || latestSignal.signal || finalDecision.decision || 'n/a',
    hs.signal_status || latestSignal.status || 'PENDING',
    regime.regime || v.forecast_direction || 'Direction pending',
    postgresOk ? 'ok' : 'offline',
    hs.live_source || 'no_live_source',
    websocketHealthLabel,
    data.selected_resolution || m.resolution || latestSignal.resolution || 'MINUTE',
    bid === null ? 'n/a' : fmtNumber(bid, 2),
    ask === null ? 'n/a' : fmtNumber(ask, 2),
    spreadAbs === null ? 'n/a' : fmtNumber(spreadAbs, 4),
    priceFreshness.label,
  ].join('|');
  if (heroMetaKey !== lastHeroMetaKey) {
    setHtmlIfChanged($('heroMeta'), heroMetaHtml);
    lastHeroMetaKey = heroMetaKey;
  }

  renderModelStatus(data.auto_finetune || {}, m);

  const decision = normalizeDecisionSignal(signalValidation.final_signal || hs.signal || latestRow.signal || scorer.decision || finalDecision.decision || 'NO_TRADE');
  const decisionTone = toneClassForDecision(decision);
  const entryPrice = firstFinite(hs.entry_price, latestRow.entry_price, latestRow.recommended_entry);
  const tp1Price = firstFinite(hs.tp_price, latestRow.tp_price, latestRow.take_profit);
  const tp2Price = firstFinite(hs.tp2_price, latestRow.tp2_price);
  const stopPrice = firstFinite(hs.sl_price, latestRow.sl_price, latestRow.stop_loss);
  const rewardRisk = riskRewardRatio(entryPrice, tp1Price, stopPrice);
  const validationSummary = aiJsonObject(latestRow.validation_summary || {});
  const blockReason = signalValidation.block_reason || validationSummary.block_reason || latestRow.execution_block_reason || '';
  const strategyScore = scorePercent(signalValidation.total_score ?? hs.confidence_pct, true);
  const aiSupportScore = scorePercent(ensemble.agreement_score, true);
  const finalScore = scorePercent(scorer.probability_win ?? hs.confidence_pct, true);
  const riskScore = scorer.probability_loss === null || scorer.probability_loss === undefined ? null : Math.max(0, 100 - (scorePercent(scorer.probability_loss, true) || 0));
  const trendBias = normalizeDecisionSignal(ensemble.ensemble_direction || v.forecast_direction || latestRow.direction || 'NO_TRADE');
  const modelLabel = scorer.scorer_model || data.auto_finetune?.current_model_label || m.model_name || 'N/A';
  const reasonNarrative = [
    ...(Array.isArray(signalValidation.reason_details) ? signalValidation.reason_details : []),
    finalDecision.reason,
    validationSummary.reason,
    blockReason ? `Blocked by ${blockReason}` : '',
  ].filter(Boolean)[0] || 'No detailed narrative has been returned yet for the current live decision.';
  const summaryCardsHtml = `
    <div class="hero-terminal">
      <section class="hero-decision">
        <div class="hero-eyebrow">Hero Decision Panel</div>
        <div class="hero-header">
          <div>
            <div class="section-sub">Current live decision</div>
            <div class="hero-signal ${decisionTone}">${escapeHtml(decision)}</div>
            <div class="status-strip">
              ${chip(hs.signal_status || latestSignal.status || 'PENDING')}
              ${chip(regime.regime || 'N/A')}
              ${chip(trendBias)}
              ${chip(modelLabel)}
            </div>
          </div>
          <div class="ring-grid">
            ${scoreRing('Confidence', hs.confidence_pct, hs.confidence_pct === null || hs.confidence_pct === undefined ? 'No confidence value in status payload' : 'Status confidence', toneForPercent(hs.confidence_pct))}
            ${scoreRing('Final Score', finalScore, scorer.probability_win === null || scorer.probability_win === undefined ? 'Scorer win probability unavailable' : 'Derived from scorer win probability', toneForPercent(finalScore))}
          </div>
        </div>
        <div class="decision-levels">
          ${decisionCell('Entry', formatPrice(entryPrice), 'info', 'Current entry level')}
          ${decisionCell('Stop Loss', formatPrice(stopPrice), 'bad', 'Protective stop')}
          ${decisionCell('TP1', formatPrice(tp1Price), 'good', 'Primary target')}
          ${decisionCell('TP2', formatPrice(tp2Price), 'good', tp2Price === null ? 'Secondary target unavailable' : 'Secondary target')}
          ${decisionCell('Risk / Reward', rewardRisk === null ? 'N/A' : `${fmtNumber(rewardRisk, 2)} R`, rewardRisk !== null && rewardRisk >= 1.5 ? 'good' : rewardRisk !== null && rewardRisk >= 1 ? 'warn' : 'bad', rewardRisk === null ? 'Requires entry, TP1, and stop' : 'Calculated from TP1 / stop')}
          ${decisionCell('Blocked By', blockReason || 'None', blockReason ? 'bad' : 'good', blockReason ? 'Current blockers are active' : 'No active hard block')}
        </div>
        <div class="hero-note"><strong>Reason:</strong> ${escapeHtml(reasonNarrative)}</div>
        <div class="score-breakdown">
          <div class="score-bar-list">
            ${scoreBar('Strategy Score', strategyScore, signalValidation.total_score === null || signalValidation.total_score === undefined ? 'Validation total score unavailable' : 'Validation score from signal gate')}
            ${scoreBar('AI Support Score', aiSupportScore, ensemble.agreement_score === null || ensemble.agreement_score === undefined ? 'No ensemble agreement stored yet' : 'Ensemble agreement / alignment')}
            ${scoreBar('Risk Score', riskScore, scorer.probability_loss === null || scorer.probability_loss === undefined ? 'Risk score unavailable from scorer output' : 'Inverse loss probability', toneForPercent(riskScore))}
            ${scoreBar('Final Score', finalScore, scorer.expected_return === null || scorer.expected_return === undefined ? 'Expected return unavailable' : `Expected return ${formatPercentFromFraction(scorer.expected_return, 2)}`)}
          </div>
        </div>
      </section>

      <aside class="hero-side">
        <div class="section-kicker">Market Tape</div>
        <div class="section-titlebar">
          <div>
            <h2 class="section-title">Live Quote & Session Context</h2>
            <p class="section-sub">Bid, ask, spread, timeframe, last prediction activity, and current forecast-quality context.</p>
          </div>
          ${chip(priceFreshness.label)}
        </div>
        <div class="quote-grid">
          ${quoteCell('Current Price', resolvedPrice === null ? 'N/A' : fmtNumber(resolvedPrice, 2), titlePriceTime ? fmtDate(titlePriceTime) : 'Latest stored candle close')}
          ${quoteCell('Bid', bid === null ? 'N/A' : fmtNumber(bid, 2), hs.live_source || 'No live source')}
          ${quoteCell('Ask', ask === null ? 'N/A' : fmtNumber(ask, 2), data.selected_resolution || m.resolution || latestSignal.resolution || 'MINUTE')}
          ${quoteCell('Spread', spreadAbs === null ? 'N/A' : fmtNumber(spreadAbs, 4), hs.websocket_stale_alert ? 'Websocket stale alert active' : 'Websocket feed is fresh')}
          ${quoteCell('Last Prediction', fmtDate(hs.last_prediction_time), hs.last_prediction_run_id || 'No run id')}
          ${quoteCell('Last Auto Prediction', fmtDate(hs.last_auto_prediction_time), 'Scheduler heartbeat timestamp')}
        </div>
        <div class="hero-meta-grid" style="margin-top: 14px;">
          ${miniStat('Trend Bias', trendBias, regime.risk_state ? `Risk ${regime.risk_state}` : 'No regime risk state')}
          ${miniStat('Forecast Hit Rate', db.metric_categories?.forecast_quality?.directional_forecast_hit_rate_pct === null || db.metric_categories?.forecast_quality?.directional_forecast_hit_rate_pct === undefined ? 'N/A' : `${Number(db.metric_categories.forecast_quality.directional_forecast_hit_rate_pct).toFixed(2)}%`, `${fmtCount(db.wins ?? 0)} wins / ${fmtCount(db.losses ?? 0)} losses`)}
          ${miniStat('Pending Candles', fmtCount(db.pending ?? 0), 'Awaiting actual candle close')}
          ${miniStat('Expected Return', scorer.expected_return === null || scorer.expected_return === undefined ? 'N/A' : formatPercentFromFraction(scorer.expected_return, 2), modelLabel)}
        </div>
      </aside>
    </div>`;
  const summaryCardsKey = [
    resolvedPrice === null ? 'n/a' : fmtNumber(resolvedPrice),
    titlePriceTime || '',
    decision || 'n/a',
    hs.signal_status || 'PENDING',
    entryPrice === null ? 'n/a' : fmtNumber(entryPrice),
    tp1Price === null ? 'n/a' : fmtNumber(tp1Price),
    stopPrice === null ? 'n/a' : fmtNumber(stopPrice),
    tp2Price === null ? 'n/a' : fmtNumber(tp2Price),
    hs.confidence_pct === null || hs.confidence_pct === undefined ? 'n/a' : fmtNumber(hs.confidence_pct, 2),
    hs.last_prediction_time || '',
    hs.last_prediction_run_id || '',
    hs.last_auto_prediction_time || '',
    db.metric_categories?.forecast_quality?.directional_forecast_hit_rate_pct === null || db.metric_categories?.forecast_quality?.directional_forecast_hit_rate_pct === undefined ? 'n/a' : Number(db.metric_categories.forecast_quality.directional_forecast_hit_rate_pct).toFixed(2),
    String(db.pending ?? 0),
    regime.regime || 'n/a',
    ensemble.ensemble_direction || 'n/a',
    strategyScore === null ? 'n/a' : fmtNumber(strategyScore, 1),
    aiSupportScore === null ? 'n/a' : fmtNumber(aiSupportScore, 1),
    finalScore === null ? 'n/a' : fmtNumber(finalScore, 1),
    riskScore === null ? 'n/a' : fmtNumber(riskScore, 1),
    blockReason || 'none',
    modelLabel,
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
    setErrorBanner('');
    if (showSpinner) showLoader('Refreshing dashboard...');
    const res = await fetch(`/api/status?${currentStatusQuery()}`, { cache: 'no-store' });
    const data = await parseJsonResponse(res);
    if (!res.ok) throw new Error(responseMessage(data, `Status HTTP ${res.status}`));
    try {
      const perfRes = await fetch(`/api/model-performance?${currentStatusQuery()}`, { cache: 'no-store' });
      latestModelPerformance = await parseJsonResponse(perfRes);
      if (!perfRes.ok) latestModelPerformance = null;
    } catch (_err) {
      latestModelPerformance = null;
    }
    await Promise.all([
      refreshSignals(signalPage, { renderUi: false }),
      refreshAiStack(),
    ]);
    render(data, { background, forceOverview: false });
    await maybeAutoPredict();
  } catch (err) {
    setErrorBanner(`Status refresh failed: ${err.message}`);
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
    const data = await parseJsonResponse(res);
    if (!res.ok) {
      const message = responseMessage(data, `HTTP ${res.status}`);
      throw new Error(message);
    }
    if (!silent) {
      setLogText(data.output || data.error || data.message || data);
    }
    if (data.report_url && $('reportFrame') && $('reportLink')) {
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
    setLogText('Running prediction...');
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
      setLogText(err.message);
      setErrorBanner(`Prediction failed: ${err.message}`);
      showToast(`Prediction failed: ${err.message}`);
    } else {
      setErrorBanner(`Auto prediction failed: ${err.message}`);
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
      </tbody></table></div><pre id="auditLog" class="hidden"></pre>`;
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
      dateFrom: '',
      dateTo: '',
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
      dateFrom: '',
      dateTo: '',
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
$('fetchActual').addEventListener('click', async () => {
  try {
    await postJson('/api/fetch-actual', actionContextPayload(), { loaderText: 'Fetching actual candles...' });
    showToast('Actual fetch finished');
  } catch (err) {
    setErrorBanner(`Actual fetch failed: ${err.message}`);
    showToast(`Actual fetch failed: ${err.message}`);
  }
});
$('validateActual').addEventListener('click', async () => {
  try {
    await postJson('/api/validate-actual', actionContextPayload({ scoring_version: 'v1' }), { loaderText: 'Validating actuals...' });
    showToast('Validation finished');
  } catch (err) {
    setErrorBanner(`Validation failed: ${err.message}`);
    showToast(`Validation failed: ${err.message}`);
  }
});
$('runBaselines').addEventListener('click', async () => {
  try {
    await postJson('/api/baselines', actionContextPayload(), { loaderText: 'Running baselines...' });
    showToast('Baselines complete');
  } catch (err) {
    setErrorBanner(`Baselines failed: ${err.message}`);
    showToast(`Baselines failed: ${err.message}`);
  }
});

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
</html>""".replace("__DEFAULT_SYMBOL__", default_symbol)
