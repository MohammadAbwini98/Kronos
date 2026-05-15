from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from gold_analyzer.models.outputs import ForecastResult


@dataclass(frozen=True)
class EnsemblePoint:
    epic: str
    timeframe: str
    forecast_for_ts: pd.Timestamp
    horizon_bar: int
    ensemble_return: float | None
    ensemble_direction: str
    agreement_score: float
    dispersion_score: float
    confidence: float | None
    model_votes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "epic": self.epic,
            "timeframe": self.timeframe,
            "forecast_for_ts": pd.to_datetime(self.forecast_for_ts, utc=True).isoformat(),
            "horizon_bar": int(self.horizon_bar),
            "ensemble_return": self.ensemble_return,
            "ensemble_direction": self.ensemble_direction,
            "agreement_score": self.agreement_score,
            "dispersion_score": self.dispersion_score,
            "confidence": self.confidence,
            "model_votes": dict(self.model_votes or {}),
        }


class EnsembleBuilder:
    def __init__(self, weights: dict[str, float] | None = None, flat_threshold: float = 0.0) -> None:
        self.weights = weights or {}
        self.flat_threshold = float(flat_threshold)

    def combine(self, results: list[ForecastResult]) -> list[EnsemblePoint]:
        usable = [result for result in results if result.status == "OK" and result.points]
        if not usable:
            return []
        by_horizon: dict[int, list[tuple[ForecastResult, Any]]] = {}
        for result in usable:
            for point in result.points:
                by_horizon.setdefault(int(point.horizon_bar), []).append((result, point))

        output: list[EnsemblePoint] = []
        for horizon_bar in sorted(by_horizon):
            rows = by_horizon[horizon_bar]
            weighted_sum = 0.0
            weight_sum = 0.0
            returns: list[float] = []
            votes: dict[str, dict[str, Any]] = {}
            direction_counts: dict[str, int] = {}
            confidence_values: list[float] = []
            epic = rows[0][0].epic
            timeframe = rows[0][0].timeframe
            ts = rows[0][1].forecast_for_ts
            for result, point in rows:
                direction = str(point.predicted_direction or "UNKNOWN").upper()
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
                if point.confidence is not None:
                    confidence_values.append(float(point.confidence))
                votes[result.model_key] = {
                    "direction": direction,
                    "predicted_close": point.predicted_close,
                    "predicted_return": point.predicted_return,
                    "lower_bound": point.lower_bound,
                    "upper_bound": point.upper_bound,
                    "confidence": point.confidence,
                    "raw": dict(point.raw or {}),
                }
                if point.predicted_return is None:
                    continue
                weight = float(self.weights.get(result.model_key, 1.0))
                weighted_sum += float(point.predicted_return) * weight
                weight_sum += weight
                returns.append(float(point.predicted_return))

            ensemble_return = None if weight_sum <= 0 else weighted_sum / weight_sum
            if ensemble_return is None:
                direction = max(direction_counts, key=direction_counts.get)
            elif ensemble_return > self.flat_threshold:
                direction = "UP"
            elif ensemble_return < -self.flat_threshold:
                direction = "DOWN"
            else:
                direction = "FLAT"
            agreement = max(direction_counts.values()) / max(1, sum(direction_counts.values()))
            dispersion = statistics.pstdev(returns) if len(returns) > 1 else 0.0
            confidence = statistics.fmean(confidence_values) if confidence_values else agreement
            output.append(
                EnsemblePoint(
                    epic=epic,
                    timeframe=timeframe,
                    forecast_for_ts=ts,
                    horizon_bar=horizon_bar,
                    ensemble_return=ensemble_return,
                    ensemble_direction=direction,
                    agreement_score=float(agreement),
                    dispersion_score=float(dispersion),
                    confidence=float(confidence) if confidence is not None else None,
                    model_votes=votes,
                )
            )
        return output
