from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _read_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "forecast_quality_validation" not in data:
        raise ValueError(f"Report missing forecast_quality_validation: {path}")
    return data["forecast_quality_validation"]


def _mean(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _group_summary(reports: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        grouped[str(report.get(key, "UNKNOWN"))].append(report)
    return {name: _aggregate_reports(items, include_groups=False) for name, items in grouped.items()}


def _aggregate_reports(reports: list[dict[str, Any]], include_groups: bool = True) -> dict[str, Any]:
    total_matched = sum(int(report.get("matched_candles") or 0) for report in reports)
    summary: dict[str, Any] = {
        "total_forecasts_evaluated": len(reports),
        "total_matched_candles": total_matched,
        "average_mae": _mean([report.get("mae") for report in reports]),
        "average_rmse": _mean([report.get("rmse") for report in reports]),
        "average_mape": _mean([report.get("mape_pct") for report in reports]),
        "average_direction_accuracy": _mean([report.get("direction_accuracy_pct") for report in reports]),
    }
    if not include_groups:
        return summary

    summary["performance_by_resolution"] = _group_summary(reports, "resolution")
    summary["performance_by_forecast_horizon"] = _group_summary(reports, "forecast_horizon_minutes")
    summary["performance_by_price_side"] = _group_summary(reports, "price_side")

    resolution_perf = summary["performance_by_resolution"]
    scored = [
        (name, values.get("average_mape"), values.get("average_direction_accuracy"))
        for name, values in resolution_perf.items()
        if values.get("average_mape") is not None
    ]
    if scored:
        summary["best_resolution"] = sorted(scored, key=lambda item: (item[1], -(item[2] or 0.0)))[0][0]
        summary["worst_resolution"] = sorted(scored, key=lambda item: (item[1], -(item[2] or 0.0)), reverse=True)[0][0]
    else:
        summary["best_resolution"] = None
        summary["worst_resolution"] = None

    avg_dir = summary["average_direction_accuracy"]
    avg_mape = summary["average_mape"]
    if len(reports) < 5 or total_matched < 30:
        status = "NEEDS_MORE_SAMPLES"
    elif avg_dir is not None and avg_mape is not None and avg_dir >= 60.0 and avg_mape <= 0.25:
        status = "PROMISING"
    elif avg_dir is not None and avg_dir < 50.0:
        status = "WEAK"
    else:
        status = "NEEDS_MORE_SAMPLES"
    summary["overall_quality_status"] = status
    return summary


def build_cumulative_report(report_paths: list[str | Path]) -> dict[str, Any]:
    paths = [Path(path) for path in report_paths]
    reports = [_read_report(path) for path in paths]
    summary = _aggregate_reports(reports)
    summary["source_reports"] = [str(path) for path in paths]
    return {"cumulative_forecast_quality_report": summary}


def scan_and_build_cumulative_report(input_dir: str | Path = "output", pattern: str = "forecast_quality_report_*.json") -> dict[str, Any]:
    paths = sorted(Path(input_dir).glob(pattern))
    if not paths:
        raise FileNotFoundError(f"No forecast quality reports found in {input_dir} matching {pattern}")
    return build_cumulative_report(paths)
