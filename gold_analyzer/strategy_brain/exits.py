from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .models import StrategyCandidate
    from .risk import RiskConfig


def build_exit_plan(
    *,
    config: "RiskConfig",
    candidate: "StrategyCandidate",
    signal: str,
    entry_price: float,
    stop_loss: float,
    take_profit_1: float | None,
    take_profit_2: float | None,
    stop_distance: float,
    spread: float,
    atr_value: float,
    current_row: dict[str, Any] | None,
) -> dict[str, Any]:
    ema_20 = _coerce_float((current_row or {}).get("EMA_20"))
    trailing_reference = None
    if ema_20 is not None:
        if signal == "BUY":
            trailing_reference = max(stop_loss, ema_20 - (config.trailing_stop_atr_multiple * atr_value))
        else:
            trailing_reference = min(stop_loss, ema_20 + (config.trailing_stop_atr_multiple * atr_value))

    if signal == "BUY":
        breakeven_stop = entry_price + spread
        breakeven_trigger_price = entry_price + (config.breakeven_r_multiple * stop_distance)
        progress_price = entry_price + (config.time_stop_progress_r_multiple * stop_distance)
    else:
        breakeven_stop = entry_price - spread
        breakeven_trigger_price = entry_price - (config.breakeven_r_multiple * stop_distance)
        progress_price = entry_price - (config.time_stop_progress_r_multiple * stop_distance)

    return {
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "partial_exit": {
            "tp1_fraction": config.tp1_close_fraction,
            "tp2_fraction": config.tp2_close_fraction,
        },
        "breakeven": {
            "enabled": True,
            "trigger_tp1_hit": take_profit_1 is not None,
            "trigger_r_multiple": config.breakeven_r_multiple,
            "trigger_price": breakeven_trigger_price,
            "new_stop": breakeven_stop,
        },
        "trailing_stop": {
            "enabled": True,
            "runner_only": True,
            "atr_multiple": config.trailing_stop_atr_multiple,
            "ema_20": ema_20,
            "candidate_stop": trailing_reference,
        },
        "time_stop": {
            "enabled": True,
            "bars": config.time_stop_bars(candidate.strategy_type),
            "progress_r_multiple": config.time_stop_progress_r_multiple,
            "progress_price": progress_price,
        },
    }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["build_exit_plan"]