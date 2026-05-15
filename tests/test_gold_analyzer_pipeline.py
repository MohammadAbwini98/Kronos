from __future__ import annotations

import pandas as pd

from gold_analyzer.forecasting.pipeline import ForecastingPipeline
from gold_analyzer.forecasting.regime_validator import RegimeSnapshot
from gold_analyzer.models.base import ForecastModel
from gold_analyzer.models.outputs import ForecastPoint, ForecastRequest, ForecastResult


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


class _OkModel(ForecastModel):
    model_key = "ok"
    model_version = "v1"

    def predict(self, request: ForecastRequest) -> ForecastResult:
        return ForecastResult(
            model_key=self.model_key,
            model_version=self.model_version,
            epic=request.epic,
            timeframe=request.timeframe,
            status="OK",
            latency_ms=1,
            points=[
                ForecastPoint(
                    forecast_for_ts=request.candles["timestamps"].iloc[-1] + pd.Timedelta(minutes=5),
                    horizon_bar=1,
                    predicted_close=2400.0,
                    predicted_return=0.02,
                    predicted_direction="UP",
                    confidence=0.8,
                )
            ],
        )


class _BadModel(ForecastModel):
    model_key = "bad"
    model_version = "v1"

    def predict(self, request: ForecastRequest) -> ForecastResult:
        raise RuntimeError("boom")


class _NamedUpModel(ForecastModel):
    model_version = "v1"

    def __init__(self, model_key: str) -> None:
        self.model_key = model_key

    def predict(self, request: ForecastRequest) -> ForecastResult:
        return ForecastResult(
            model_key=self.model_key,
            model_version=self.model_version,
            epic=request.epic,
            timeframe=request.timeframe,
            status="OK",
            latency_ms=1,
            points=[
                ForecastPoint(
                    forecast_for_ts=request.candles["timestamps"].iloc[-1] + pd.Timedelta(minutes=5),
                    horizon_bar=1,
                    predicted_close=2400.0,
                    predicted_return=0.02,
                    predicted_direction="UP",
                    confidence=0.8,
                )
            ],
        )


class _NormalRegimeValidator:
    def evaluate(self, *, candles, features, ensemble, epic=None, timeframe=None):
        return RegimeSnapshot(
            epic=epic or "GOLD",
            timeframe=timeframe or "MINUTE_5",
            regime="TRENDING_UP",
            spread=0.10,
            risk_state="NORMAL",
        )


class _MemoryForecastRepo:
    def __init__(self) -> None:
        self.results = []
        self.ensembles = []

    def save_result(self, result):
        self.results.append(result)

    def save_ensemble(self, ensemble):
        self.ensembles.append(ensemble)


class _MemoryRegimeRepo:
    def __init__(self) -> None:
        self.regimes = []

    def save_regime(self, regime):
        self.regimes.append(regime)


class _MemoryScoreRepo:
    def __init__(self) -> None:
        self.scores = []

    def save_score(self, score):
        self.scores.append(score)


class _MemoryHealthRepo:
    def __init__(self) -> None:
        self.blocked = []

    def save_blocked_cycle(self, *, reason, details):
        self.blocked.append({"reason": reason, "details": details})


def test_pipeline_does_not_block_when_one_model_fails() -> None:
    pipeline = ForecastingPipeline(
        data_loader=lambda _epic, _timeframe, _limit: _candles(),
        models=[_OkModel(), _BadModel()],
    )

    result = pipeline.run_cycle(epic="GOLD", timeframe="MINUTE_5", context_bars=64, horizon_bars=1)

    assert result.quality.ok
    assert [row.status for row in result.model_results] == ["OK", "FAILED"]
    assert len(result.ensemble) == 1
    assert result.ensemble[0].ensemble_direction == "UP"
    assert result.regime is not None
    assert result.score is not None
    assert result.score["candidate_signal"] == "LONG"


def test_pipeline_persists_forecast_ensemble_regime_and_signal_score() -> None:
    forecast_repo = _MemoryForecastRepo()
    regime_repo = _MemoryRegimeRepo()
    score_repo = _MemoryScoreRepo()
    pipeline = ForecastingPipeline(
        data_loader=lambda _epic, _timeframe, _limit: _candles(),
        models=[_OkModel()],
        forecast_repository=forecast_repo,
        regime_repository=regime_repo,
        signal_score_repository=score_repo,
    )

    result = pipeline.run_cycle(epic="GOLD", timeframe="MINUTE_5", context_bars=64, horizon_bars=1)

    assert result.quality.ok
    assert len(forecast_repo.results) == 1
    assert len(forecast_repo.ensembles) == 1
    assert regime_repo.regimes[0]["epic"] == "GOLD"
    assert score_repo.scores[0]["epic"] == "GOLD"
    assert score_repo.scores[0]["timeframe"] == "MINUTE_5"


def test_pipeline_persists_final_buy_decision_when_rules_pass() -> None:
    score_repo = _MemoryScoreRepo()
    pipeline = ForecastingPipeline(
        data_loader=lambda _epic, _timeframe, _limit: _candles(),
        models=[_NamedUpModel("kronos"), _NamedUpModel("chronos2"), _NamedUpModel("timesfm")],
        regime_validator=_NormalRegimeValidator(),
        signal_score_repository=score_repo,
    )

    result = pipeline.run_cycle(epic="GOLD", timeframe="MINUTE_5", context_bars=64, horizon_bars=1)

    assert result.decision is not None
    assert result.decision["decision"] == "BUY"
    assert score_repo.scores[0]["decision"] == "BUY"
    assert "final_decision" in score_repo.scores[0]["features"]


def test_pipeline_records_blocked_cycle_when_candle_quality_fails() -> None:
    health_repo = _MemoryHealthRepo()
    pipeline = ForecastingPipeline(
        data_loader=lambda _epic, _timeframe, _limit: pd.DataFrame(),
        models=[_OkModel()],
        health_repository=health_repo,
    )

    result = pipeline.run_cycle(epic="GOLD", timeframe="MINUTE_5", context_bars=64, horizon_bars=1)

    assert not result.quality.ok
    assert health_repo.blocked[0]["reason"] == "bad_data"
