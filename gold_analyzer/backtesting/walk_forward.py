from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .performance_metrics import summarize_strategy_backtest
from .strategy_brain import StrategyBrainBacktester


@dataclass(frozen=True)
class WalkForwardWindowResult:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    result: Any


@dataclass(frozen=True)
class WalkForwardResult:
    windows: list[WalkForwardWindowResult]
    aggregate_summary: dict[str, Any]


def run_walk_forward(
    candles: pd.DataFrame,
    *,
    backtester: StrategyBrainBacktester,
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    symbol: str = "GOLD",
    timeframe: str = "5m",
    metadata: dict[str, Any] | None = None,
) -> WalkForwardResult:
    frame = candles.reset_index(drop=True)
    step = step_bars or test_bars
    windows: list[WalkForwardWindowResult] = []
    all_trades = []

    for start in range(max(1, int(train_bars)), len(frame) - int(test_bars) + 1, max(1, int(step))):
        train_slice = frame.iloc[start - int(train_bars) : start].copy()
        test_slice = frame.iloc[start : start + int(test_bars)].copy()
        if train_slice.empty or test_slice.empty:
            continue
        result = backtester.run(test_slice, symbol=symbol, timeframe=timeframe, metadata=metadata)
        all_trades.extend(result.trades)
        windows.append(
            WalkForwardWindowResult(
                train_start=pd.to_datetime(train_slice["ts"].iloc[0], utc=True),
                train_end=pd.to_datetime(train_slice["ts"].iloc[-1], utc=True),
                test_start=pd.to_datetime(test_slice["ts"].iloc[0], utc=True),
                test_end=pd.to_datetime(test_slice["ts"].iloc[-1], utc=True),
                result=result,
            )
        )

    aggregate_summary = summarize_strategy_backtest(
        all_trades,
        initial_equity=backtester.config.initial_equity,
        ending_equity=(backtester.config.initial_equity + sum(trade.net_pnl for trade in all_trades)),
        bar_count=len(frame),
        minimum_trades_for_approval=backtester.config.minimum_trades_for_approval,
        minimum_win_rate=backtester.config.minimum_win_rate,
        minimum_profit_factor=backtester.config.minimum_profit_factor,
        minimum_expectancy=backtester.config.minimum_expectancy,
        epsilon=backtester.config.epsilon,
    )
    aggregate_summary["windows_count"] = len(windows)
    return WalkForwardResult(windows=windows, aggregate_summary=aggregate_summary)


__all__ = ["WalkForwardResult", "WalkForwardWindowResult", "run_walk_forward"]