from __future__ import annotations

from collections.abc import Iterable

from .base import ForecastModel


class ModelRegistry:
    """Small in-process registry used by the optional forecasting pipeline."""

    def __init__(self, models: Iterable[ForecastModel] | None = None) -> None:
        self._models: dict[str, ForecastModel] = {}
        for model in models or []:
            self.register(model)

    def register(self, model: ForecastModel) -> None:
        self._models[model.model_key] = model

    def get(self, model_key: str) -> ForecastModel | None:
        return self._models.get(model_key)

    def enabled_models(self, keys: Iterable[str] | None = None, timeframe: str | None = None) -> list[ForecastModel]:
        if keys is None:
            models = list(self._models.values())
        else:
            models = [self._models[key] for key in keys if key in self._models]
        if timeframe is None:
            return models
        normalized = str(timeframe).strip().upper()
        return [model for model in models if _model_supports_timeframe(model, normalized)]


def _model_supports_timeframe(model: ForecastModel, timeframe: str) -> bool:
    for attr_name in ("enabled_timeframes", "supported_timeframes", "timeframes"):
        value = getattr(model, attr_name, None)
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip().upper()
            if text in {"*", "ALL", "ANY"}:
                return True
            return text == timeframe
        if isinstance(value, Iterable):
            normalized = {str(item).strip().upper() for item in value}
            if {"*", "ALL", "ANY"}.intersection(normalized):
                return True
            return timeframe in normalized
        return bool(value)
    return True
