from __future__ import annotations

import importlib.util
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from gold_analyzer.models.base import ForecastModel, ForecastPoint, ForecastRequest, ForecastResult


@dataclass(frozen=True)
class VolatilityEstimate:
    status: str
    risk_state: str
    volatility: float | None = None
    error_message: str | None = None
    raw: dict[str, Any] | None = None


class GarchAdapter(ForecastModel):
    model_key = "garch"

    def __init__(self, *, model_version: str = "garch-v1", window_bars: int = 1000) -> None:
        self.model_version = model_version
        self.window_bars = max(50, int(window_bars))

    def predict(self, request: ForecastRequest) -> ForecastResult:
        started = time.perf_counter()
        estimate = self.estimate(request.candles)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if estimate.status != "OK":
            return ForecastResult.skipped(
                model_key=self.model_key,
                model_version=self.model_version,
                epic=request.epic,
                timeframe=request.timeframe,
                reason=estimate.error_message or "GARCH volatility estimate skipped.",
                latency_ms=latency_ms,
                raw=estimate.raw or {},
            )
        last_ts = pd.to_datetime(request.candles["timestamps"].iloc[-1], utc=True)
        point = ForecastPoint(
            forecast_for_ts=last_ts,
            horizon_bar=1,
            predicted_close=None,
            predicted_return=None,
            predicted_direction="VOLATILITY",
            confidence=None,
            raw={"risk_state": estimate.risk_state, "volatility": estimate.volatility},
        )
        return ForecastResult(
            model_key=self.model_key,
            model_version=self.model_version,
            epic=request.epic,
            timeframe=request.timeframe,
            status="OK",
            latency_ms=latency_ms,
            points=[point],
            raw=estimate.raw or {},
        )

    def estimate(self, candles: pd.DataFrame) -> VolatilityEstimate:
        if importlib.util.find_spec("arch") is None:
            return VolatilityEstimate(
                status="SKIPPED",
                risk_state="UNKNOWN",
                error_message="Optional dependency 'arch' is not installed.",
            )
        close = pd.to_numeric(candles["close"], errors="coerce").dropna()
        returns = close.pct_change().dropna().tail(self.window_bars) * 100.0
        if len(returns) < 50:
            return VolatilityEstimate(
                status="SKIPPED",
                risk_state="UNKNOWN",
                error_message=f"Not enough return samples for GARCH: {len(returns)}/50",
            )
        try:
            from arch import arch_model

            fitted = arch_model(returns, p=1, q=1, mean="Zero", vol="Garch", rescale=False).fit(disp="off")
            forecast = fitted.forecast(horizon=1)
            variance = float(forecast.variance.iloc[-1, 0])
            volatility = variance ** 0.5
        except Exception as exc:  # noqa: BLE001
            return VolatilityEstimate(status="SKIPPED", risk_state="UNKNOWN", error_message=str(exc))
        thresholds = returns.rolling(20, min_periods=5).std().dropna()
        if thresholds.empty:
            risk_state = "NORMAL"
        else:
            low = float(thresholds.quantile(0.25))
            high = float(thresholds.quantile(0.80))
            extreme = float(thresholds.quantile(0.95))
            if volatility >= extreme:
                risk_state = "EXTREME"
            elif volatility >= high:
                risk_state = "HIGH"
            elif volatility <= low:
                risk_state = "LOW"
            else:
                risk_state = "NORMAL"
        return VolatilityEstimate(
            status="OK",
            risk_state=risk_state,
            volatility=float(volatility),
            raw={"sample_count": int(len(returns))},
        )
