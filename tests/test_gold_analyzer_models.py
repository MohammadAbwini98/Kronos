from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

import gold_analyzer.models.base as model_base
from gold_analyzer.models.foundation import KronosAdapter
from gold_analyzer.models.base import ForecastPoint, ForecastRequest, ForecastResult
from gold_analyzer.models.volatility import GarchAdapter


def _candles(rows: int = 80) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    close = pd.Series(range(rows), dtype=float) + 2300.0
    return pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0,
        }
    )


def test_forecast_result_schema_serializes_points() -> None:
    point = ForecastPoint(
        forecast_for_ts=pd.Timestamp("2026-01-01T00:05:00Z"),
        horizon_bar=1,
        predicted_close=2301.0,
        predicted_return=0.001,
        predicted_direction="UP",
        confidence=0.7,
    )
    result = ForecastResult(
        model_key="dummy",
        model_version="v1",
        epic="GOLD",
        timeframe="MINUTE_5",
        status="OK",
        latency_ms=12,
        points=[point],
    )

    payload = result.to_dict()

    assert payload["status"] == "OK"
    assert payload["points"][0]["forecast_for_ts"].startswith("2026-01-01T00:05:00")


def test_standard_model_interface_exports_required_shapes() -> None:
    assert model_base.ForecastRequest is ForecastRequest
    assert model_base.ForecastPoint is ForecastPoint
    assert model_base.ForecastResult is ForecastResult
    assert list(ForecastRequest.__dataclass_fields__)[:6] == [
        "epic",
        "timeframe",
        "horizon_bars",
        "context_bars",
        "candles",
        "features",
    ]
    assert list(ForecastPoint.__dataclass_fields__)[:8] == [
        "forecast_for_ts",
        "horizon_bar",
        "predicted_close",
        "predicted_return",
        "predicted_direction",
        "lower_bound",
        "upper_bound",
        "confidence",
    ]
    assert list(ForecastResult.__dataclass_fields__)[:8] == [
        "model_key",
        "model_version",
        "epic",
        "timeframe",
        "status",
        "latency_ms",
        "points",
        "error_message",
    ]


def test_kronos_adapter_skips_when_model_path_missing(tmp_path: Path) -> None:
    request = ForecastRequest(
        epic="GOLD",
        timeframe="MINUTE_5",
        horizon_bars=12,
        context_bars=64,
        candles=_candles(),
    )

    result = KronosAdapter(model_path=tmp_path / "missing").predict(request)

    assert result.status == "SKIPPED"
    assert "does not exist" in (result.error_message or "")


def test_kronos_adapter_skips_when_package_missing_after_path_validation(tmp_path: Path, monkeypatch) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_text("", encoding="utf-8")
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    request = ForecastRequest(
        epic="GOLD",
        timeframe="MINUTE_5",
        horizon_bars=12,
        context_bars=64,
        candles=_candles(),
    )

    result = KronosAdapter(model_path=model_dir).predict(request)

    assert result.status == "SKIPPED"
    assert "not importable" in (result.error_message or "")


def test_garch_adapter_skips_when_arch_missing(monkeypatch) -> None:
    original = importlib.util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name == "arch":
            return None
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    request = ForecastRequest(
        epic="GOLD",
        timeframe="MINUTE_5",
        horizon_bars=12,
        context_bars=64,
        candles=_candles(),
    )

    result = GarchAdapter().predict(request)

    assert result.status == "SKIPPED"
    assert "arch" in (result.error_message or "")


def test_forecast_request_rejects_non_positive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_bars must be positive"):
        ForecastRequest(
            epic="GOLD",
            timeframe="MINUTE_5",
            horizon_bars=0,
            context_bars=64,
            candles=_candles(),
        )


def test_forecast_request_rejects_non_positive_context() -> None:
    with pytest.raises(ValueError, match="context_bars must be positive"):
        ForecastRequest(
            epic="GOLD",
            timeframe="MINUTE_5",
            horizon_bars=12,
            context_bars=0,
            candles=_candles(),
        )


def test_forecast_request_rejects_empty_candles() -> None:
    with pytest.raises(ValueError, match="candles must not be empty"):
        ForecastRequest(
            epic="GOLD",
            timeframe="MINUTE_5",
            horizon_bars=12,
            context_bars=64,
            candles=pd.DataFrame(),
        )
