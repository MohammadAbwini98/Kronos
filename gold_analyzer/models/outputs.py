from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


FORECAST_STATUSES = {"OK", "SKIPPED", "FAILED"}


@dataclass(frozen=True)
class ForecastRequest:
    epic: str
    timeframe: str
    horizon_bars: int
    context_bars: int
    candles: pd.DataFrame
    features: pd.DataFrame | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.horizon_bars <= 0:
            raise ValueError("horizon_bars must be positive")
        if self.context_bars <= 0:
            raise ValueError("context_bars must be positive")
        if self.candles is None or self.candles.empty:
            raise ValueError("candles must not be empty")


@dataclass(frozen=True)
class ForecastPoint:
    forecast_for_ts: pd.Timestamp
    horizon_bar: int
    predicted_close: float | None
    predicted_return: float | None
    predicted_direction: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_for_ts": pd.to_datetime(self.forecast_for_ts, utc=True).isoformat(),
            "horizon_bar": int(self.horizon_bar),
            "predicted_close": self.predicted_close,
            "predicted_return": self.predicted_return,
            "predicted_direction": self.predicted_direction,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "confidence": self.confidence,
            "raw": dict(self.raw or {}),
        }


@dataclass(frozen=True)
class ForecastResult:
    model_key: str
    model_version: str
    epic: str
    timeframe: str
    status: str
    latency_ms: int
    points: list[ForecastPoint] = field(default_factory=list)
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.status.upper()
        if status not in FORECAST_STATUSES:
            raise ValueError(f"Unsupported forecast status: {self.status}")
        object.__setattr__(self, "status", status)

    @classmethod
    def skipped(
        cls,
        *,
        model_key: str,
        model_version: str,
        epic: str,
        timeframe: str,
        reason: str,
        latency_ms: int = 0,
        raw: dict[str, Any] | None = None,
    ) -> "ForecastResult":
        return cls(
            model_key=model_key,
            model_version=model_version,
            epic=epic,
            timeframe=timeframe,
            status="SKIPPED",
            latency_ms=latency_ms,
            points=[],
            error_message=reason,
            raw=raw or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        model_key: str,
        model_version: str,
        epic: str,
        timeframe: str,
        error: str,
        latency_ms: int = 0,
        raw: dict[str, Any] | None = None,
    ) -> "ForecastResult":
        return cls(
            model_key=model_key,
            model_version=model_version,
            epic=epic,
            timeframe=timeframe,
            status="FAILED",
            latency_ms=latency_ms,
            points=[],
            error_message=error,
            raw=raw or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "model_version": self.model_version,
            "epic": self.epic,
            "timeframe": self.timeframe,
            "status": self.status,
            "latency_ms": int(self.latency_ms),
            "points": [point.to_dict() for point in self.points],
            "error_message": self.error_message,
            "raw": dict(self.raw or {}),
        }
