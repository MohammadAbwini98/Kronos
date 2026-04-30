from __future__ import annotations

from typing import Any

import pandas as pd


def _direction_from_move_pct(move_pct: float, flat_threshold_pct: float) -> str:
    if abs(move_pct) < flat_threshold_pct:
        return "FLAT"
    return "UP" if move_pct > 0 else "DOWN"


def analyze_trading_usefulness(
    matched: pd.DataFrame,
    *,
    flat_threshold_pct: float,
    cost_threshold_pct: float = 0.05,
) -> dict[str, Any]:
    if matched.empty:
        return {
            "cost_threshold_pct": cost_threshold_pct,
            "actionable_forecast_rows": 0,
            "hold_rows_after_cost": 0,
            "false_positive_rate_pct": None,
            "up_precision_pct": None,
            "down_precision_pct": None,
            "average_hypothetical_signal_return_pct": None,
            "max_adverse_excursion_pct": None,
            "usefulness_status": "NEEDS_MORE_SAMPLES",
        }
    rows = matched.copy()
    rows["previous_actual_close"] = rows["close_actual"].shift(1)
    rows = rows.dropna(subset=["previous_actual_close"]).copy()
    if rows.empty:
        return {
            "cost_threshold_pct": cost_threshold_pct,
            "actionable_forecast_rows": 0,
            "hold_rows_after_cost": 0,
            "false_positive_rate_pct": None,
            "up_precision_pct": None,
            "down_precision_pct": None,
            "average_hypothetical_signal_return_pct": None,
            "max_adverse_excursion_pct": None,
            "usefulness_status": "NEEDS_MORE_SAMPLES",
        }
    forecast_move = ((rows["close_forecast"] / rows["previous_actual_close"]) - 1.0) * 100.0
    actual_move = ((rows["close_actual"] / rows["previous_actual_close"]) - 1.0) * 100.0
    rows["forecast_direction"] = forecast_move.apply(lambda value: _direction_from_move_pct(float(value), flat_threshold_pct))
    rows["actual_direction"] = actual_move.apply(lambda value: _direction_from_move_pct(float(value), flat_threshold_pct))
    rows["actionable"] = forecast_move.abs() >= cost_threshold_pct
    actionable = rows[rows["actionable"]].copy()
    hold_rows = int((~rows["actionable"]).sum())
    if actionable.empty:
        return {
            "cost_threshold_pct": cost_threshold_pct,
            "actionable_forecast_rows": 0,
            "hold_rows_after_cost": hold_rows,
            "false_positive_rate_pct": None,
            "up_precision_pct": None,
            "down_precision_pct": None,
            "average_hypothetical_signal_return_pct": None,
            "max_adverse_excursion_pct": None,
            "usefulness_status": "NOT_TRADABLE",
        }
    actionable["hit"] = actionable["forecast_direction"] == actionable["actual_direction"]
    false_positive_rate = float((~actionable["hit"]).mean() * 100.0)
    up_rows = actionable[actionable["forecast_direction"] == "UP"]
    down_rows = actionable[actionable["forecast_direction"] == "DOWN"]
    up_precision = float((up_rows["actual_direction"] == "UP").mean() * 100.0) if not up_rows.empty else None
    down_precision = float((down_rows["actual_direction"] == "DOWN").mean() * 100.0) if not down_rows.empty else None
    signed_return = actual_move.loc[actionable.index].where(
        actionable["forecast_direction"] == "UP",
        -actual_move.loc[actionable.index],
    )
    after_cost = signed_return - cost_threshold_pct
    max_adverse = float(after_cost.min())
    avg_return = float(after_cost.mean())
    if len(actionable) < 30:
        status = "NEEDS_MORE_SAMPLES"
    elif avg_return <= 0:
        status = "NOT_TRADABLE"
    elif false_positive_rate > 50:
        status = "WEAK"
    else:
        status = "PROMISING"
    return {
        "cost_threshold_pct": cost_threshold_pct,
        "actionable_forecast_rows": int(len(actionable)),
        "hold_rows_after_cost": hold_rows,
        "false_positive_rate_pct": false_positive_rate,
        "up_precision_pct": up_precision,
        "down_precision_pct": down_precision,
        "average_hypothetical_signal_return_pct": avg_return,
        "max_adverse_excursion_pct": max_adverse,
        "usefulness_status": status,
    }
