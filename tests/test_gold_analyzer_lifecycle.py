from __future__ import annotations

from pathlib import Path

import pandas as pd

from gold_analyzer.app.lifecycle import ConfiguredModelRegistry, load_default_models
from gold_analyzer.config import load_models_config
from gold_analyzer.models.base import ForecastModel
from gold_analyzer.models.foundation import Chronos2Adapter
from gold_analyzer.models.local import PatchTSTAdapter
from gold_analyzer.models.outputs import ForecastRequest, ForecastResult


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


class _Model(ForecastModel):
    model_version = "v1"

    def __init__(self, model_key: str) -> None:
        self.model_key = model_key

    def predict(self, request: ForecastRequest) -> ForecastResult:
        return ForecastResult.skipped(
            model_key=self.model_key,
            model_version=self.model_version,
            epic=request.epic,
            timeframe=request.timeframe,
            reason="test",
        )


def test_load_default_models_respects_global_disabled(monkeypatch) -> None:
    monkeypatch.delenv("AI_MODELS_ENABLED", raising=False)
    config = load_models_config("configs/models.example.yaml")

    assert load_default_models(config) == []


def test_load_default_models_wires_enabled_stack(monkeypatch) -> None:
    monkeypatch.setenv("AI_MODELS_ENABLED", "true")
    config = load_models_config("configs/models.example.yaml")

    models = load_default_models(config)

    assert {model.model_key for model in models} == {
        "kronos",
        "chronos2",
        "timesfm",
        "moirai",
        "garch",
        "patchtst",
        "itransformer",
    }


def test_configured_model_registry_filters_by_schedule() -> None:
    models = [_Model("kronos"), _Model("patchtst"), _Model("itransformer"), _Model("garch"), _Model("chronos2")]
    schedule = {
        "1m": {"resolution": "MINUTE", "run_models": False},
        "5m": {"resolution": "MINUTE_5", "run_models": True, "models": ["kronos", "patchtst", "itransformer", "garch"]},
    }
    registry = ConfiguredModelRegistry(models=models, schedule=schedule)

    assert [model.model_key for model in registry.enabled_models(timeframe="MINUTE_5")] == ["kronos", "patchtst", "itransformer", "garch"]
    assert registry.enabled_models(timeframe="MINUTE") == []


def test_non_kronos_adapters_report_missing_readiness(tmp_path: Path) -> None:
    request = ForecastRequest(
        epic="GOLD",
        timeframe="MINUTE_5",
        horizon_bars=12,
        context_bars=64,
        candles=_candles(),
    )

    chronos = Chronos2Adapter(model_path=tmp_path / "chronos2").predict(request)
    patchtst = PatchTSTAdapter(artifact_path=tmp_path / "patchtst.pt").predict(request)

    assert chronos.status == "SKIPPED"
    assert "does not exist" in (chronos.error_message or "")
    assert patchtst.status == "SKIPPED"
    assert "does not exist" in (patchtst.error_message or "")
