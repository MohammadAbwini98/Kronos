from __future__ import annotations

from contextlib import contextmanager

import pandas as pd

from gold_analyzer.ai_support.models import AISupportResult
from gold_analyzer.orchestration.strategy_cycle import StrategyCycle
from gold_analyzer.repositories.ai_support_repository import AISupportRepository
from gold_analyzer.repositories.strategy_decision_repository import StrategyDecisionRepository
from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.models import StrategyCandidate
from gold_analyzer.strategy_brain.risk import RiskDecision


class _StaticBrain:
    def __init__(self, candidate: StrategyCandidate | None) -> None:
        self.candidate = candidate

    def generate_candidate(self, context):
        return self.candidate


class _StaticAISupportService:
    def __init__(self, result: AISupportResult) -> None:
        self.result = result

    def evaluate(self, candidate, context):
        return self.result


class _StaticRiskManager:
    def __init__(self, result: RiskDecision) -> None:
        self.result = result

    def evaluate(self, candidate, context):
        return self.result


class _RecordingDecisionRepository:
    def __init__(self, decision_id: int = 42) -> None:
        self.decision_id = decision_id
        self.saved = []

    def save(self, decision):
        self.saved.append(decision)
        return self.decision_id


class _RecordingAISupportRepository:
    def __init__(self) -> None:
        self.calls = []

    def save_result(self, *, decision_id, symbol, timeframe, result):
        self.calls.append(
            {
                "decision_id": decision_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "result": result,
            }
        )
        return 1


class _FakeResult:
    def __init__(self, row=None, rows=None) -> None:
        self._row = row or {"id": 1}
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _FakeResult({"id": 7})


def _context() -> StrategyContext:
    candles = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=3, freq="5min", tz="UTC"),
            "open": [100.0, 100.1, 100.2],
            "high": [100.4, 100.5, 100.6],
            "low": [99.6, 99.7, 99.8],
            "close": [100.1, 100.2, 100.3],
            "ATR_14": [1.0, 1.0, 1.0],
            "spread": [0.1, 0.1, 0.1],
        }
    )
    return StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=candles["ts"].iloc[-1],
        candles=candles,
    )


def test_strategy_cycle_links_ai_support_rows_to_saved_decision() -> None:
    candidate = StrategyCandidate(
        signal="BUY",
        strategy_type="trend_pullback",
        entry_price=100.3,
        stop_loss=99.1,
        take_profit_1=101.2,
        take_profit_2=102.1,
        strategy_score=82.0,
        indicators={"ATR_14": 1.0},
    )
    ai_result = AISupportResult.neutral(
        candidate_signal="BUY",
        reason="AI_NEUTRAL",
        evaluations=[{"model_key": "kronos", "model_status": "SKIPPED", "candidate_signal": "BUY", "support_value": 0.0}],
    )
    decision_repository = _RecordingDecisionRepository(decision_id=314)
    ai_repository = _RecordingAISupportRepository()
    cycle = StrategyCycle(
        brain=_StaticBrain(candidate),
        ai_support_service=_StaticAISupportService(ai_result),
        risk_manager=_StaticRiskManager(RiskDecision.approved_decision(risk_score=88.0, position_size=1.25)),
        decision_repository=decision_repository,
        ai_support_repository=ai_repository,
    )

    decision = cycle.run(_context())

    assert decision.signal == "BUY"
    assert len(decision_repository.saved) == 1
    assert ai_repository.calls == [
        {
            "decision_id": 314,
            "symbol": "GOLD",
            "timeframe": "5m",
            "result": ai_result,
        }
    ]


def test_strategy_cycle_does_not_persist_ai_support_without_strategy_candidate() -> None:
    decision_repository = _RecordingDecisionRepository(decision_id=99)
    ai_repository = _RecordingAISupportRepository()
    cycle = StrategyCycle(
        brain=_StaticBrain(None),
        decision_repository=decision_repository,
        ai_support_repository=ai_repository,
    )

    decision = cycle.run(_context())

    assert decision.signal == "NO_TRADE"
    assert len(decision_repository.saved) == 1
    assert ai_repository.calls == []


def test_strategy_decision_repository_sanitizes_non_finite_values_before_insert() -> None:
    connection = _RecordingConnection()

    @contextmanager
    def connect_factory(_dsn=None):
        yield connection

    repository = StrategyDecisionRepository(connect_factory=connect_factory)
    decision = repository.save(
        decision=__import__("gold_analyzer.strategy_brain.decision", fromlist=["StrategyDecision"]).StrategyDecision(
            symbol="GOLD",
            timeframe="5m",
            computed_at=pd.Timestamp("2026-01-01T00:00:00Z"),
            signal="BUY",
            decision_status="APPROVED",
            reason="STRATEGY_CANDIDATE_APPROVED",
            entry_price=float("nan"),
            stop_loss=float("inf"),
            take_profit_1=101.0,
            take_profit_2=float("-inf"),
            position_size=1.5,
            risk_reward_1=float("nan"),
            risk_reward_2=2.0,
            strategy_score=float("nan"),
            ai_support_score=float("inf"),
            risk_score=80.0,
            final_score=float("nan"),
            blocked_by=["RISK", float("nan")],
            indicators={"ATR_14": float("inf")},
            ai_details={"at": pd.Timestamp("2026-01-01T00:00:00Z"), "confidence": float("nan")},
            risk_details={"details": {"stop_distance_atr": float("-inf")}},
        )
    )

    assert decision == 7
    _sql, params = connection.calls[-1]
    assert params[6] is None
    assert params[7] is None
    assert params[9] is None
    assert params[11] is None
    assert params[13] is None
    assert params[14] is None
    assert params[16] is None
    assert params[19].obj == ["RISK", None]
    assert params[20].obj == {"ATR_14": None}
    assert params[21].obj["confidence"] is None
    assert params[21].obj["at"] == "2026-01-01T00:00:00+00:00"
    assert params[22].obj == {"details": {"stop_distance_atr": None}}


def test_ai_support_repository_sanitizes_evaluation_payloads_before_insert() -> None:
    connection = _RecordingConnection()

    @contextmanager
    def connect_factory(_dsn=None):
        yield connection

    repository = AISupportRepository(connect_factory=connect_factory)
    result = AISupportResult.neutral(
        candidate_signal="BUY",
        evaluations=[
            {
                "model_key": "kronos",
                "model_status": "FAILED",
                "candidate_signal": "BUY",
                "predicted_return": float("nan"),
                "support_value": float("inf"),
                "confidence": float("nan"),
                "latency_ms": float("nan"),
                "raw_json": {"extreme": float("-inf")},
            }
        ],
    )

    saved = repository.save_result(decision_id=123, symbol="GOLD", timeframe="5m", result=result)

    assert saved == 1
    _sql, params = connection.calls[-1]
    assert params[6] is None
    assert params[8] is None
    assert params[9] is None
    assert params[10] is None
    assert params[11].obj == {"extreme": None}