from __future__ import annotations

import pandas as pd

from gold_analyzer.ai_support.service import AISupportService
from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.decision import DECISION_NO_TRADE, FinalDecisionEngine
from gold_analyzer.strategy_brain.models import StrategyCandidate
from gold_analyzer.strategy_brain.risk import RiskDecision


def _context(*, metadata: dict | None = None) -> StrategyContext:
    candles = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC"),
            "open": [100.0, 100.2, 100.4],
            "high": [100.6, 100.8, 101.0],
            "low": [99.4, 99.6, 99.8],
            "close": [100.2, 100.4, 100.5],
            "ATR_14": [2.0, 2.0, 2.0],
            "spread": [0.1, 0.1, 0.1],
        }
    )
    return StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=candles["ts"].iloc[-1],
        candles=candles,
        metadata=dict(metadata or {}),
    )


def _candidate(signal: str = "BUY") -> StrategyCandidate:
    if signal == "BUY":
        return StrategyCandidate(
            signal="BUY",
            strategy_type="trend_pullback",
            entry_price=100.5,
            stop_loss=98.5,
            take_profit_1=102.1,
            take_profit_2=103.5,
            strategy_score=84.0,
            indicators={"ATR_14": 2.0},
        )
    return StrategyCandidate(
        signal="SELL",
        strategy_type="breakout_momentum",
        entry_price=100.5,
        stop_loss=102.5,
        take_profit_1=99.5,
        take_profit_2=98.0,
        strategy_score=84.0,
        indicators={"ATR_14": 2.0},
    )


def test_ai_support_service_confirms_candidate_without_generating_signal() -> None:
    context = _context(
        metadata={
            "ai_support_models": {
                "kronos": {"predicted_return": 0.012, "confidence": 0.90},
                "chronos2": {"predicted_return": 0.009, "confidence": 0.70},
                "timesfm": {"predicted_return": 0.008, "confidence": 0.65},
                "patchtst": {"predicted_return": 0.007, "confidence": 0.60},
                "itransformer": {"predicted_return": 0.006, "confidence": 0.60},
                "moirai": {"predicted_return": 0.008, "lower_bound": 0.004, "upper_bound": 0.010, "confidence": 0.55},
                "garch": {"risk_state": "NORMAL", "confidence": 0.80},
            }
        }
    )

    result = AISupportService().evaluate(_candidate("BUY"), context)

    assert result.candidate_signal == "BUY"
    assert result.status == "SUPPORTED"
    assert result.should_block is False
    assert result.ai_support_score > 0.0
    assert result.kronos_support == 1.0
    assert result.garch_support == 1.0
    assert len(result.evaluations) == 7


def test_ai_support_service_soft_vetoes_heavily_disagreeing_models() -> None:
    context = _context(
        metadata={
            "ai_support_models": {
                "kronos": {"predicted_return": -0.012},
                "chronos2": {"predicted_return": -0.010},
                "timesfm": {"predicted_return": -0.010},
                "patchtst": {"predicted_return": -0.010},
                "itransformer": {"predicted_return": -0.010},
                "moirai": {"predicted_return": -0.010, "lower_bound": -0.011, "upper_bound": -0.009},
                "garch": {"risk_state": "HIGH"},
            }
        }
    )

    result = AISupportService().evaluate(_candidate("BUY"), context)

    assert result.status == "BLOCKED"
    assert result.should_block is True
    assert result.reason == "AI_SOFT_VETO"
    assert result.ai_support_score <= -60.0


def test_ai_support_service_hard_vetoes_garch_extreme() -> None:
    context = _context(
        metadata={
            "ai_support_models": {
                "kronos": {"predicted_return": 0.012},
                "garch": {"risk_state": "EXTREME"},
            }
        }
    )

    result = AISupportService().evaluate(_candidate("SELL"), context)

    assert result.status == "BLOCKED"
    assert result.hard_veto is True
    assert result.veto_reason == "GARCH_RISK_EXTREME"
    assert result.should_block is True


def test_ai_support_service_skips_missing_models_without_crashing() -> None:
    result = AISupportService().evaluate(_candidate("BUY"), _context())

    assert result.status == "NEUTRAL"
    assert result.ai_support_score == 0.0
    assert result.should_block is False
    assert all(evaluation["model_status"] == "SKIPPED" for evaluation in result.evaluations)


def test_no_candidate_still_results_in_no_trade_even_if_kronos_implies_buy() -> None:
    context = _context(
        metadata={
            "ai_support_models": {
                "kronos": {"predicted_return": 0.015, "predicted_direction": "BUY", "confidence": 0.95}
            }
        }
    )
    ai_result = AISupportService().evaluate(None, context)
    risk = RiskDecision.approved_decision(risk_score=85.0, position_size=0.5)

    decision = FinalDecisionEngine().decide(None, ai_result, risk, context)

    assert ai_result.status == "UNAVAILABLE"
    assert ai_result.candidate_signal is None
    assert decision.signal == DECISION_NO_TRADE
    assert decision.decision_status == DECISION_NO_TRADE
    assert decision.reason == "NO_STRATEGY_SETUP"