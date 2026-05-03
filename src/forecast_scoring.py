from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SCORING_VERSION = "v1"
DEFAULT_FLAT_THRESHOLD_PCT = 0.02
DEFAULT_COST_THRESHOLD_PCT = 0.05


def direction_from_move_pct(move_pct: float, flat_threshold_pct: float = 0.02) -> str:
    if not math.isfinite(float(move_pct)):
        return "FLAT"
    if abs(float(move_pct)) < flat_threshold_pct:
        return "FLAT"
    return "UP" if float(move_pct) > 0 else "DOWN"


def direction_from_prices(anchor_close: float, close: float, flat_threshold_pct: float = 0.02) -> str:
    anchor = float(anchor_close)
    value = float(close)
    if not math.isfinite(anchor) or not math.isfinite(value) or anchor == 0:
        return "FLAT"
    move_pct = ((value / anchor) - 1.0) * 100.0
    return direction_from_move_pct(move_pct, flat_threshold_pct)


def move_pct_from_prices(anchor_close: float | None, close: float | None) -> float | None:
    if anchor_close is None or close is None:
        return None
    anchor = float(anchor_close)
    value = float(close)
    if not math.isfinite(anchor) or not math.isfinite(value) or anchor == 0:
        return None
    return ((value / anchor) - 1.0) * 100.0


def _clean_close_frame(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if "timestamps" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{label} requires timestamps and close columns")
    clean = df[["timestamps", "close"]].copy()
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    clean["close"] = pd.to_numeric(clean["close"], errors="coerce")
    clean = clean.dropna(subset=["timestamps", "close"])
    clean = clean.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return clean


def _safe_pct_error(error: float, actual_close: float) -> float | None:
    if actual_close == 0:
        return None
    return (error / actual_close) * 100.0


def _mean(values: list[float]) -> float | None:
    return None if not values else float(np.mean(values))


def score_forecast_against_actuals(
    forecast_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    *,
    last_input_close: float | None = None,
    flat_threshold_pct: float = 0.02,
    cost_threshold_pct: float = 0.05,
) -> dict[str, Any]:
    """Score forecast candles against actual candles using one anchoring model.

    Forecast direction is measured from the previous forecast close, with the
    first horizon anchored to last_input_close when it is available. Actual
    direction is measured from the previous actual close, with the first horizon
    anchored to last_input_close when it is available.
    """
    forecast = _clean_close_frame(forecast_df, "forecast")
    actual = _clean_close_frame(actual_df, "actual")
    actual_by_ts = {row["timestamps"].isoformat(): float(row["close"]) for _, row in actual.iterrows()}

    forecast_anchor = None if last_input_close is None else float(last_input_close)
    actual_anchor = None if last_input_close is None else float(last_input_close)

    rows: list[dict[str, Any]] = []
    wins = losses = missing_actual = direction_pending = 0
    errors: list[float] = []
    abs_errors: list[float] = []
    pct_errors: list[float] = []
    expected_moves: list[float] = []
    realized_moves: list[float] = []
    movement_after_cost: list[float] = []

    for index, forecast_row in forecast.iterrows():
        ts = forecast_row["timestamps"].isoformat()
        forecast_close = float(forecast_row["close"])
        row_forecast_anchor = forecast_anchor
        row_actual_anchor = actual_anchor
        expected_move_pct = move_pct_from_prices(row_forecast_anchor, forecast_close)
        predicted_direction = (
            None
            if expected_move_pct is None
            else direction_from_move_pct(expected_move_pct, flat_threshold_pct)
        )
        actual_close = actual_by_ts.get(ts)
        actual_direction = None
        realized_move_pct = None
        close_error = None
        close_error_pct = None
        status = "PENDING"
        after_cost = None

        if actual_close is None:
            missing_actual += 1
        else:
            realized_move_pct = move_pct_from_prices(row_actual_anchor, actual_close)
            actual_direction = (
                None
                if realized_move_pct is None
                else direction_from_move_pct(realized_move_pct, flat_threshold_pct)
            )
            close_error = forecast_close - actual_close
            close_error_pct = _safe_pct_error(close_error, actual_close)
            errors.append(close_error)
            abs_errors.append(abs(close_error))
            if close_error_pct is not None:
                pct_errors.append(abs(close_error_pct))
            if expected_move_pct is not None:
                expected_moves.append(abs(expected_move_pct))
            if realized_move_pct is not None:
                realized_moves.append(abs(realized_move_pct))
            if predicted_direction is None or actual_direction is None:
                direction_pending += 1
            else:
                signed_realized = realized_move_pct if predicted_direction == "UP" else -realized_move_pct
                if predicted_direction == "FLAT":
                    signed_realized = -abs(realized_move_pct)
                after_cost = signed_realized - cost_threshold_pct
                movement_after_cost.append(after_cost)
                status = "WIN" if predicted_direction == actual_direction else "LOSS"
                if status == "WIN":
                    wins += 1
                else:
                    losses += 1
            actual_anchor = actual_close

        rows.append(
            {
                "horizon_index": int(index) + 1,
                "timestamp_utc": ts,
                "forecast_close": forecast_close,
                "actual_close": actual_close,
                "forecast_anchor_close": row_forecast_anchor,
                "actual_anchor_close": row_actual_anchor,
                "expected_move_pct": expected_move_pct,
                "realized_move_pct": realized_move_pct,
                "predicted_direction": predicted_direction,
                "actual_direction": actual_direction,
                "close_error": close_error,
                "close_error_pct": close_error_pct,
                "movement_after_cost_pct": after_cost,
                "status": status,
            }
        )
        forecast_anchor = forecast_close

    validated = wins + losses
    total_rows = int(len(forecast))
    matched_candles = total_rows - missing_actual
    summary = {
        "total_rows": total_rows,
        "matched_candles": matched_candles,
        "missing_actual_candles": missing_actual,
        "direction_pending": direction_pending,
        "pending": missing_actual + direction_pending,
        "validated": validated,
        "wins": wins,
        "losses": losses,
        "status": "PENDING" if validated == 0 else ("WIN" if wins >= losses else "LOSS"),
        "direction_accuracy_pct": None if validated == 0 else (wins / validated) * 100.0,
        "direction_matches": wins,
        "direction_comparable_candles": validated,
        "mae": _mean(abs_errors),
        "rmse": None if not errors else float(math.sqrt(float(np.mean(np.square(errors))))),
        "mape_pct": _mean(pct_errors),
        "average_forecast_error": _mean(errors),
        "max_abs_error": None if not abs_errors else float(max(abs_errors)),
        "max_abs_percentage_error": None if not pct_errors else float(max(pct_errors)),
        "expected_movement_pct": _mean(expected_moves),
        "realized_movement_pct": _mean(realized_moves),
        "average_movement_after_cost_pct": _mean(movement_after_cost),
    }
    return {"summary": summary, "rows": rows}


def signal_status_from_counts(wins: int, losses: int) -> str:
    validated = int(wins) + int(losses)
    if validated <= 0:
        return "PENDING"
    return "WIN" if int(wins) >= int(losses) else "LOSS"


def score_signal_quality(
    *,
    signal: str,
    confidence: float,
    expected_move_pct: float,
    cost_threshold_pct: float,
    scoring_summary: dict[str, Any],
) -> dict[str, Any]:
    signal_text = str(signal or "HOLD").upper()
    actionable = signal_text in {"LONG", "SHORT"}
    realized_move_pct = scoring_summary.get("realized_movement_pct")
    status = str(scoring_summary.get("status") or "PENDING").upper()
    movement_after_cost_pct = scoring_summary.get("average_movement_after_cost_pct")
    false_positive = None
    hold_quality = None
    if actionable and status in {"WIN", "LOSS"}:
        false_positive = status == "LOSS"
    if not actionable and realized_move_pct is not None:
        hold_quality = "GOOD_HOLD" if abs(float(realized_move_pct)) < float(cost_threshold_pct) else "MISSED_MOVE"
    precision_bucket = None
    if actionable:
        accuracy = scoring_summary.get("direction_accuracy_pct")
        if accuracy is None:
            precision_bucket = "PENDING"
        elif float(accuracy) >= 60.0:
            precision_bucket = "HIGH"
        elif float(accuracy) >= 50.0:
            precision_bucket = "MEDIUM"
        else:
            precision_bucket = "LOW"
    return {
        "signal": signal_text,
        "status": status,
        "actionable": actionable,
        "confidence": float(confidence),
        "expected_move_pct": float(expected_move_pct),
        "realized_move_pct": realized_move_pct,
        "cost_threshold_pct": float(cost_threshold_pct),
        "movement_after_cost_pct": movement_after_cost_pct,
        "precision_bucket": precision_bucket,
        "false_positive": false_positive,
        "hold_quality": hold_quality,
    }
