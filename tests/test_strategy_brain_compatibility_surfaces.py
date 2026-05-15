from __future__ import annotations

from gold_analyzer.ai_support.adapters import score_garch_support, score_kronos_support
from gold_analyzer.backtesting.strategy_brain import StrategyBrainBacktester as BaseStrategyBrainBacktester
from gold_analyzer.backtesting.strategy_brain_backtest import StrategyBrainBacktester
from gold_analyzer.strategy_brain.exits import build_exit_plan
from gold_analyzer.strategy_brain.regimes import REGIME_NO_TRADE, classify_market_regime
from gold_analyzer.strategy_brain.rules import (
    build_breakout_candidate,
    build_mean_reversion_candidate,
    build_trend_pullback_candidate,
)


def test_named_strategy_brain_surfaces_are_importable() -> None:
    assert REGIME_NO_TRADE == "NO_TRADE"
    assert callable(classify_market_regime)
    assert callable(build_exit_plan)
    assert callable(build_trend_pullback_candidate)
    assert callable(build_breakout_candidate)
    assert callable(build_mean_reversion_candidate)
    assert StrategyBrainBacktester is BaseStrategyBrainBacktester


def test_ai_adapter_surfaces_return_expected_support_values() -> None:
    assert score_kronos_support("BUY", 0.02, 0.01) == 1.0
    assert score_kronos_support("SELL", 0.02, 0.01) == -1.0
    assert score_garch_support("NORMAL") == 1.0
    assert score_garch_support("EXTREME") == -1.0