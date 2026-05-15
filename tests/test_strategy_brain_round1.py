from __future__ import annotations

from pathlib import Path

import pandas as pd

from gold_analyzer.ai_support.models import AISupportResult
from gold_analyzer.ai_support.service import AISupportService
from gold_analyzer.orchestration.strategy_cycle import StrategyCycle
from gold_analyzer.repositories.ai_support_repository import AISupportRepository
from gold_analyzer.repositories.strategy_decision_repository import StrategyDecisionRepository
from gold_analyzer.repositories.strategy_performance_repository import StrategyPerformanceRepository
from gold_analyzer.strategy_brain.context import DataQualityState, MarketRegimeState, StrategyContext
from gold_analyzer.strategy_brain.decision import DECISION_NO_TRADE, FinalDecisionEngine
from gold_analyzer.strategy_brain.models import StrategyCandidate
from gold_analyzer.strategy_brain.risk import RiskDecision


ROOT = Path(__file__).resolve().parents[1]


def test_round1_dataclasses_construct_expected_shapes() -> None:
    context = StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=pd.Timestamp("2026-05-13T00:00:00Z"),
        data_quality=DataQualityState.passed(details={"rows": 512}),
        market_regime=MarketRegimeState(regime="UNKNOWN", confidence=0.25),
    )
    candidate = StrategyCandidate(
        signal="buy",
        strategy_type="trend_pullback",
        entry_price=2350.0,
        stop_loss=2345.0,
        take_profit_1=2358.0,
        take_profit_2=2364.0,
        position_size=0.5,
        strategy_score=81.0,
    )
    ai_result = AISupportResult.neutral(candidate_signal="BUY", support_value=12.0, confidence=0.66)
    risk = RiskDecision.approved_decision(risk_score=77.0, position_size=0.4)

    assert context.data_quality.ok is True
    assert context.now_utc.isoformat().startswith("2026-05-13T00:00:00")
    assert candidate.signal == "BUY"
    assert ai_result.status == "NEUTRAL"
    assert ai_result.candidate_signal == "BUY"
    assert risk.approved is True


def test_ai_support_cannot_generate_signal_without_strategy_candidate() -> None:
    context = StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=pd.Timestamp("2026-05-13T00:00:00Z"),
    )

    result = AISupportService().evaluate(None, context)

    assert result.status == "UNAVAILABLE"
    assert result.candidate_signal is None
    assert result.reason == "NO_STRATEGY_CANDIDATE"


def test_final_decision_is_no_trade_when_strategy_candidate_missing_even_if_ai_supports() -> None:
    context = StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=pd.Timestamp("2026-05-13T00:00:00Z"),
    )
    ai_result = AISupportResult(
        candidate_signal="BUY",
        support_value=100.0,
        confidence=0.99,
        ai_support_score=95.0,
        status="SUPPORTED",
        reason="BULLISH_MODEL_STACK",
    )
    risk = RiskDecision.approved_decision(risk_score=85.0, position_size=0.5)

    decision = FinalDecisionEngine().decide(None, ai_result, risk, context)

    assert decision.signal == DECISION_NO_TRADE
    assert decision.decision_status == DECISION_NO_TRADE
    assert decision.reason == "NO_STRATEGY_SETUP"


def test_strategy_cycle_returns_no_trade_when_null_brain_produces_no_candidate() -> None:
    context = StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=pd.Timestamp("2026-05-13T00:00:00Z"),
    )

    decision = StrategyCycle().run(context)

    assert decision.signal == DECISION_NO_TRADE
    assert decision.reason == "NO_STRATEGY_SETUP"


def test_strategy_brain_repository_creation_sql_is_additive() -> None:
    migration_sql = (ROOT / "migrations" / "020_strategy_brain_round1.sql").read_text(encoding="utf-8")

    for expected in (
        "CREATE TABLE IF NOT EXISTS strategy_decisions",
        "CREATE TABLE IF NOT EXISTS ai_support_evaluations",
        "CREATE TABLE IF NOT EXISTS strategy_performance",
    ):
        assert expected in migration_sql

    for existing in (
        "forecast_runs",
        "forecast_validation",
        "signal_scores",
    ):
        assert f"DROP TABLE {existing}" not in migration_sql
        assert f"DROP TABLE IF EXISTS {existing}" not in migration_sql


def test_strategy_brain_backtest_migration_is_additive() -> None:
    migration_sql = (ROOT / "migrations" / "021_strategy_brain_backtest_runs.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS strategy_backtest_runs" in migration_sql
    assert "CREATE INDEX IF NOT EXISTS idx_strategy_backtest_runs_symbol_tf_time" in migration_sql

    for existing in (
        "strategy_decisions",
        "ai_support_evaluations",
        "strategy_performance",
        "forecast_runs",
        "forecast_validation",
        "signal_scores",
    ):
        assert f"DROP TABLE {existing}" not in migration_sql
        assert f"DROP TABLE IF EXISTS {existing}" not in migration_sql


def test_strategy_brain_example_config_exists_and_contains_no_secrets() -> None:
    config_text = (ROOT / "configs" / "strategy_brain.example.yaml").read_text(encoding="utf-8")

    for expected in (
        "strategy_brain:",
        'main_timeframe: "5m"',
        "risk_per_trade: 0.005",
        "ai_cannot_generate_signal: true",
    ):
        assert expected in config_text

    lower_text = config_text.lower()
    for forbidden in ("password", "secret", "token", "api_key", "dsn"):
        assert forbidden not in lower_text


def test_repository_creation_sql_does_not_remove_existing_tables() -> None:
    sql = "\n".join(
        [
            StrategyDecisionRepository.creation_sql(),
            AISupportRepository.creation_sql(),
            StrategyPerformanceRepository.creation_sql(),
        ]
    )

    assert "CREATE TABLE IF NOT EXISTS strategy_decisions" in sql
    assert "CREATE TABLE IF NOT EXISTS ai_support_evaluations" in sql
    assert "CREATE TABLE IF NOT EXISTS strategy_performance" in sql
    assert "DROP TABLE" not in sql