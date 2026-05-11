from __future__ import annotations

import math
import random
from decimal import Decimal
from typing import Any

import pandas as pd

from forecast_scoring import direction_from_prices, score_forecast_against_actuals


FINAL_FORECAST_STATUSES = {"WIN", "LOSS"}
FINAL_TRADE_OUTCOMES = {"WIN", "LOSS", "BREAKEVEN"}


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


def final_outcome_from_net_pnl(net_pnl: Any, *, breakeven_epsilon: float = 0.0) -> str:
    value = _to_float(net_pnl)
    if value is None:
        return "UNKNOWN"
    if value > breakeven_epsilon:
        return "WIN"
    if value < -breakeven_epsilon:
        return "LOSS"
    return "BREAKEVEN"


def _is_final_forecast_row(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").upper()
    if status not in FINAL_FORECAST_STATUSES:
        return False
    validation_state = str(row.get("validation_state") or "FINAL").upper()
    actual_window_complete = row.get("actual_window_complete")
    if validation_state and validation_state not in {"FINAL", "COMPLETE", "COMPLETED"}:
        return False
    return actual_window_complete is not False


def compute_forecast_quality_metrics(outcome_rows: list[dict[str, Any]]) -> dict[str, Any]:
    final_rows = [row for row in outcome_rows if _is_final_forecast_row(row)]
    wins = sum(1 for row in final_rows if str(row.get("status") or "").upper() == "WIN")
    losses = sum(1 for row in final_rows if str(row.get("status") or "").upper() == "LOSS")
    errors = [_to_float(row.get("close_error")) for row in final_rows]
    errors = [value for value in errors if value is not None]
    pct_errors = [_to_float(row.get("close_error_pct")) for row in final_rows]
    pct_errors = [abs(value) for value in pct_errors if value is not None]
    by_horizon: dict[int, dict[str, int]] = {}
    for row in outcome_rows:
        horizon = int(row.get("horizon_index") or 0)
        bucket = by_horizon.setdefault(horizon, {"wins": 0, "losses": 0, "pending": 0})
        status = str(row.get("status") or "PENDING").upper()
        if _is_final_forecast_row(row) and status == "WIN":
            bucket["wins"] += 1
        elif _is_final_forecast_row(row) and status == "LOSS":
            bucket["losses"] += 1
        else:
            bucket["pending"] += 1
    comparable = wins + losses
    return {
        "metric_category": "forecast_quality",
        "sample_count": comparable,
        "directional_forecast_hit_rate_pct": None if comparable == 0 else (wins / comparable) * 100.0,
        "wins": wins,
        "losses": losses,
        "pending": len(outcome_rows) - comparable,
        "mae": _mean([abs(value) for value in errors]),
        "rmse": None if not errors else math.sqrt(sum(value * value for value in errors) / len(errors)),
        "mape_pct": _mean(pct_errors),
        "bias": _mean(errors),
        "per_horizon": by_horizon,
    }


def _validation_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"LONG", "STRONG_LONG", "WEAK_LONG"}:
        return "LONG"
    if text in {"SHORT", "STRONG_SHORT", "WEAK_SHORT"}:
        return "SHORT"
    if text in {"HOLD", "WATCH", "BLOCKED", "VALIDATION_UNAVAILABLE"}:
        return text
    return None


def compute_signal_quality_metrics(signal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    signal_status_distribution: dict[str, int] = {}
    validation_status_distribution: dict[str, int] = {}
    score_buckets = {"missing": 0, "0_25": 0, "25_50": 0, "50_75": 0, "75_100": 0}
    mismatches = 0
    for row in signal_rows:
        signal_status = str(row.get("status") or "PENDING").upper()
        validation_status = str(row.get("validation_status") or "UNVALIDATED").upper()
        signal_status_distribution[signal_status] = signal_status_distribution.get(signal_status, 0) + 1
        validation_status_distribution[validation_status] = validation_status_distribution.get(validation_status, 0) + 1
        score = _to_float(row.get("validation_score"))
        if score is None:
            score_buckets["missing"] += 1
        elif score < 25:
            score_buckets["0_25"] += 1
        elif score < 50:
            score_buckets["25_50"] += 1
        elif score < 75:
            score_buckets["50_75"] += 1
        else:
            score_buckets["75_100"] += 1
        raw_signal = str(row.get("signal") or "").upper()
        raw_direction = raw_signal if raw_signal in {"LONG", "SHORT"} else None
        validation_direction = _validation_direction(validation_status)
        if raw_direction and validation_direction in {"LONG", "SHORT"} and raw_direction != validation_direction:
            mismatches += 1
        elif raw_direction and validation_direction in {"HOLD", "WATCH", "BLOCKED", "VALIDATION_UNAVAILABLE"}:
            mismatches += 1
    return {
        "metric_category": "signal_quality",
        "sample_count": len(signal_rows),
        "signal_status_distribution": signal_status_distribution,
        "validation_status_distribution": validation_status_distribution,
        "validation_score_distribution": score_buckets,
        "raw_signal_validation_mismatch_count": mismatches,
    }


def compute_executed_trade_performance(trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in trade_rows if str(row.get("status") or "").upper() == "CLOSED"]
    finalized = [
        row
        for row in closed
        if str(row.get("final_outcome") or "").upper() in FINAL_TRADE_OUTCOMES and row.get("outcome_finalized_at") is not None
    ]
    wins = [row for row in finalized if str(row.get("final_outcome") or "").upper() == "WIN"]
    losses = [row for row in finalized if str(row.get("final_outcome") or "").upper() == "LOSS"]
    breakevens = [row for row in finalized if str(row.get("final_outcome") or "").upper() == "BREAKEVEN"]
    unknown = [
        row
        for row in closed
        if str(row.get("final_outcome") or "UNKNOWN").upper() == "UNKNOWN" or row.get("outcome_finalized_at") is None
    ]
    win_pnls = [_to_float(row.get("net_pnl")) for row in wins]
    win_pnls = [value for value in win_pnls if value is not None]
    loss_pnls = [_to_float(row.get("net_pnl")) for row in losses]
    loss_pnls = [value for value in loss_pnls if value is not None]
    all_pnls = [_to_float(row.get("net_pnl")) for row in finalized]
    all_pnls = [value for value in all_pnls if value is not None]
    spread_costs = [_to_float(row.get("spread_cost")) for row in finalized]
    spread_costs = [value for value in spread_costs if value is not None]
    slippage = [_to_float(row.get("slippage_estimate")) for row in finalized]
    slippage = [value for value in slippage if value is not None]
    win_loss_count = len(wins) + len(losses)
    return {
        "metric_category": "executed_trade_performance",
        "closed_trade_count": len(closed),
        "finalized_trade_count": len(finalized),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "unknown_outcome_count": len(unknown),
        "executed_trade_win_rate_pct": None if win_loss_count == 0 else (len(wins) / win_loss_count) * 100.0,
        "average_win": _mean(win_pnls),
        "average_loss": _mean(loss_pnls),
        "expectancy": _mean(all_pnls),
        "total_net_pnl": None if not all_pnls else float(sum(all_pnls)),
        "average_spread_cost": _mean(spread_costs),
        "average_slippage_estimate": _mean(slippage),
    }


def terminal_direction_outcome(
    forecast_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    *,
    last_input_close: float,
    flat_threshold_pct: float = 0.02,
) -> dict[str, Any]:
    forecast = forecast_df.copy()
    actual = actual_df.copy()
    forecast["timestamps"] = pd.to_datetime(forecast["timestamps"], utc=True)
    actual["timestamps"] = pd.to_datetime(actual["timestamps"], utc=True)
    forecast = forecast.sort_values("timestamps")
    actual = actual.sort_values("timestamps")
    if forecast.empty or actual.empty:
        return {
            "terminal_predicted_direction": None,
            "terminal_actual_direction": None,
            "terminal_direction_status": "PENDING",
        }
    terminal_ts = forecast.iloc[-1]["timestamps"]
    actual_match = actual[actual["timestamps"] == terminal_ts]
    if actual_match.empty:
        return {
            "terminal_predicted_direction": direction_from_prices(last_input_close, float(forecast.iloc[-1]["close"]), flat_threshold_pct),
            "terminal_actual_direction": None,
            "terminal_direction_status": "PENDING",
        }
    predicted = direction_from_prices(last_input_close, float(forecast.iloc[-1]["close"]), flat_threshold_pct)
    actual_direction = direction_from_prices(last_input_close, float(actual_match.iloc[-1]["close"]), flat_threshold_pct)
    return {
        "terminal_predicted_direction": predicted,
        "terminal_actual_direction": actual_direction,
        "terminal_direction_status": "WIN" if predicted == actual_direction else "LOSS",
    }


def _baseline_step(input_df: pd.DataFrame) -> float:
    closes = pd.to_numeric(input_df["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return 0.001
    returns = closes.pct_change().abs().dropna()
    return max(float(returns.tail(12).mean() or 0.001), 0.0001)


def _baseline_forecast_df(input_df: pd.DataFrame, forecast_df: pd.DataFrame, method: str, *, seed: int) -> pd.DataFrame:
    history = input_df.copy()
    history["close"] = pd.to_numeric(history["close"], errors="coerce")
    history = history.dropna(subset=["close"]).reset_index(drop=True)
    if history.empty:
        raise ValueError("baseline input requires at least one historical close")
    last_close = float(history.iloc[-1]["close"])
    step = _baseline_step(history)
    direction = 0
    if method == "last_close_persistence":
        closes = [last_close] * len(forecast_df)
    elif method == "random_direction":
        direction = random.Random(seed).choice([-1, 1])
        closes = [last_close * (1.0 + direction * step * (index + 1)) for index in range(len(forecast_df))]
    elif method == "moving_average_direction":
        short = float(history["close"].tail(5).mean())
        long = float(history["close"].tail(20).mean())
        direction = 1 if short >= long else -1
        closes = [last_close * (1.0 + direction * step * (index + 1)) for index in range(len(forecast_df))]
    elif method == "naive_momentum":
        lookback = min(6, max(len(history) - 1, 1))
        direction = 1 if float(history["close"].iloc[-1] - history["close"].iloc[-1 - lookback]) >= 0 else -1
        closes = [last_close * (1.0 + direction * step * (index + 1)) for index in range(len(forecast_df))]
    elif method == "naive_mean_reversion":
        lookback = min(6, max(len(history) - 1, 1))
        direction = -1 if float(history["close"].iloc[-1] - history["close"].iloc[-1 - lookback]) >= 0 else 1
        closes = [last_close * (1.0 + direction * step * (index + 1)) for index in range(len(forecast_df))]
    else:
        raise ValueError(f"Unsupported baseline method: {method}")
    return pd.DataFrame({"timestamps": forecast_df["timestamps"], "close": closes})


def compute_baseline_comparisons(
    input_df: pd.DataFrame,
    model_forecast_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    *,
    last_input_close: float | None = None,
    flat_threshold_pct: float = 0.02,
    seed: int = 17,
    minimum_samples: int = 30,
) -> list[dict[str, Any]]:
    methods = [
        "last_close_persistence",
        "random_direction",
        "moving_average_direction",
        "naive_momentum",
        "naive_mean_reversion",
    ]
    input_clean = input_df.copy()
    input_clean["timestamps"] = pd.to_datetime(input_clean["timestamps"], utc=True)
    input_clean = input_clean.sort_values("timestamps")
    anchor = float(last_input_close if last_input_close is not None else input_clean.iloc[-1]["close"])
    model_score = score_forecast_against_actuals(
        model_forecast_df,
        actual_df,
        last_input_close=anchor,
        flat_threshold_pct=flat_threshold_pct,
    )["summary"]
    model_metric = model_score.get("direction_accuracy_pct")
    sample_count = int(model_score.get("direction_comparable_candles") or 0)
    comparisons = []
    for method in methods:
        baseline_forecast = _baseline_forecast_df(input_clean, model_forecast_df, method, seed=seed)
        baseline_score = score_forecast_against_actuals(
            baseline_forecast,
            actual_df,
            last_input_close=anchor,
            flat_threshold_pct=flat_threshold_pct,
        )["summary"]
        baseline_metric = baseline_score.get("direction_accuracy_pct")
        delta = None if model_metric is None or baseline_metric is None else float(model_metric) - float(baseline_metric)
        terminal = terminal_direction_outcome(
            baseline_forecast,
            actual_df,
            last_input_close=anchor,
            flat_threshold_pct=flat_threshold_pct,
        )
        comparisons.append(
            {
                "baseline_name": method,
                "metric_name": "direction_accuracy_pct",
                "model_metric": model_metric,
                "baseline_metric": baseline_metric,
                "delta": delta,
                "sample_count": sample_count,
                "enough_samples": sample_count >= minimum_samples,
                "details": {
                    "seed": seed if method == "random_direction" else None,
                    "terminal_direction": terminal,
                    "baseline_summary": baseline_score,
                    "model_summary": model_score,
                },
            }
        )
    return comparisons


def decimal_or_none(value: Any) -> Decimal | None:
    result = _to_float(value)
    return None if result is None else Decimal(str(result))
