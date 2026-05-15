from __future__ import annotations

from typing import Any, Iterable


TRADE_SIGNALS = {"BUY", "SELL", "LONG", "SHORT"}
WIN_LOSS = {"WIN", "LOSS"}


def normalize_trade_signal(signal: Any) -> str | None:
    text = str(signal or "").upper().strip()
    if text in {"BUY", "LONG"}:
        return "BUY"
    if text in {"SELL", "SHORT"}:
        return "SELL"
    return None


def is_trade_signal(signal: Any) -> bool:
    return normalize_trade_signal(signal) is not None


def trade_pnl_from_return(signal: Any, log_return: float, *, cost_frac: float = 0.0) -> float | None:
    direction = normalize_trade_signal(signal)
    if direction == "BUY":
        return float(log_return) - (2.0 * float(cost_frac))
    if direction == "SELL":
        return -float(log_return) - (2.0 * float(cost_frac))
    return None


def label_from_return(signal: Any, log_return: float, *, cost_frac: float = 0.0) -> str | None:
    pnl = trade_pnl_from_return(signal, log_return, cost_frac=cost_frac)
    if pnl is None:
        return None
    return "WIN" if pnl > 0.0 else "LOSS"


def filter_meta_training_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        signal = normalize_trade_signal(row.get("signal"))
        outcome = str(row.get("outcome") or row.get("status") or "").upper().strip()
        if signal is None or outcome not in WIN_LOSS:
            continue
        if row.get("is_trade_signal") is False:
            continue
        normalized = dict(row)
        normalized["signal"] = signal
        normalized["outcome"] = outcome
        filtered.append(normalized)
    return filtered


def clean_non_trade_label(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(row)
    if is_trade_signal(cleaned.get("signal")):
        cleaned["is_trade_signal"] = True
        return cleaned
    cleaned["is_trade_signal"] = False
    for key in ("outcome", "pnl", "exit_price", "exit_ts", "label_computed_at"):
        cleaned[key] = None
    return cleaned


__all__ = [
    "TRADE_SIGNALS",
    "WIN_LOSS",
    "clean_non_trade_label",
    "filter_meta_training_rows",
    "is_trade_signal",
    "label_from_return",
    "normalize_trade_signal",
    "trade_pnl_from_return",
]
