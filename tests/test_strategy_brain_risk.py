from __future__ import annotations

import pandas as pd

from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.models import StrategyCandidate
from gold_analyzer.strategy_brain.risk import RiskConfig, RiskManager


def _candles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC"),
            "open": [100.0, 100.1, 100.2, 100.3],
            "high": [100.8, 100.9, 101.0, 101.1],
            "low": [99.2, 99.3, 99.4, 99.5],
            "close": [100.2, 100.3, 100.4, 100.5],
            "ATR_14": [2.0, 2.0, 2.0, 2.0],
            "EMA_20": [100.0, 100.0, 100.0, 100.0],
            "EMA_50": [99.8, 99.8, 99.8, 99.8],
            "spread": [0.2, 0.2, 0.2, 0.2],
        }
    )


def _context(*, metadata: dict | None = None) -> StrategyContext:
    candles = _candles()
    return StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=candles["ts"].iloc[-1],
        candles=candles,
        metadata=dict(metadata or {}),
    )


def test_risk_manager_sizes_position_and_builds_exit_plan() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=103.0,
        strategy_score=84.0,
    )

    decision = RiskManager().evaluate(
        candidate,
        _context(metadata={"account_equity": 10_000.0, "size_step": 0.01}),
    )

    assert decision.approved is True
    assert decision.position_size == 25.0
    assert decision.details["risk_amount"] == 50.0
    assert decision.details["stop_distance_atr"] == 1.0
    assert decision.details["exit_plan"]["breakeven"]["new_stop"] == 100.2
    assert decision.details["exit_plan"]["trailing_stop"]["candidate_stop"] == 99.0
    assert decision.details["exit_plan"]["time_stop"]["bars"] == 8


def test_risk_manager_blocks_stop_distance_too_tight() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=99.6,
        take_profit_1=100.8,
        take_profit_2=101.2,
        strategy_score=82.0,
    )

    decision = RiskManager().evaluate(candidate, _context(metadata={"account_equity": 10_000.0}))

    assert decision.approved is False
    assert decision.reason == "STOP_DISTANCE_TOO_TIGHT"
    assert "STOP_QUALITY" in decision.blocked_by


def test_risk_manager_blocks_max_daily_loss() -> None:
    candidate = StrategyCandidate(
        signal="SELL",
        strategy_type="breakout_momentum",
        entry_price=100.0,
        stop_loss=102.0,
        take_profit_1=99.0,
        take_profit_2=98.0,
        strategy_score=81.0,
    )

    decision = RiskManager().evaluate(
        candidate,
        _context(metadata={"account_equity": 10_000.0, "daily_loss": 250.0}),
    )

    assert decision.approved is False
    assert decision.reason == "MAX_DAILY_LOSS_HIT"
    assert decision.details["daily_loss_fraction"] == 0.025


def test_risk_manager_blocks_loss_cooldown() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=103.0,
        strategy_score=84.0,
    )
    context = _context(
        metadata={
            "account_equity": 10_000.0,
            "consecutive_losses": 3,
            "last_loss_utc": "2026-01-01T00:10:00Z",
        }
    )

    decision = RiskManager().evaluate(candidate, context)

    assert decision.approved is False
    assert decision.reason == "LOSS_COOLDOWN_ACTIVE"
    assert "COOLDOWN" in decision.blocked_by


def test_risk_manager_blocks_open_position_limit() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=103.0,
        strategy_score=84.0,
    )

    decision = RiskManager().evaluate(
        candidate,
        _context(
            metadata={
                "account_equity": 10_000.0,
                "open_positions": [{"symbol": "GOLD", "status": "OPEN"}],
            }
        ),
    )

    assert decision.approved is False
    assert decision.reason == "MAX_OPEN_POSITIONS_PER_SYMBOL"
    assert decision.blocked_by == ["OPEN_POSITION_LIMIT"]


def test_risk_manager_blocks_signal_cooldown() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=103.0,
        strategy_score=84.0,
    )
    context = _context(
        metadata={
            "account_equity": 10_000.0,
            "last_signal_utc": "2026-01-01T00:13:00Z",
        }
    )

    decision = RiskManager(config=RiskConfig(signal_cooldown_minutes=10)).evaluate(candidate, context)

    assert decision.approved is False
    assert decision.reason == "SIGNAL_COOLDOWN_ACTIVE"
    assert decision.blocked_by == ["COOLDOWN"]


def test_risk_manager_blocks_excessive_spread() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit_1=101.6,
        take_profit_2=103.0,
        strategy_score=84.0,
    )
    candles = _candles()
    candles["spread"] = [0.4, 0.4, 0.4, 0.4]
    context = StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=candles["ts"].iloc[-1],
        candles=candles,
        metadata={"account_equity": 10_000.0},
    )

    decision = RiskManager().evaluate(candidate, context)

    assert decision.approved is False
    assert decision.reason == "SPREAD_TOO_WIDE_ATR"
    assert decision.blocked_by == ["SPREAD_PROTECTION"]