from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import pandas as pd


TARGET_HORIZONS = (1, 3, 6, 12)
DEFAULT_MIN_CALIBRATION_SAMPLES = 30


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: list[float]) -> float | None:
    return None if not values else float(sum(values) / len(values))


def _rmse(values: list[float]) -> float | None:
    return None if not values else math.sqrt(sum(value * value for value in values) / len(values))


def compute_baseline_delta(model_metric: float | None, baseline_metric: float | None) -> float | None:
    if model_metric is None or baseline_metric is None:
        return None
    return float(model_metric) - float(baseline_metric)


def _baseline_delta_for_horizon(baseline_rows: list[dict[str, Any]], horizon: int, metric_name: str) -> float | None:
    for row in baseline_rows:
        details = row.get("details") or {}
        row_horizon = row.get("horizon_index") or details.get("horizon_index")
        if row_horizon is not None and int(row_horizon) != int(horizon):
            continue
        if str(row.get("metric_name") or metric_name) != metric_name:
            continue
        return compute_baseline_delta(row.get("model_metric"), row.get("baseline_metric"))
    return None


def compute_horizon_skill_analysis(
    horizon_rows: list[dict[str, Any]],
    *,
    baseline_rows: list[dict[str, Any]] | None = None,
    target_horizons: tuple[int, ...] = TARGET_HORIZONS,
    minimum_samples: int = 30,
) -> list[dict[str, Any]]:
    baselines = baseline_rows or []
    output: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in horizon_rows:
        try:
            by_horizon[int(row.get("horizon_index"))].append(row)
        except (TypeError, ValueError):
            continue

    for horizon in target_horizons:
        rows = by_horizon.get(horizon, [])
        final_rows = [
            row
            for row in rows
            if str(row.get("status") or "").upper() in {"WIN", "LOSS"}
            and str(row.get("validation_state") or "FINAL").upper() in {"FINAL", "COMPLETE", "COMPLETED"}
            and row.get("actual_window_complete") is not False
        ]
        wins = sum(1 for row in final_rows if str(row.get("status") or "").upper() == "WIN")
        losses = sum(1 for row in final_rows if str(row.get("status") or "").upper() == "LOSS")
        sample_count = wins + losses
        errors = [_to_float(row.get("close_error")) for row in final_rows]
        errors = [value for value in errors if value is not None]
        pct_errors = [_to_float(row.get("close_error_pct")) for row in final_rows]
        pct_errors = [abs(value) for value in pct_errors if value is not None and abs(value) < 1_000_000]
        net_edge_rows = [row for row in final_rows if _to_float(row.get("movement_after_cost_pct")) is not None]
        net_edge_hits = [
            row
            for row in net_edge_rows
            if str(row.get("status") or "").upper() == "WIN" and (_to_float(row.get("movement_after_cost_pct")) or 0.0) > 0.0
        ]
        directional_hit_rate = None if sample_count == 0 else (wins / sample_count) * 100.0
        output.append(
            {
                "horizon": horizon,
                "sample_count": sample_count,
                "wins": wins,
                "losses": losses,
                "pending": len(rows) - sample_count,
                "directional_hit_rate_pct": directional_hit_rate,
                "mae": _mean([abs(value) for value in errors]),
                "rmse": _rmse(errors),
                "mape_pct": _mean(pct_errors),
                "net_edge_hit_rate_pct": None if not net_edge_rows else (len(net_edge_hits) / len(net_edge_rows)) * 100.0,
                "baseline_delta": _baseline_delta_for_horizon(baselines, horizon, "directional_hit_rate_pct"),
                "enough_samples": sample_count >= minimum_samples,
            }
        )
    return output


def session_for_hour(hour: int) -> str:
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 13:
        return "EUROPE"
    if 13 <= hour < 21:
        return "US"
    return "LATE_US"


def build_regime_labels(
    candle_df: pd.DataFrame,
    *,
    volatility_window: int = 12,
    trend_window: int = 12,
    volume_window: int = 20,
) -> pd.DataFrame:
    """Build prediction-time regime labels using only each row's past/current candles."""
    df = candle_df.copy()
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    returns = close.pct_change()
    abs_returns = returns.abs()
    volume = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series([math.nan] * len(df))
    spread_pct = pd.to_numeric(df["spread_pct"], errors="coerce") if "spread_pct" in df.columns else pd.Series([math.nan] * len(df))

    labels: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        past_abs = abs_returns.iloc[: index + 1].dropna().tail(volatility_window)
        current_abs = _to_float(abs_returns.iloc[index])
        if current_abs is None:
            volatility = "UNKNOWN"
        elif len(past_abs) < 3:
            volatility = "UNKNOWN"
        else:
            low_q = past_abs.quantile(0.33)
            high_q = past_abs.quantile(0.80)
            volatility = "LOW" if current_abs <= low_q else ("HIGH" if current_abs >= high_q else "NORMAL")

        trend_start = max(0, index - trend_window + 1)
        trend_slice = close.iloc[trend_start : index + 1].dropna()
        if len(trend_slice) < 3:
            trend = "UNKNOWN"
        else:
            move_pct = ((float(trend_slice.iloc[-1]) / float(trend_slice.iloc[0])) - 1.0) * 100.0
            trend = "TREND_UP" if move_pct > 0.15 else ("TREND_DOWN" if move_pct < -0.15 else "RANGE")

        past_volume = volume.iloc[: index + 1].dropna().tail(volume_window)
        current_volume = _to_float(volume.iloc[index])
        if current_volume is None:
            volume_regime = "MISSING"
        elif len(past_volume) < 3 or float(past_volume.median()) <= 0:
            volume_regime = "UNKNOWN"
        else:
            ratio = current_volume / float(past_volume.median())
            volume_regime = "LOW" if ratio < 0.5 else ("HIGH" if ratio > 1.8 else "NORMAL")

        current_spread = _to_float(spread_pct.iloc[index])
        if current_spread is None:
            spread_regime = "MISSING"
        else:
            spread_regime = "TIGHT" if current_spread <= 0.02 else ("WIDE" if current_spread >= 0.08 else "NORMAL")

        hour = int(row["timestamps"].hour)
        labels.append(
            {
                "timestamps": row["timestamps"],
                "volatility_regime": volatility,
                "trend_range_regime": trend,
                "volume_regime": volume_regime,
                "spread_regime": spread_regime,
                "hour": hour,
                "session": session_for_hour(hour),
            }
        )
    return pd.DataFrame(labels)


def compute_regime_skill_analysis(
    rows: list[dict[str, Any]],
    *,
    dimensions: tuple[str, ...] = ("volatility_regime", "trend_range_regime", "volume_regime", "spread_regime", "hour", "session"),
    minimum_samples: int = 30,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for dimension in dimensions:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[str(row.get(dimension) if row.get(dimension) is not None else "UNKNOWN")].append(row)
        for label, bucket_rows in sorted(buckets.items()):
            final_rows = [row for row in bucket_rows if str(row.get("status") or "").upper() in {"WIN", "LOSS"}]
            wins = sum(1 for row in final_rows if str(row.get("status") or "").upper() == "WIN")
            sample_count = len(final_rows)
            output.append(
                {
                    "dimension": dimension,
                    "label": label,
                    "sample_count": sample_count,
                    "directional_hit_rate_pct": None if sample_count == 0 else (wins / sample_count) * 100.0,
                    "enough_samples": sample_count >= minimum_samples,
                }
            )
    return output


def confidence_bucket(value: Any, *, bucket_size: float = 0.1) -> str:
    confidence = _to_float(value)
    if confidence is None:
        return "missing"
    confidence = max(0.0, min(1.0, confidence))
    lower = math.floor(confidence / bucket_size) * bucket_size
    upper = min(1.0, lower + bucket_size)
    if confidence == 1.0:
        lower = max(0.0, 1.0 - bucket_size)
        upper = 1.0
    return f"{lower:.1f}-{upper:.1f}"


def compute_confidence_calibration_buckets(
    rows: list[dict[str, Any]],
    *,
    minimum_samples: int = DEFAULT_MIN_CALIBRATION_SAMPLES,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("symbol") or "UNKNOWN",
            row.get("resolution") or "UNKNOWN",
            int(row.get("horizon") or row.get("horizon_index") or 0),
            str(row.get("signal_type") or row.get("signal") or "UNKNOWN").upper(),
            str(row.get("validation_status") or "UNKNOWN").upper(),
            str(row.get("volatility_regime") or "UNKNOWN").upper(),
            confidence_bucket(row.get("confidence")),
        )
        buckets[key].append(row)

    output: list[dict[str, Any]] = []
    for key, bucket_rows in sorted(buckets.items()):
        wins = sum(1 for row in bucket_rows if str(row.get("status") or row.get("outcome") or "").upper() == "WIN")
        sample_count = len(bucket_rows)
        raw_rate = None if sample_count == 0 else (wins / sample_count) * 100.0
        enough = sample_count >= minimum_samples
        output.append(
            {
                "symbol": key[0],
                "resolution": key[1],
                "horizon": key[2],
                "signal_type": key[3],
                "validation_status": key[4],
                "volatility_regime": key[5],
                "confidence_bucket": key[6],
                "observed_win_rate": raw_rate if enough else None,
                "empirical_win_rate_raw": raw_rate,
                "sample_count": sample_count,
                "enough_samples": enough,
                "calibration_claim": "empirical_calibration" if enough else "insufficient_samples_not_calibrated",
            }
        )
    return output
