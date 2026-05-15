from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .ensemble import EnsemblePoint


@dataclass(frozen=True)
class RegimeSnapshot:
    epic: str
    timeframe: str
    regime: str
    trend_strength: float | None = None
    realized_volatility: float | None = None
    garch_volatility: float | None = None
    spread: float | None = None
    liquidity_score: float | None = None
    risk_state: str = "UNKNOWN"
    features: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "epic": self.epic,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "trend_strength": self.trend_strength,
            "realized_volatility": self.realized_volatility,
            "garch_volatility": self.garch_volatility,
            "spread": self.spread,
            "liquidity_score": self.liquidity_score,
            "risk_state": self.risk_state,
            "features": dict(self.features or {}),
        }


class RegimeValidator:
    """Lightweight, past-only regime validator for the first AI pipeline pass."""

    def evaluate(
        self,
        *,
        candles: pd.DataFrame,
        features: pd.DataFrame,
        ensemble: list[EnsemblePoint],
        epic: str | None = None,
        timeframe: str | None = None,
    ) -> RegimeSnapshot:
        epic_value = epic or (ensemble[0].epic if ensemble else str(candles.get("epic", pd.Series(["UNKNOWN"])).iloc[-1] if "epic" in candles else "UNKNOWN"))
        timeframe_value = timeframe or (
            ensemble[0].timeframe if ensemble else str(candles.get("timeframe", pd.Series(["UNKNOWN"])).iloc[-1] if "timeframe" in candles else "UNKNOWN")
        )
        close = pd.to_numeric(candles["close"], errors="coerce").dropna()
        returns = close.pct_change().dropna()
        realized_volatility = None if returns.empty else float(returns.tail(20).std() or 0.0)
        latest_features = features.iloc[-1].to_dict() if not features.empty else {}
        trend_strength = _safe_float(latest_features.get("trend_strength"))
        spread = _safe_float(latest_features.get("spread_pct", latest_features.get("spread")))
        volume_zscore = abs(_safe_float(latest_features.get("volume_zscore")) or 0.0)
        liquidity_score = max(0.0, min(1.0, 1.0 / (1.0 + volume_zscore)))
        garch_volatility = self._garch_volatility_from_ensemble(ensemble)
        risk_state = self._risk_state(realized_volatility, returns)
        if risk_state == "EXTREME":
            regime = "RISK_OFF"
        elif trend_strength is not None and trend_strength >= 0.5:
            direction = str((ensemble[0].ensemble_direction if ensemble else "") or "").upper()
            regime = "TRENDING_UP" if direction == "UP" else "TRENDING_DOWN" if direction == "DOWN" else "TRENDING"
        else:
            regime = "RANGE"
        return RegimeSnapshot(
            epic=epic_value,
            timeframe=timeframe_value,
            regime=regime,
            trend_strength=trend_strength,
            realized_volatility=realized_volatility,
            garch_volatility=garch_volatility,
            spread=spread,
            liquidity_score=liquidity_score,
            risk_state=risk_state,
            features={
                "latest_timestamp": str(latest_features.get("timestamps", "")),
                "volume_zscore": latest_features.get("volume_zscore"),
                "price_z": latest_features.get("price_z"),
                "ensemble_points": len(ensemble),
            },
        )

    @staticmethod
    def _garch_volatility_from_ensemble(ensemble: list[EnsemblePoint]) -> float | None:
        for point in ensemble:
            vote = (point.model_votes or {}).get("garch") or {}
            raw = vote.get("raw") if isinstance(vote, dict) else None
            if isinstance(raw, dict) and raw.get("volatility") is not None:
                return _safe_float(raw.get("volatility"))
        return None

    @staticmethod
    def _risk_state(realized_volatility: float | None, returns: pd.Series) -> str:
        if realized_volatility is None:
            return "UNKNOWN"
        rolling = returns.rolling(20, min_periods=5).std().dropna()
        if rolling.empty:
            return "NORMAL"
        low = float(rolling.quantile(0.25))
        high = float(rolling.quantile(0.80))
        extreme = float(rolling.quantile(0.95))
        if realized_volatility >= extreme:
            return "EXTREME"
        if realized_volatility >= high:
            return "HIGH"
        if realized_volatility <= low:
            return "LOW"
        return "NORMAL"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed
