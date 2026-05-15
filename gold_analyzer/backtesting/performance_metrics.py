from __future__ import annotations

from statistics import median
from typing import Any


def summarize_strategy_backtest(
    trades,
    *,
    initial_equity: float,
    ending_equity: float,
    bar_count: int | None = None,
    minimum_trades_for_approval: int = 100,
    minimum_win_rate: float = 0.55,
    minimum_profit_factor: float = 1.20,
    minimum_expectancy: float = 0.0,
    epsilon: float = 1e-12,
) -> dict[str, Any]:
    trades = list(trades)
    wins = [trade.net_pnl for trade in trades if trade.outcome == "WIN"]
    losses = [trade.net_pnl for trade in trades if trade.outcome == "LOSS"]
    breakevens = [trade.net_pnl for trade in trades if trade.outcome == "BREAKEVEN"]
    trade_count = len(trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = (len(wins) / trade_count) if trade_count else None
    profit_factor = None if gross_loss <= epsilon else gross_profit / gross_loss
    expectancy = None if trade_count == 0 else sum(trade.net_pnl for trade in trades) / trade_count

    equity = initial_equity
    peak = initial_equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    r_values = [value for value in (_r_multiple(trade) for trade in trades) if value is not None]
    long_trades = [trade for trade in trades if str(trade.signal).upper() == "BUY"]
    short_trades = [trade for trade in trades if str(trade.signal).upper() == "SELL"]
    strategy_type_performance = {
        strategy_type: _strategy_type_summary(strategy_trades, epsilon=epsilon)
        for strategy_type, strategy_trades in _group_by_strategy_type(trades).items()
    }
    approved_for_paper = (
        trade_count >= minimum_trades_for_approval
        and (win_rate or 0.0) >= minimum_win_rate
        and (profit_factor or 0.0) >= minimum_profit_factor
        and (expectancy or 0.0) > minimum_expectancy
    )
    return {
        "trade_count": trade_count,
        "trades_count": trade_count,
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_win": None if not wins else sum(wins) / len(wins),
        "avg_loss": None if not losses else sum(losses) / len(losses),
        "average_R": None if not r_values else sum(r_values) / len(r_values),
        "median_R": None if not r_values else median(r_values),
        "max_drawdown": max_drawdown,
        "starting_equity": initial_equity,
        "ending_equity": ending_equity,
        "signal_frequency": None if not bar_count else trade_count / max(1, int(bar_count)),
        "long_win_rate": _win_rate(long_trades),
        "short_win_rate": _win_rate(short_trades),
        "strategy_type_performance": strategy_type_performance,
        "approved_for_paper": approved_for_paper,
    }


def _r_multiple(trade) -> float | None:
    denominator = float(trade.position_size or 0.0) * float(trade.stop_distance or 0.0)
    if denominator <= 0.0:
        return None
    return trade.net_pnl / denominator


def _win_rate(trades) -> float | None:
    trades = list(trades)
    if not trades:
        return None
    wins = len([trade for trade in trades if trade.outcome == "WIN"])
    return wins / len(trades)


def _group_by_strategy_type(trades) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for trade in trades:
        key = str(trade.strategy_type or "UNKNOWN")
        grouped.setdefault(key, []).append(trade)
    return grouped


def _strategy_type_summary(trades, *, epsilon: float) -> dict[str, Any]:
    wins = [trade.net_pnl for trade in trades if trade.outcome == "WIN"]
    losses = [trade.net_pnl for trade in trades if trade.outcome == "LOSS"]
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(trades),
        "win_rate": _win_rate(trades),
        "profit_factor": None if gross_loss <= epsilon else sum(wins) / gross_loss,
        "net_pnl": sum(trade.net_pnl for trade in trades),
        "avg_pnl": None if not trades else sum(trade.net_pnl for trade in trades) / len(trades),
    }


__all__ = ["summarize_strategy_backtest"]