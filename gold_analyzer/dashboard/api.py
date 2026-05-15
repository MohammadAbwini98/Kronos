from __future__ import annotations

from gold_analyzer.db.repositories import ForecastRepository, SignalScoreRepository, ValidationRepository


def ai_forecasts(*, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict:
    return ForecastRepository().list_forecasts(epic=epic, timeframe=timeframe, limit=limit)


def ai_ensemble(*, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict:
    return ForecastRepository().list_ensemble(epic=epic, timeframe=timeframe, limit=limit)


def ai_regime(*, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict:
    return ValidationRepository().list_regime(epic=epic, timeframe=timeframe, limit=limit)


def ai_scorer(*, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict:
    return SignalScoreRepository().list_scores(epic=epic, timeframe=timeframe, limit=limit)


def ai_forecast_validation(*, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict:
    return ValidationRepository().list_validation(epic=epic, timeframe=timeframe, limit=limit)
