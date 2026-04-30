from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trading_usefulness import analyze_trading_usefulness
from time_utils import display_timezone_name, format_local_timestamp

KRONOS_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]
SUPPORTED_RESOLUTIONS = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}


class ForecastQualityError(ValueError):
    """Raised when forecast quality validation cannot be performed."""


def direction_from_move_pct(move_pct: float, flat_threshold_pct: float = 0.02) -> str:
    if abs(move_pct) < flat_threshold_pct:
        return "FLAT"
    return "UP" if move_pct > 0 else "DOWN"


def validate_ohlc_df(df: pd.DataFrame, label: str) -> pd.DataFrame:
    missing = [col for col in KRONOS_COLUMNS if col not in df.columns]
    if missing:
        raise ForecastQualityError(f"{label} missing required columns: {', '.join(missing)}")
    clean = df.copy()
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    clean = clean.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    if clean[["open", "high", "low", "close"]].isna().any().any():
        raise ForecastQualityError(f"{label} contains null OHLC values")
    if not np.isfinite(clean[["open", "high", "low", "close"]].to_numpy()).all():
        raise ForecastQualityError(f"{label} contains non-finite OHLC values")
    invalid_ohlc = (
        (clean["high"] < clean[["open", "low", "close"]].max(axis=1))
        | (clean["low"] > clean[["open", "high", "close"]].min(axis=1))
    )
    if invalid_ohlc.any():
        raise ForecastQualityError(f"{label} has {int(invalid_ohlc.sum())} OHLC invariant violation(s)")
    return clean


def _load_csv(path: str | Path, label: str) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"{label} CSV does not exist: {source}")
    return validate_ohlc_df(pd.read_csv(source), label)


def _safe_mape(abs_error: pd.Series, actual_close: pd.Series) -> pd.Series:
    denominator = actual_close.abs().replace(0, np.nan)
    return (abs_error / denominator) * 100.0


def _quality_status(
    matched_candles: int,
    direction_accuracy_pct: float | None,
    mape_pct: float | None,
    expected_movement_pct: float | None,
    acceptable_mape_pct: float,
) -> str:
    if matched_candles < 30:
        return "NEEDS_MORE_SAMPLES"
    if direction_accuracy_pct is None or mape_pct is None:
        return "NEEDS_MORE_SAMPLES"
    if expected_movement_pct is not None and expected_movement_pct > 0 and mape_pct > expected_movement_pct:
        return "NOT_TRADABLE"
    if direction_accuracy_pct >= 60.0 and mape_pct <= acceptable_mape_pct:
        return "PROMISING"
    if direction_accuracy_pct < 50.0:
        return "WEAK"
    return "NEEDS_MORE_SAMPLES"


def _bias(avg_error: float | None, neutral_abs_threshold: float) -> str:
    if avg_error is None or abs(avg_error) <= neutral_abs_threshold:
        return "neutral"
    return "over-predicting" if avg_error > 0 else "under-predicting"


def validate_forecast_quality(
    forecast_csv_path: str,
    actual_csv_path: str,
    resolution: str,
    price_side: str = "mid",
    *,
    flat_threshold_pct: float = 0.02,
    acceptable_mape_pct: float = 0.25,
    cost_threshold_pct: float = 0.05,
) -> dict[str, Any]:
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ForecastQualityError(f"Unsupported resolution: {resolution}")
    if price_side not in {"bid", "ask", "mid"}:
        raise ForecastQualityError(f"Unsupported price side: {price_side}")

    forecast = _load_csv(forecast_csv_path, "forecast")
    actual = _load_csv(actual_csv_path, "actual")
    actual_available = actual.dropna(subset=["close"]).copy()

    merged = forecast.merge(actual_available, on="timestamps", how="left", suffixes=("_forecast", "_actual"))
    matched = merged.dropna(subset=["close_actual"]).copy()
    missing_actual = merged[merged["close_actual"].isna()].copy()

    missing_actual_timestamps = [format_local_timestamp(ts) for ts in missing_actual["timestamps"].tolist()]
    matched_candles = int(len(matched))
    unmatched_forecast_candles = int(len(forecast) - matched_candles)

    metrics: dict[str, Any] = {
        "forecast_quality_validation": {
            "resolution": resolution,
            "price_side": price_side,
            "display_timezone": display_timezone_name(),
            "forecast_horizon_candles": int(len(forecast)),
            "forecast_horizon_minutes": int(len(forecast) * SUPPORTED_RESOLUTIONS[resolution]),
            "matched_candles": matched_candles,
            "missing_actual_candles": int(len(missing_actual)),
            "unmatched_forecast_candles": unmatched_forecast_candles,
            "missing_actual_timestamps": missing_actual_timestamps,
        }
    }
    report = metrics["forecast_quality_validation"]
    if matched_candles == 0:
        report.update(
            {
                "mae": None,
                "rmse": None,
                "mape_pct": None,
                "close_direction_accuracy_pct": None,
                "direction_accuracy_pct": None,
                "average_forecast_error": None,
                "max_abs_error": None,
                "max_abs_percentage_error": None,
                "forecast_bias": "neutral",
                "expected_movement_pct": None,
                "trading_usefulness": analyze_trading_usefulness(
                    matched,
                    flat_threshold_pct=flat_threshold_pct,
                    cost_threshold_pct=cost_threshold_pct,
                ),
                "quality_status": "NEEDS_MORE_SAMPLES",
            }
        )
        return metrics

    error = matched["close_forecast"] - matched["close_actual"]
    abs_error = error.abs()
    pct_error = _safe_mape(abs_error, matched["close_actual"])
    mae = float(abs_error.mean())
    rmse = float(math.sqrt(float((error**2).mean())))
    mape_pct = float(pct_error.mean())
    max_abs_error = float(abs_error.max())
    max_abs_percentage_error = float(pct_error.max())
    average_forecast_error = float(error.mean())

    actual_with_prev = actual_available[["timestamps", "close"]].rename(columns={"close": "previous_actual_close"})
    actual_with_prev["previous_actual_close"] = actual_with_prev["previous_actual_close"].shift(1)
    matched = matched.merge(actual_with_prev, on="timestamps", how="left")
    direction_rows = matched.dropna(subset=["previous_actual_close"]).copy()
    direction_accuracy_pct: float | None = None
    expected_movement_pct: float | None = None
    direction_matches = 0
    direction_total = int(len(direction_rows))
    if direction_total > 0:
        forecast_move_pct = ((direction_rows["close_forecast"] / direction_rows["previous_actual_close"]) - 1.0) * 100.0
        actual_move_pct = ((direction_rows["close_actual"] / direction_rows["previous_actual_close"]) - 1.0) * 100.0
        forecast_dir = forecast_move_pct.apply(lambda value: direction_from_move_pct(float(value), flat_threshold_pct))
        actual_dir = actual_move_pct.apply(lambda value: direction_from_move_pct(float(value), flat_threshold_pct))
        direction_matches = int((forecast_dir == actual_dir).sum())
        direction_accuracy_pct = float((direction_matches / direction_total) * 100.0)
        expected_movement_pct = float(forecast_move_pct.abs().mean())

    neutral_threshold = max(float(matched["close_actual"].mean()) * acceptable_mape_pct / 100.0 * 0.1, 1e-9)
    report.update(
        {
            "mae": mae,
            "rmse": rmse,
            "mape_pct": mape_pct,
            "close_direction_accuracy_pct": direction_accuracy_pct,
            "direction_accuracy_pct": direction_accuracy_pct,
            "direction_matches": direction_matches,
            "direction_comparable_candles": direction_total,
            "average_forecast_error": average_forecast_error,
            "max_abs_error": max_abs_error,
            "max_abs_percentage_error": max_abs_percentage_error,
            "forecast_bias": _bias(average_forecast_error, neutral_threshold),
            "expected_movement_pct": expected_movement_pct,
            "trading_usefulness": analyze_trading_usefulness(
                matched,
                flat_threshold_pct=flat_threshold_pct,
                cost_threshold_pct=cost_threshold_pct,
            ),
            "quality_status": _quality_status(
                matched_candles,
                direction_accuracy_pct,
                mape_pct,
                expected_movement_pct,
                acceptable_mape_pct,
            ),
        }
    )
    return metrics


def recommendation_for_status(status: str) -> str:
    return {
        "NEEDS_MORE_SAMPLES": "continue collecting samples",
        "PROMISING": "promising but not enough data for execution by itself",
        "WEAK": "weak forecast",
        "NOT_TRADABLE": "not tradable after costs",
    }.get(status, "continue collecting samples")
