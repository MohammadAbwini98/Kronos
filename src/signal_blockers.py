from __future__ import annotations

from typing import Any

from signal_config import SignalConfig


BLOCK_REASONS = {
    "KRONOS_FORECAST_INVALID",
    "FORECAST_DIRECTION_FLAT",
    "FORECAST_EDGE_BELOW_COST",
    "MISSING_5M_INPUT",
    "INVALID_5M_INPUT",
    "MISSING_HIGHER_TIMEFRAME_CONTEXT",
    "HIGHER_TIMEFRAME_CONFLICT",
    "DIRECTION_REGIME_TIMEFRAME_CONFLICT",
    "PROVISIONAL_HIGHER_TIMEFRAME_CONTEXT",
    "WIDE_SPREAD_OR_COST_UNKNOWN",
    "VERY_LOW_VOLUME",
    "EXTREME_VOLATILITY",
    "CADENCE_INVALID",
    "DATABASE_UNAVAILABLE",
    "VALIDATION_DISABLED",
    "VALIDATION_UNAVAILABLE",
}


def _blocked(reason_codes: list[str], reason_details: list[str]) -> dict[str, Any]:
    first = reason_codes[0] if reason_codes else None
    return {
        "blocked": bool(reason_codes),
        "block_reason": first,
        "reason_codes": reason_codes,
        "reason_details": reason_details,
    }


def _hour_confirmation_conflict(candidate_signal: str, timeframe_results: list[dict[str, Any]]) -> bool:
    hour_row = next((row for row in timeframe_results if str(row.get("timeframe")) == "HOUR"), None)
    if not hour_row:
        return False
    trend = str(hour_row.get("trend") or "NEUTRAL").upper()
    if candidate_signal == "LONG" and trend != "BULLISH":
        return True
    if candidate_signal == "SHORT" and trend != "BEARISH":
        return True
    return False


def _trend_opposes_candidate(candidate_signal: str, trend: str) -> bool:
    candidate = str(candidate_signal).upper()
    trend_value = str(trend).upper()
    if candidate == "LONG":
        return trend_value == "BEARISH"
    if candidate == "SHORT":
        return trend_value == "BULLISH"
    return False


def _trend_strength(row: dict[str, Any]) -> float | None:
    snapshot = row.get("indicator_snapshot") or {}
    try:
        value = snapshot.get("trend_strength")
    except AttributeError:
        value = None
    if value is None:
        value = row.get("trend_strength")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strongly_opposes_candidate(candidate_signal: str, row: dict[str, Any], min_strength: float) -> bool:
    if not row:
        return False
    trend = str(row.get("trend") or "NEUTRAL").upper()
    if not _trend_opposes_candidate(candidate_signal, trend):
        return False
    state = str(row.get("alignment_state") or "").upper()
    if state and state != "CONFLICTS":
        return False
    strength = _trend_strength(row)
    return strength is None or strength >= float(min_strength)


def _direction_regime_conflict(
    candidate_signal: str,
    timeframe_results: list[dict[str, Any]],
    *,
    min_strength: float,
) -> tuple[bool, list[str]]:
    candidate = str(candidate_signal).upper()
    if candidate not in {"LONG", "SHORT"}:
        return False, []

    by_timeframe = {str(row.get("timeframe") or "").upper(): row for row in timeframe_results}
    direction_row = by_timeframe.get("MINUTE_15") or {}
    regime_row = by_timeframe.get("MINUTE_30") or {}

    direction_conflict = _strongly_opposes_candidate(candidate, direction_row, min_strength)
    regime_conflict = _strongly_opposes_candidate(candidate, regime_row, min_strength)
    if not (direction_conflict and regime_conflict):
        return False, []

    details = [
        f"15m direction confirmation is {direction_row.get('trend', 'UNKNOWN')} against the 5m {candidate} candidate.",
        f"30m regime confirmation is {regime_row.get('trend', 'UNKNOWN')} against the 5m {candidate} candidate.",
    ]
    return True, details


def evaluate_hard_blockers(
    *,
    normalized_forecast: dict[str, Any] | None,
    primary_input_validation: dict[str, Any] | None,
    context_fetch_status: dict[str, Any] | None,
    timeframe_validations: list[dict[str, Any]] | None,
    config: SignalConfig,
    market_context: dict[str, Any] | None = None,
    database_available: bool = True,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    reason_details: list[str] = []

    market = market_context or {}
    timeframe_results = list(timeframe_validations or [])

    if not config.signal_validation_enabled:
        reason_codes.append("VALIDATION_DISABLED")
        reason_details.append("External signal validation is disabled by configuration.")
        return _blocked(reason_codes, reason_details)

    if not database_available:
        reason_codes.append("DATABASE_UNAVAILABLE")
        reason_details.append("Database is unavailable; validation context cannot be loaded.")
        return _blocked(reason_codes, reason_details)

    if not normalized_forecast:
        reason_codes.append("KRONOS_FORECAST_INVALID")
        reason_details.append("Forecast normalization did not produce a valid payload.")
        return _blocked(reason_codes, reason_details)

    candidate_signal = str(normalized_forecast.get("candidate_signal") or "HOLD").upper()
    forecast_direction = str(normalized_forecast.get("forecast_direction") or "FLAT").upper()
    net_edge_pct = float(normalized_forecast.get("net_edge_pct") or 0.0)

    if forecast_direction == "FLAT":
        reason_codes.append("FORECAST_DIRECTION_FLAT")
        reason_details.append("Forecast direction is FLAT and is blocked by hard validation rules.")

    if net_edge_pct <= 0.0 or net_edge_pct < float(config.signal_min_net_edge_pct):
        reason_codes.append("FORECAST_EDGE_BELOW_COST")
        reason_details.append(
            f"Net edge {net_edge_pct:.4f}% is below required minimum {config.signal_min_net_edge_pct:.4f}%."
        )

    if primary_input_validation is None:
        reason_codes.append("MISSING_5M_INPUT")
        reason_details.append("Primary MINUTE_5 input context is missing.")
    else:
        if not bool(primary_input_validation.get("ok")):
            reason_codes.append("INVALID_5M_INPUT")
            reason_details.append("Primary MINUTE_5 input failed candle integrity checks.")
        if not bool(primary_input_validation.get("cadence_ok", True)):
            reason_codes.append("CADENCE_INVALID")
            reason_details.append("Primary MINUTE_5 input cadence does not match expected resolution interval.")

    if context_fetch_status is None:
        reason_codes.append("VALIDATION_UNAVAILABLE")
        reason_details.append("Higher-timeframe context fetch status is unavailable.")
    else:
        missing = list(context_fetch_status.get("missing_timeframes") or [])
        if missing:
            reason_codes.append("MISSING_HIGHER_TIMEFRAME_CONTEXT")
            reason_details.append(
                "Missing required higher-timeframe context: " + ", ".join(sorted(set(missing)))
            )
        if not bool(context_fetch_status.get("ok", True)) and not missing:
            reason_codes.append("PROVISIONAL_HIGHER_TIMEFRAME_CONTEXT")
            reason_details.append("Higher-timeframe context is provisional and cannot be trusted for scoring.")

    if config.signal_require_hour_confirmation and _hour_confirmation_conflict(candidate_signal, timeframe_results):
        reason_codes.append("HIGHER_TIMEFRAME_CONFLICT")
        reason_details.append("HOUR trend confirmation is required and does not confirm the candidate signal.")

    if config.signal_block_on_direction_regime_conflict:
        conflicts, conflict_details = _direction_regime_conflict(
            candidate_signal,
            timeframe_results,
            min_strength=config.signal_strong_disagreement_trend_strength,
        )
        if conflicts:
            reason_codes.append("DIRECTION_REGIME_TIMEFRAME_CONFLICT")
            reason_details.extend(conflict_details)

    spread_pct = market.get("spread_pct")
    if config.signal_block_on_wide_spread:
        if spread_pct is None:
            reason_codes.append("WIDE_SPREAD_OR_COST_UNKNOWN")
            reason_details.append("Live spread is unavailable, so cost quality cannot be validated.")
        elif float(spread_pct) > float(config.signal_max_spread_pct):
            reason_codes.append("WIDE_SPREAD_OR_COST_UNKNOWN")
            reason_details.append(
                f"Spread {float(spread_pct):.4f}% exceeds configured max {config.signal_max_spread_pct:.4f}%."
            )

    volume_z = market.get("volume_zscore")
    if (
        config.signal_block_on_low_volume
        and volume_z is not None
        and float(volume_z) <= float(config.signal_low_volume_zscore)
    ):
        reason_codes.append("VERY_LOW_VOLUME")
        reason_details.append(
            f"Volume z-score {float(volume_z):.3f} is below threshold {config.signal_low_volume_zscore:.3f}."
        )

    atr_percentile = market.get("atr_percentile")
    if (
        config.signal_block_on_extreme_volatility
        and atr_percentile is not None
        and float(atr_percentile) >= float(config.signal_atr_extreme_percentile)
    ):
        reason_codes.append("EXTREME_VOLATILITY")
        reason_details.append(
            "Volatility regime is extreme "
            f"(ATR percentile {float(atr_percentile):.2f} >= {config.signal_atr_extreme_percentile:.2f})."
        )

    # Keep only known reason codes and preserve insertion order.
    filtered_codes: list[str] = []
    for code in reason_codes:
        if code in BLOCK_REASONS and code not in filtered_codes:
            filtered_codes.append(code)

    return _blocked(filtered_codes, reason_details)
