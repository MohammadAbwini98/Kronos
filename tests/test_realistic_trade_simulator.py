from __future__ import annotations

import pandas as pd

from gold_analyzer.backtesting.realistic_trade_simulator import (
    RealisticSimulatorConfig,
    RealisticTradeSimulator,
    TradeSetup,
)


def _candles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=8, freq="5min", tz="UTC"),
            "open": [100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7],
            "high": [100.5, 101.2, 101.5, 100.8, 100.9, 101.0, 101.1, 101.2],
            "low": [99.8, 98.8, 99.7, 99.9, 100.0, 100.1, 100.2, 100.3],
            "close": [100.1, 100.4, 100.6, 100.5, 100.6, 100.7, 100.8, 100.9],
        }
    )


def test_same_bar_ambiguity_defaults_to_conservative_sl_first() -> None:
    result = RealisticTradeSimulator().run(
        _candles(),
        [TradeSetup(signal="BUY", entry_price=100.0, stop_loss=99.0, take_profit_1=101.0, signal_index=1)],
    )

    assert result.trades[0].outcome == "LOSS"
    assert result.trades[0].exit_reason == "STOP_LOSS"


def test_simulates_spread_slippage_tp_and_metrics() -> None:
    result = RealisticTradeSimulator(RealisticSimulatorConfig(spread=0.2, slippage=0.05)).run(
        _candles(),
        [TradeSetup(signal="BUY", entry_price=100.0, stop_loss=99.0, take_profit_1=101.0, signal_index=2)],
    )

    assert result.trades[0].outcome == "WIN"
    assert result.metrics["trade_count"] == 1
    assert result.metrics["win_rate"] == 1.0
    assert result.metrics["average_R"] is not None


def test_cooldown_and_daily_max_loss_block_later_trades() -> None:
    result = RealisticTradeSimulator(RealisticSimulatorConfig(cooldown_bars=3, daily_max_loss=0.5)).run(
        _candles(),
        [
            TradeSetup(signal="BUY", entry_price=100.0, stop_loss=99.0, take_profit_1=101.0, signal_index=1),
            TradeSetup(signal="BUY", entry_price=100.0, stop_loss=99.0, take_profit_1=101.0, signal_index=2),
            TradeSetup(signal="BUY", entry_price=100.0, stop_loss=99.0, take_profit_1=101.0, signal_index=6),
        ],
    )

    assert result.trades[0].outcome == "LOSS"
    assert {row["reason"] for row in result.blocked} == {"COOLDOWN_ACTIVE", "DAILY_MAX_LOSS_HIT"}
