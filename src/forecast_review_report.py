from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from forecast_quality_validator import direction_from_move_pct, validate_ohlc_df
from time_utils import display_timezone_name, format_local_timestamp


def _load_csv(path: str | Path, label: str) -> pd.DataFrame:
    return validate_ohlc_df(pd.read_csv(path), label)


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


def _fmt_time(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return html.escape(format_local_timestamp(value))


def _scale(values: list[float], lo: float, hi: float, size: float, invert: bool = False) -> list[float]:
    if hi == lo:
        return [size / 2.0 for _ in values]
    scaled = [((value - lo) / (hi - lo)) * size for value in values]
    if invert:
        return [size - value for value in scaled]
    return scaled


def _line_svg(series: dict[str, list[float]], title: str, height: int = 260, width: int = 920) -> str:
    all_values = [value for values in series.values() for value in values]
    if not all_values:
        return f"<p>No data for {html.escape(title)}.</p>"
    pad = 36
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    lo = min(all_values)
    hi = max(all_values)
    if lo == hi:
        lo -= 1
        hi += 1
    n = max(len(values) for values in series.values())
    x_values = _scale(list(range(n)), 0, max(n - 1, 1), plot_w)
    colors = ["#2563eb", "#dc2626", "#059669", "#7c3aed"]
    paths: list[str] = []
    labels: list[str] = []
    for idx, (name, values) in enumerate(series.items()):
        y_values = _scale(values, lo, hi, plot_h, invert=True)
        points = " ".join(f"{pad + x_values[i]:.2f},{pad + y_values[i]:.2f}" for i in range(len(values)))
        color = colors[idx % len(colors)]
        paths.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" />')
        labels.append(
            f'<span class="legend-item"><span style="background:{color}"></span>{html.escape(name)}</span>'
        )
    return f"""
    <section class="panel">
      <h2>{html.escape(title)}</h2>
      <div class="legend">{''.join(labels)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#94a3b8" />
        <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#94a3b8" />
        <text x="{pad}" y="22" fill="#475569" font-size="12">{hi:.4f}</text>
        <text x="{pad}" y="{height-8}" fill="#475569" font-size="12">{lo:.4f}</text>
        {''.join(paths)}
      </svg>
    </section>
    """


def _bar_svg(values: list[float], title: str, height: int = 240, width: int = 920) -> str:
    if not values:
        return f"<p>No data for {html.escape(title)}.</p>"
    pad = 36
    plot_w = width - pad * 2
    plot_h = height - pad * 2
    max_abs = max(abs(value) for value in values) or 1.0
    zero_y = pad + plot_h / 2
    bar_w = max(plot_w / len(values) * 0.7, 2)
    pieces: list[str] = []
    for i, value in enumerate(values):
        x = pad + (plot_w / len(values)) * i
        h = abs(value) / max_abs * (plot_h / 2)
        y = zero_y - h if value >= 0 else zero_y
        color = "#dc2626" if value >= 0 else "#2563eb"
        pieces.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{color}" />')
    return f"""
    <section class="panel">
      <h2>{html.escape(title)}</h2>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <line x1="{pad}" y1="{zero_y}" x2="{width-pad}" y2="{zero_y}" stroke="#94a3b8" />
        {''.join(pieces)}
      </svg>
    </section>
    """


def _metrics_table(metadata: dict[str, Any], quality: dict[str, Any]) -> str:
    q = quality.get("forecast_quality_validation", quality)
    items = {
        "Epic": metadata.get("epic"),
        "Market": metadata.get("market_name"),
        "Resolution": q.get("resolution") or metadata.get("resolution"),
        "Price side": q.get("price_side") or metadata.get("price_side"),
        "Input rows": metadata.get("input_rows_used"),
        "Forecast rows": metadata.get("forecast_rows"),
        "Horizon minutes": metadata.get("forecast_horizon_minutes") or q.get("forecast_horizon_minutes"),
        "MAE": q.get("mae"),
        "RMSE": q.get("rmse"),
        "MAPE %": q.get("mape_pct"),
        "Direction accuracy %": q.get("direction_accuracy_pct"),
        "Bias": q.get("forecast_bias"),
        "Quality": q.get("quality_status"),
    }
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{_fmt(v)}</td></tr>" for k, v in items.items())
    return f"<section class='panel'><h2>Summary</h2><table>{rows}</table></section>"


def _direction_table(joined: pd.DataFrame, flat_threshold_pct: float = 0.02) -> str:
    rows: list[str] = []
    actual_prev = joined["close_actual"].shift(1)
    for idx, row in joined.iterrows():
        if pd.isna(row.get("close_actual")):
            status = "missing actual"
            actual_dir = "n/a"
            forecast_dir = "n/a"
        elif idx == 0 or pd.isna(actual_prev.iloc[idx]):
            status = "no previous actual"
            actual_dir = "n/a"
            forecast_dir = "n/a"
        else:
            prev = float(actual_prev.iloc[idx])
            actual_move = ((float(row["close_actual"]) / prev) - 1.0) * 100.0
            forecast_move = ((float(row["close_forecast"]) / prev) - 1.0) * 100.0
            actual_dir = direction_from_move_pct(actual_move, flat_threshold_pct)
            forecast_dir = direction_from_move_pct(forecast_move, flat_threshold_pct)
            status = "hit" if actual_dir == forecast_dir else "miss"
        rows.append(
            "<tr>"
            f"<td>{_fmt_time(row['timestamps'])}</td>"
            f"<td>{_fmt(row.get('close_forecast'))}</td>"
            f"<td>{_fmt(row.get('close_actual'))}</td>"
            f"<td>{html.escape(forecast_dir)}</td>"
            f"<td>{html.escape(actual_dir)}</td>"
            f"<td>{html.escape(status)}</td>"
            "</tr>"
        )
    return (
        "<section class='panel'><h2>Direction Review</h2><table>"
        "<tr><th>Timestamp</th><th>Forecast close</th><th>Actual close</th>"
        "<th>Forecast direction</th><th>Actual direction</th><th>Status</th></tr>"
        f"{''.join(rows)}</table></section>"
    )


def generate_forecast_review_html(
    forecast_csv_path: str | Path,
    actual_csv_path: str | Path,
    metadata_json_path: str | Path | None,
    quality_report_json_path: str | Path | None,
    output_html_path: str | Path,
) -> Path:
    forecast = _load_csv(forecast_csv_path, "forecast")
    actual = _load_csv(actual_csv_path, "actual")
    metadata = _load_json(metadata_json_path)
    quality = _load_json(quality_report_json_path)
    joined = forecast.merge(actual, on="timestamps", how="left", suffixes=("_forecast", "_actual"))
    matched = joined.dropna(subset=["close_actual"]).copy()
    errors = (matched["close_forecast"] - matched["close_actual"]).tolist()
    abs_errors = [abs(value) for value in errors]
    cumulative_abs = pd.Series(abs_errors).cumsum().tolist()

    missing = joined[joined["close_actual"].isna()]
    missing_rows = "".join(f"<li>{_fmt_time(ts)}</li>" for ts in missing["timestamps"].tolist())
    missing_html = (
        f"<section class='panel'><h2>Missing Actual Candles</h2><ul>{missing_rows}</ul></section>"
        if missing_rows
        else "<section class='panel'><h2>Missing Actual Candles</h2><p>None.</p></section>"
    )

    close_chart = _line_svg(
        {
            "Forecast close": joined["close_forecast"].astype(float).tolist(),
            "Actual close": joined["close_actual"].dropna().astype(float).tolist(),
        },
        "Forecast Close vs Actual Close",
    )
    error_chart = _bar_svg(errors, "Forecast Error Over Time")
    abs_chart = _line_svg({"Cumulative absolute error": cumulative_abs}, "Cumulative Absolute Error")
    volume_chart = _line_svg(
        {
            "Forecast volume": joined["volume_forecast"].astype(float).tolist(),
            "Actual volume": joined["volume_actual"].dropna().astype(float).tolist(),
        },
        "Volume Context",
    )

    q = quality.get("forecast_quality_validation", quality)
    tradability = (
        "Movement appears too small after configured costs."
        if q.get("quality_status") == "NOT_TRADABLE"
        else "Use this report for analysis only; it is not an execution signal."
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Forecast Review</title>
  <style>
    :root {{ color-scheme: dark; --bg:#0b0f1a; --surface:#121826; --line:rgba(148,163,184,.20); --text:#eef2ff; --muted:#9aa8bd; --cyan:#27d3d8; --blue:#62a8ff; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: Inter, Segoe UI, Arial, sans-serif; margin: 0; color: var(--text); background: radial-gradient(circle at 18% 0%, rgba(39,211,216,.18), transparent 28rem), linear-gradient(135deg, #08111e, var(--bg)); }}
    header {{ padding: 30px 36px; background: rgba(10,15,27,.88); border-bottom: 1px solid var(--line); color: var(--text); }}
    main {{ padding: 24px 36px; max-width: 1100px; margin: auto; }}
    .panel {{ background: linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.035)); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin: 16px 0; box-shadow: 0 18px 50px rgba(0,0,0,.30); }}
    h1, h2 {{ margin: 0 0 12px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid rgba(148,163,184,.16); text-align: left; padding: 10px; font-size: 14px; }}
    th {{ color: var(--muted); width: 240px; }}
    svg {{ width: 100%; height: auto; display: block; }}
    .legend {{ display: flex; gap: 16px; margin-bottom: 8px; color: var(--muted); }}
    .legend-item span {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; border-radius: 999px; }}
    .note {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Forecast Review</h1>
    <p class="note">{html.escape(str(metadata.get('epic', 'UNKNOWN')))} {html.escape(str(metadata.get('resolution', '')))} | Times shown in {html.escape(display_timezone_name())}</p>
  </header>
  <main>
    {_metrics_table(metadata, quality)}
    <section class="panel"><h2>Tradability Notes</h2><p>{html.escape(tradability)}</p></section>
    {close_chart}
    {error_chart}
    {abs_chart}
    {volume_chart}
    {_direction_table(joined)}
    {missing_html}
  </main>
</body>
</html>"""
    output = Path(output_html_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output
