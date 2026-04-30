from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


INDEX_COLUMNS = [
    "epic",
    "resolution",
    "price_side",
    "model_name",
    "generated_at_utc",
    "generated_at_local",
    "display_timezone",
    "forecast_horizon_minutes",
    "quality_status",
    "mae",
    "rmse",
    "mape_pct",
    "direction_accuracy_pct",
    "input_csv_path",
    "forecast_csv_path",
    "metadata_json_path",
    "actual_csv_path",
    "quality_report_path",
]


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def append_forecast_run_index(
    index_path: str | Path,
    *,
    metadata_path: str | Path | None,
    quality_report_path: str | Path | None,
    actual_csv_path: str | Path | None = None,
) -> Path:
    metadata = _load_json(metadata_path)
    quality = _load_json(quality_report_path).get("forecast_quality_validation", {})
    row = {
        "epic": metadata.get("epic", ""),
        "resolution": quality.get("resolution") or metadata.get("resolution", ""),
        "price_side": quality.get("price_side") or metadata.get("price_side", ""),
        "model_name": metadata.get("model_name", ""),
        "generated_at_utc": metadata.get("generated_at_utc", ""),
        "generated_at_local": metadata.get("generated_at_local", ""),
        "display_timezone": metadata.get("display_timezone", ""),
        "forecast_horizon_minutes": quality.get("forecast_horizon_minutes")
        or metadata.get("forecast_horizon_minutes", ""),
        "quality_status": quality.get("quality_status", ""),
        "mae": quality.get("mae", ""),
        "rmse": quality.get("rmse", ""),
        "mape_pct": quality.get("mape_pct", ""),
        "direction_accuracy_pct": quality.get("direction_accuracy_pct", ""),
        "input_csv_path": metadata.get("input_csv_path", ""),
        "forecast_csv_path": metadata.get("forecast_csv_path", ""),
        "metadata_json_path": str(metadata_path or ""),
        "actual_csv_path": str(actual_csv_path or ""),
        "quality_report_path": str(quality_report_path or ""),
    }
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return path
