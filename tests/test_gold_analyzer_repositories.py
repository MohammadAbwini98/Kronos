from __future__ import annotations

import pandas as pd

from gold_analyzer.db.repositories import ForecastRepository, SignalScoreRepository, ValidationRepository
from gold_analyzer.models.outputs import ForecastPoint, ForecastResult


class _Result:
    def __init__(self, row=None, rows=None) -> None:
        self.row = row if row is not None else {"id": 1}
        self.rows = rows if rows is not None else []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Result()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_forecast_repository_insert_result_records_run_and_points() -> None:
    conn = _Conn()
    repo = ForecastRepository(connect_factory=lambda _dsn: conn)
    result = ForecastResult(
        model_key="dummy",
        model_version="v1",
        epic="GOLD",
        timeframe="MINUTE_5",
        status="OK",
        latency_ms=5,
        points=[
            ForecastPoint(
                forecast_for_ts=pd.Timestamp("2026-01-01T00:05:00Z"),
                horizon_bar=1,
                predicted_close=2301.0,
                predicted_return=0.01,
                predicted_direction="UP",
            )
        ],
    )

    run_id = repo.save_result(result)

    assert run_id == 1
    assert len(conn.calls) == 2
    assert "INSERT INTO forecast_runs" in conn.calls[0][0]
    assert "INSERT INTO forecasts" in conn.calls[1][0]


def test_validation_repository_can_save_regime_snapshot() -> None:
    conn = _Conn()
    repo = ValidationRepository(connect_factory=lambda _dsn: conn)

    regime_id = repo.save_regime(
        {
            "epic": "GOLD",
            "timeframe": "MINUTE_5",
            "regime": "RANGE",
            "trend_strength": 0.1,
            "realized_volatility": 0.01,
            "garch_volatility": None,
            "spread": 0.02,
            "liquidity_score": 0.9,
            "risk_state": "NORMAL",
            "features": {"source": "test"},
        }
    )

    assert regime_id == 1
    assert "INSERT INTO regime_snapshots" in conn.calls[0][0]


def test_signal_score_repository_can_save_pipeline_score() -> None:
    conn = _Conn()
    repo = SignalScoreRepository(connect_factory=lambda _dsn: conn)

    score_id = repo.save_score(
        {
            "epic": "GOLD",
            "timeframe": "MINUTE_5",
            "candidate_signal": "LONG",
            "probability_win": 0.7,
            "probability_loss": 0.3,
            "expected_return": 0.01,
            "model_agreement": 1.0,
            "risk_score": 0.25,
            "scorer_model": "fallback",
            "features": {"source": "test"},
            "decision": "LONG",
        }
    )

    assert score_id == 1
    assert "INSERT INTO signal_scores" in conn.calls[0][0]
