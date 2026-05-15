from __future__ import annotations

from abc import ABC, abstractmethod

from .outputs import ForecastPoint, ForecastRequest, ForecastResult


__all__ = ["ForecastRequest", "ForecastPoint", "ForecastResult", "ForecastModel"]


class ForecastModel(ABC):
    """Common interface for every forecast-capable model adapter."""

    model_key: str
    model_version: str

    @abstractmethod
    def predict(self, request: ForecastRequest) -> ForecastResult:
        """Return a normalized forecast result without raising for known skips."""
