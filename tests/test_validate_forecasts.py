from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate_forecasts.py"

spec = importlib.util.spec_from_file_location("validate_forecasts", MODULE_PATH)
validate_forecasts = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = validate_forecasts
spec.loader.exec_module(validate_forecasts)


class _QueryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    def __init__(self, forecast_rows: list[dict[str, Any]], actual_rows: list[dict[str, Any]]) -> None:
        self._forecast_rows = forecast_rows
        self._actual_rows = actual_rows
        self.insert_count = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _QueryResult:
        if "FROM forecasts" in sql:
            return _QueryResult(self._forecast_rows)
        if "FROM ohlcv_candles" in sql:
            return _QueryResult(self._actual_rows)
        if "INSERT INTO" in sql:
            self.insert_count += 1
            return _QueryResult([])
        return _QueryResult([])


class _FakeConnectContext:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    def __enter__(self) -> _FakeConn:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _args(*, dry_run: bool) -> validate_forecasts.ValidationArgs:
    return validate_forecasts.ValidationArgs(
        dsn=None,
        mirror_legacy=False,
        model_key=None,
        epic=None,
        timeframe=None,
        lookback_hours=168,
        flat_threshold_pct=0.02,
        trading_cost_pct=0.05,
        min_samples=1,
        dry_run=dry_run,
    )


def test_compute_group_metrics_returns_expected_fields() -> None:
    frame = pd.DataFrame(
        [
            {
                "forecast_for_ts": pd.Timestamp("2026-05-01T00:05:00Z"),
                "predicted_close": 101.0,
                "predicted_return": 1.0,
                "predicted_direction": "UP",
                "confidence": 0.8,
                "latency_ms": 25,
                "close": 101.0,
                "prev_close": 100.0,
                "actual_return_pct": 1.0,
                "actual_direction": "UP",
            },
            {
                "forecast_for_ts": pd.Timestamp("2026-05-01T00:10:00Z"),
                "predicted_close": 100.0,
                "predicted_return": -0.99,
                "predicted_direction": "DOWN",
                "confidence": 0.7,
                "latency_ms": 35,
                "close": 100.0,
                "prev_close": 101.0,
                "actual_return_pct": -0.99,
                "actual_direction": "DOWN",
            },
        ]
    )

    metrics = validate_forecasts._compute_group_metrics(frame, _args(dry_run=True))

    assert metrics["n_samples"] == 2
    assert metrics["direction_accuracy"] == 1.0
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["mape"] == 0.0
    assert metrics["actionable_samples"] == 2
    assert metrics["brier_score"] is not None
    assert isinstance(metrics["calibration_curve"], list)


def test_run_validation_calculates_matured_forecast_results_dry_run(monkeypatch) -> None:
    forecast_rows = [
        {
            "id": 1,
            "run_id": 10,
            "model_key": "kronos",
            "epic": "XAUUSD",
            "timeframe": "MINUTE_5",
            "forecast_for_ts": pd.Timestamp("2026-05-01T00:05:00Z"),
            "horizon_bar": 1,
            "predicted_close": 101.0,
            "predicted_return": 1.0,
            "predicted_direction": "UP",
            "confidence": 0.8,
            "created_at": pd.Timestamp("2026-05-01T00:00:00Z"),
            "latency_ms": 20,
        },
        {
            "id": 2,
            "run_id": 10,
            "model_key": "kronos",
            "epic": "XAUUSD",
            "timeframe": "MINUTE_5",
            "forecast_for_ts": pd.Timestamp("2026-05-01T00:10:00Z"),
            "horizon_bar": 1,
            "predicted_close": 100.0,
            "predicted_return": -0.99,
            "predicted_direction": "DOWN",
            "confidence": 0.7,
            "created_at": pd.Timestamp("2026-05-01T00:00:00Z"),
            "latency_ms": 30,
        },
    ]
    actual_rows = [
        {"timestamp_utc": pd.Timestamp("2026-05-01T00:00:00Z"), "close": 100.0},
        {"timestamp_utc": pd.Timestamp("2026-05-01T00:05:00Z"), "close": 101.0},
        {"timestamp_utc": pd.Timestamp("2026-05-01T00:10:00Z"), "close": 100.0},
    ]

    fake_conn = _FakeConn(forecast_rows=forecast_rows, actual_rows=actual_rows)
    monkeypatch.setattr(validate_forecasts, "connect", lambda _dsn: _FakeConnectContext(fake_conn))

    summary = validate_forecasts.run_validation(_args(dry_run=True))

    assert summary["groups"] == 1
    assert summary["inserted"] == 0
    assert len(summary["rows"]) == 1
    row = summary["rows"][0]
    assert row["model_key"] == "kronos"
    assert row["epic"] == "XAUUSD"
    assert row["timeframe"] == "MINUTE_5"
    assert row["horizon_bar"] == 1
    assert row["direction_accuracy"] == 1.0


def test_run_validation_writes_to_gold_analytics_forecast_validation(monkeypatch) -> None:
    forecast_rows = [
        {
            "id": 1,
            "run_id": 10,
            "model_key": "kronos",
            "epic": "XAUUSD",
            "timeframe": "MINUTE_5",
            "forecast_for_ts": pd.Timestamp("2026-05-01T00:05:00Z"),
            "horizon_bar": 1,
            "predicted_close": 101.0,
            "predicted_return": 1.0,
            "predicted_direction": "UP",
            "confidence": 0.8,
            "created_at": pd.Timestamp("2026-05-01T00:00:00Z"),
            "latency_ms": 20,
        }
    ]
    actual_rows = [
        {"timestamp_utc": pd.Timestamp("2026-05-01T00:00:00Z"), "close": 100.0},
        {"timestamp_utc": pd.Timestamp("2026-05-01T00:05:00Z"), "close": 101.0},
    ]

    fake_conn = _FakeConn(forecast_rows=forecast_rows, actual_rows=actual_rows)
    monkeypatch.setattr(validate_forecasts, "connect", lambda _dsn: _FakeConnectContext(fake_conn))

    summary = validate_forecasts.run_validation(_args(dry_run=False))

    assert summary["groups"] == 1
    assert summary["inserted"] == 1
    assert fake_conn.insert_count >= 1
