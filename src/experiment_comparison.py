from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def build_experiment_comparison(index_csv_path: str | Path, output_json_path: str | Path) -> dict[str, Any]:
    path = Path(index_csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Forecast runs index does not exist: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Forecast runs index is empty")
    for col in ("mae", "rmse", "mape_pct", "direction_accuracy_pct", "forecast_horizon_minutes"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    def group(cols: list[str]) -> list[dict[str, Any]]:
        grouped = (
            df.groupby(cols, dropna=False)
            .agg(
                runs=("quality_report_path", "count"),
                avg_mae=("mae", "mean"),
                avg_rmse=("rmse", "mean"),
                avg_mape=("mape_pct", "mean"),
                avg_direction_accuracy=("direction_accuracy_pct", "mean"),
            )
            .reset_index()
        )
        return grouped.to_dict(orient="records")

    report: dict[str, Any] = {
        "experiment_comparison": {
            "total_runs": int(len(df)),
            "by_resolution": group(["resolution"]),
            "by_horizon": group(["forecast_horizon_minutes"]),
            "by_price_side": group(["price_side"]),
            "by_resolution_horizon_price_side": group(["resolution", "forecast_horizon_minutes", "price_side"]),
        }
    }
    valid = df.dropna(subset=["mape_pct"])
    if not valid.empty:
        best = valid.sort_values(["mape_pct", "direction_accuracy_pct"], ascending=[True, False]).iloc[0]
        report["experiment_comparison"]["best_run"] = best.to_dict()
    output = Path(output_json_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
