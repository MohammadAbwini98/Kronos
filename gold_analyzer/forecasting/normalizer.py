from __future__ import annotations

from gold_analyzer.models.outputs import ForecastPoint, ForecastResult


def normalized_direction(predicted_return: float | None, *, flat_threshold: float = 0.0) -> str:
    if predicted_return is None:
        return "UNKNOWN"
    if predicted_return > flat_threshold:
        return "UP"
    if predicted_return < -flat_threshold:
        return "DOWN"
    return "FLAT"


def normalize_result(result: ForecastResult) -> ForecastResult:
    points: list[ForecastPoint] = []
    for point in result.points:
        direction = str(point.predicted_direction or "").upper()
        if direction in {"", "UNKNOWN"}:
            direction = normalized_direction(point.predicted_return)
        points.append(
            ForecastPoint(
                forecast_for_ts=point.forecast_for_ts,
                horizon_bar=point.horizon_bar,
                predicted_close=point.predicted_close,
                predicted_return=point.predicted_return,
                predicted_direction=direction,
                lower_bound=point.lower_bound,
                upper_bound=point.upper_bound,
                confidence=point.confidence,
                raw=point.raw,
            )
        )
    return ForecastResult(
        model_key=result.model_key,
        model_version=result.model_version,
        epic=result.epic,
        timeframe=result.timeframe,
        status=result.status,
        latency_ms=result.latency_ms,
        points=points,
        error_message=result.error_message,
        raw=result.raw,
    )
