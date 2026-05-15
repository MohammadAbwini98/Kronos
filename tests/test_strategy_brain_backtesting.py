from __future__ import annotations

import pandas as pd

from gold_analyzer.backtesting import BacktestConfig, StrategyBrainBacktester, run_walk_forward
from gold_analyzer.strategy_brain.brain import StrategyBrain
from gold_analyzer.strategy_brain.models import StrategyCandidate
from gold_analyzer.strategy_brain.risk import RiskConfig, RiskManager


class _StaticBrain(StrategyBrain):
    def __init__(self, candidates_by_time: dict[pd.Timestamp, StrategyCandidate]) -> None:
        self.candidates_by_time = dict(candidates_by_time)

    def generate_candidate(self, context):
        return self.candidates_by_time.get(context.now_utc)


def _candles(rows: list[dict[str, float | str]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame["ATR_14"] = frame.get("ATR_14", 2.0)
    frame["EMA_20"] = frame.get("EMA_20", 100.0)
    frame["EMA_50"] = frame.get("EMA_50", 100.0)
    frame["spread"] = frame.get("spread", 0.2)
    return frame


def test_strategy_backtester_applies_spread_slippage_tp1_and_tp2() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.4, "low": 99.6, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 100.0, "high": 101.2, "low": 100.3, "close": 100.9, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 101.0, "high": 102.2, "low": 100.7, "close": 101.8, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain({candles["ts"].iloc[0]: candidate})

    result = StrategyBrainBacktester(brain=brain).run(candles)

    assert result.summary["trades_count"] == 1
    trade = result.trades[0]
    assert trade.position_size == 25.0
    assert trade.tp1_hit is True
    assert trade.tp2_hit is True
    assert trade.close_reason == "TP2"
    assert round(trade.entry_fill, 2) == 100.15
    assert [round(partial["fill_price"], 2) for partial in trade.partials] == [100.85, 101.85]
    assert round(trade.net_pnl, 2) == 27.50


def test_strategy_backtester_moves_stop_to_breakeven_after_one_r() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.3, "low": 99.6, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 100.0, "high": 102.1, "low": 100.4, "close": 101.8, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 101.6, "high": 100.8, "low": 100.1, "close": 100.3, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=105.0,
        take_profit_2=106.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain({candles["ts"].iloc[0]: candidate})

    result = StrategyBrainBacktester(brain=brain).run(candles)

    trade = result.trades[0]
    assert trade.breakeven_armed is True
    assert trade.active_stop == 100.2
    assert trade.close_reason == "BREAKEVEN_STOP"
    assert round(trade.net_pnl, 2) == -2.50


def test_strategy_backtester_enforces_consecutive_loss_cooldown() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.2, "low": 99.6, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 100.0, "high": 100.2, "low": 97.5, "close": 98.0, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 98.0, "high": 98.4, "low": 97.8, "close": 98.2, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain(
        {
            candles["ts"].iloc[0]: candidate,
            candles["ts"].iloc[1]: candidate,
        }
    )
    risk_manager = RiskManager(config=RiskConfig(max_consecutive_losses=1, loss_cooldown_minutes=60))

    result = StrategyBrainBacktester(brain=brain, risk_manager=risk_manager).run(candles)

    assert result.summary["trades_count"] == 1
    assert len(result.blocked_candidates) == 1
    assert result.blocked_candidates[0]["reason"] == "LOSS_COOLDOWN_ACTIVE"


def test_strategy_backtester_blocks_new_trade_after_max_daily_loss() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.2, "low": 99.6, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 100.0, "high": 100.2, "low": 97.5, "close": 98.0, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 98.0, "high": 98.4, "low": 97.8, "close": 98.2, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain(
        {
            candles["ts"].iloc[0]: candidate,
            candles["ts"].iloc[1]: candidate,
        }
    )
    risk_manager = RiskManager(config=RiskConfig(max_daily_loss=0.004, max_consecutive_losses=99))

    result = StrategyBrainBacktester(brain=brain, risk_manager=risk_manager).run(candles)

    assert result.summary["trades_count"] == 1
    assert len(result.blocked_candidates) == 1
    assert result.blocked_candidates[0]["reason"] == "MAX_DAILY_LOSS_HIT"


def test_strategy_backtester_summary_includes_extended_metrics() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.4, "low": 99.6, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 100.0, "high": 101.2, "low": 100.3, "close": 100.9, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 101.0, "high": 102.2, "low": 100.7, "close": 101.8, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain({candles["ts"].iloc[0]: candidate})

    result = StrategyBrainBacktester(brain=brain).run(candles)

    assert result.summary["trade_count"] == 1
    assert result.summary["average_R"] is not None
    assert result.summary["median_R"] is not None
    assert result.summary["long_win_rate"] == 1.0
    assert result.summary["short_win_rate"] is None
    assert result.summary["strategy_type_performance"]["trend_pullback"]["trade_count"] == 1


def test_walk_forward_runs_and_aggregates_windows() -> None:
    candles = _candles(
        [
            {"ts": "2026-01-01T00:00:00Z", "open": 99.8, "high": 100.0, "low": 99.6, "close": 99.9, "spread": 0.2},
            {"ts": "2026-01-01T00:05:00Z", "open": 99.9, "high": 100.1, "low": 99.7, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:10:00Z", "open": 100.0, "high": 100.4, "low": 99.8, "close": 100.0, "spread": 0.2},
            {"ts": "2026-01-01T00:15:00Z", "open": 100.0, "high": 101.2, "low": 100.3, "close": 100.9, "spread": 0.2},
            {"ts": "2026-01-01T00:20:00Z", "open": 100.9, "high": 101.0, "low": 100.6, "close": 100.8, "spread": 0.2},
            {"ts": "2026-01-01T00:25:00Z", "open": 100.8, "high": 102.2, "low": 100.7, "close": 101.8, "spread": 0.2},
        ]
    )
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        strategy_score=84.0,
    )
    brain = _StaticBrain({candles["ts"].iloc[0]: candidate, candles["ts"].iloc[2]: candidate})
    backtester = StrategyBrainBacktester(brain=brain)

    result = run_walk_forward(candles, backtester=backtester, train_bars=2, test_bars=2, step_bars=2)

    assert result.aggregate_summary["windows_count"] == 2
    assert result.aggregate_summary["trade_count"] >= 1
