from __future__ import annotations

from typing import Any


def summarize_validation_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "avg_direction_accuracy": None,
            "avg_mae": None,
            "avg_rmse": None,
            "best_model": None,
        }

    def _mean(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    accuracies = [float(row["direction_accuracy"]) for row in rows if row.get("direction_accuracy") is not None]
    maes = [float(row["mae"]) for row in rows if row.get("mae") is not None]
    rmses = [float(row["rmse"]) for row in rows if row.get("rmse") is not None]

    best = None
    if accuracies:
        best = max(
            (row for row in rows if row.get("direction_accuracy") is not None),
            key=lambda row: float(row["direction_accuracy"]),
            default=None,
        )

    return {
        "rows": len(rows),
        "avg_direction_accuracy": _mean(accuracies),
        "avg_mae": _mean(maes),
        "avg_rmse": _mean(rmses),
        "best_model": None if best is None else best.get("model_key"),
    }
