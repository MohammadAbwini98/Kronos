from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DataQualityState:
    ok: bool
    reason: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def passed(cls, *, details: dict[str, Any] | None = None) -> "DataQualityState":
        return cls(ok=True, reason="OK", details=dict(details or {}))

    @classmethod
    def failed(cls, reason: str, *, details: dict[str, Any] | None = None) -> "DataQualityState":
        return cls(ok=False, reason=reason, details=dict(details or {}))


@dataclass(frozen=True)
class MarketRegimeState:
    regime: str = "UNKNOWN"
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _default_data_quality() -> DataQualityState:
    return DataQualityState.passed()


def _default_market_regime() -> MarketRegimeState:
    return MarketRegimeState()


@dataclass(frozen=True)
class StrategyContext:
    symbol: str
    timeframe: str
    now_utc: pd.Timestamp
    candles: pd.DataFrame | None = None
    data_quality: DataQualityState = field(default_factory=_default_data_quality)
    market_regime: MarketRegimeState = field(default_factory=_default_market_regime)
    indicators: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "now_utc", pd.to_datetime(self.now_utc, utc=True))