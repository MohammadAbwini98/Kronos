from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from time_utils import display_timezone_name, format_local_timestamp


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return html.escape(str(value))


def _scale(values: list[float], lo: float, hi: float, size: float, invert: bool = False) -> list[float]:
    if hi == lo:
        return [size / 2 for _ in values]
    scaled = [((value - lo) / (hi - lo)) * size for value in values]
    return [size - value for value in scaled] if invert else scaled


def _line_svg(series: dict[str, list[float]], title: str, width: int = 920, height: int = 260) -> str:
    all_values = [value for values in series.values() for value in values]
    if not all_values:
        return ""
    pad = 36
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    lo = min(all_values)
    hi = max(all_values)
    if lo == hi:
        lo -= 1
        hi += 1
    n = max(len(values) for values in series.values())
    xs = _scale(list(range(n)), 0, max(n - 1, 1), plot_w)
    colors = ["#2563eb", "#dc2626", "#059669"]
    paths = []
    labels = []
    for idx, (name, values) in enumerate(series.items()):
        ys = _scale(values, lo, hi, plot_h, invert=True)
        points = " ".join(f"{pad + xs[i]:.2f},{pad + ys[i]:.2f}" for i in range(len(values)))
        color = colors[idx % len(colors)]
        paths.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" />')
        labels.append(f'<span class="legend-item"><span style="background:{color}"></span>{html.escape(name)}</span>')
    return f"""
    <section class="panel">
      <h2>{html.escape(title)}</h2>
      <div class="legend">{''.join(labels)}</div>
      <svg viewBox="0 0 {width} {height}">
        <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#94a3b8" />
        <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#94a3b8" />
        <text x="{pad}" y="22" fill="#475569" font-size="12">{hi:.4f}</text>
        <text x="{pad}" y="{height-8}" fill="#475569" font-size="12">{lo:.4f}</text>
        {''.join(paths)}
      </svg>
    </section>
    """


def _summary(metadata: dict[str, Any], validation: dict[str, Any]) -> str:
    v = validation.get("forecast_quality_validation", validation)
    items = {
        "Epic": metadata.get("epic"),
        "Market": metadata.get("market_name"),
        "Resolution": metadata.get("resolution") or v.get("resolution"),
        "Price side": metadata.get("price_side") or v.get("price_side"),
        "Generated": metadata.get("generated_at_local"),
        "Input end": metadata.get("input_end_timestamp"),
        "Forecast start": metadata.get("forecast_start_timestamp"),
        "Forecast end": metadata.get("forecast_end_timestamp"),
        "Input rows used": metadata.get("input_rows_used") or v.get("input_rows_used"),
        "Forecast rows": metadata.get("forecast_rows") or v.get("forecast_rows"),
        "Forecast direction": v.get("forecast_direction"),
        "Last input close": metadata.get("last_input_close") or v.get("last_input_close"),
        "First forecast close": v.get("first_forecast_close"),
        "Last forecast close": v.get("last_forecast_close"),
        "Max close deviation %": v.get("max_abs_close_move_pct"),
    }
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{_fmt(val)}</td></tr>" for k, val in items.items())
    return f"<section class='panel'><h2>Prediction Summary</h2><table>{rows}</table></section>"


def _forecast_table(df: pd.DataFrame) -> str:
    rows = []
    for _, row in df.iterrows():
        rows.append(
            "<tr>"
            f"<td>{html.escape(format_local_timestamp(row['timestamps']))}</td>"
            f"<td>{_fmt(float(row['open']))}</td>"
            f"<td>{_fmt(float(row['high']))}</td>"
            f"<td>{_fmt(float(row['low']))}</td>"
            f"<td>{_fmt(float(row['close']))}</td>"
            f"<td>{_fmt(float(row['volume']))}</td>"
            "</tr>"
        )
    return (
        "<section class='panel'><h2>Forecast Candles</h2><table>"
        "<tr><th>Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr>"
        f"{''.join(rows)}</table></section>"
    )


def generate_prediction_log_report(
    forecast_csv_path: str | Path,
    metadata_json_path: str | Path | None,
    validation_json_path: str | Path | None,
    output_html_path: str | Path,
) -> Path:
    forecast = pd.read_csv(forecast_csv_path)
    forecast["timestamps"] = pd.to_datetime(forecast["timestamps"], utc=True)
    metadata = _load_json(metadata_json_path)
    validation = _load_json(validation_json_path)
    close_values = forecast["close"].astype(float).tolist()
    volume_values = forecast["volume"].astype(float).tolist()
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Prediction Log Report</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b0f1a; --surface:#121826; --line:rgba(148,163,184,.20); --text:#eef2ff; --muted:#9aa8bd; --cyan:#27d3d8; --blue:#62a8ff; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; color: var(--text); background: radial-gradient(circle at 18% 0%, rgba(39,211,216,.18), transparent 28rem), linear-gradient(135deg, #08111e, var(--bg)); }}
    header {{ border-bottom: 1px solid var(--line); background: rgba(10,15,27,.86); padding: 30px 36px; }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 44px); }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    .panel {{ background: linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.035)); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin: 16px 0; box-shadow: 0 18px 50px rgba(0,0,0,.30); }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid rgba(148,163,184,.16); padding: 10px; text-align: left; font-size: 14px; }}
    th {{ color: var(--muted); }}
    svg {{ width: 100%; height: auto; }}
    .legend {{ display: flex; gap: 16px; margin-bottom: 8px; color: var(--muted); }}
    .legend-item span {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; border-radius: 999px; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Prediction Log Report</h1>
    <div class="muted">Times shown in {html.escape(display_timezone_name())}. Analytical report only; no trading actions.</div>
  </header>
  <main>
    {_summary(metadata, validation)}
    {_line_svg({"Forecast close": close_values}, "Forecast Close Path")}
    {_line_svg({"Forecast volume": volume_values}, "Forecast Volume Path")}
    {_forecast_table(forecast)}
  </main>
</body>
</html>"""
    output = Path(output_html_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output
