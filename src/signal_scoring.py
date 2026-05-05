from __future__ import annotations

from typing import Any

from higher_timeframe_validator import TIMEFRAME_ALIGNMENT_WEIGHTS
from signal_config import SignalConfig


MAX_COMPONENT_SCORES = {
    "kronos_forecast": 35.0,
    "higher_timeframe_alignment": 25.0,
    "momentum": 10.0,
    "volume": 10.0,
    "cost_liquidity": 10.0,
    "volatility": 5.0,
    "support_resistance": 5.0,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _bucket_confidence(total_score: float) -> str:
    if total_score >= 85.0:
        return "VERY_HIGH"
    if total_score >= 70.0:
        return "HIGH"
    if total_score >= 60.0:
        return "MEDIUM"
    if total_score >= 50.0:
        return "LOW"
    return "NONE"


def _final_signal(candidate_signal: str, total_score: float, config: SignalConfig) -> str:
    candidate = str(candidate_signal).upper()
    if candidate not in {"LONG", "SHORT"}:
        return "HOLD"

    if total_score >= config.signal_score_strong_threshold:
        return "STRONG_LONG" if candidate == "LONG" else "STRONG_SHORT"
    if total_score >= config.signal_score_actionable_threshold:
        return "LONG" if candidate == "LONG" else "SHORT"
    if total_score >= config.signal_score_weak_threshold:
        return "WEAK_LONG" if candidate == "LONG" else "WEAK_SHORT"
    if total_score >= config.signal_score_watch_threshold:
        return "WATCH"
    return "HOLD"


def _aggregate_timeframe_scores(timeframe_validations: list[dict[str, Any]]) -> dict[str, float]:
    if not timeframe_validations:
        return {
            "alignment": 0.0,
            "momentum": 0.0,
            "volume": 0.0,
            "volatility": 0.0,
            "support_resistance": 0.0,
        }

    alignment_raw = 0.0
    momentum_raw = 0.0
    volume_raw = 0.0
    volatility_raw = 0.0
    sr_raw = 0.0

    momentum_cap = 0.0
    volume_cap = 0.0
    volatility_cap = 0.0
    sr_cap = 0.0

    for row in timeframe_validations:
        timeframe = str(row.get("timeframe") or "").upper()
        alignment_cap = float(TIMEFRAME_ALIGNMENT_WEIGHTS.get(timeframe, 0.0))
        trend_score = float(row.get("trend_score") or 0.0)
        alignment_raw += _clamp(trend_score, 0.0, alignment_cap)

        momentum_raw += float(row.get("momentum_score") or 0.0)
        volume_raw += float(row.get("volume_score") or 0.0)
        volatility_raw += float(row.get("volatility_score") or 0.0)
        sr_raw += float(row.get("support_resistance_score") or 0.0)

        momentum_cap += 2.0
        volume_cap += 2.0
        volatility_cap += 1.0
        sr_cap += 1.0

    momentum_scaled = 0.0 if momentum_cap <= 0 else (momentum_raw / momentum_cap) * MAX_COMPONENT_SCORES["momentum"]
    volume_scaled = 0.0 if volume_cap <= 0 else (volume_raw / volume_cap) * MAX_COMPONENT_SCORES["volume"]
    volatility_scaled = 0.0 if volatility_cap <= 0 else (volatility_raw / volatility_cap) * MAX_COMPONENT_SCORES["volatility"]
    sr_scaled = 0.0 if sr_cap <= 0 else (sr_raw / sr_cap) * MAX_COMPONENT_SCORES["support_resistance"]

    return {
        "alignment": _clamp(alignment_raw, 0.0, MAX_COMPONENT_SCORES["higher_timeframe_alignment"]),
        "momentum": _clamp(momentum_scaled, 0.0, MAX_COMPONENT_SCORES["momentum"]),
        "volume": _clamp(volume_scaled, 0.0, MAX_COMPONENT_SCORES["volume"]),
        "volatility": _clamp(volatility_scaled, 0.0, MAX_COMPONENT_SCORES["volatility"]),
        "support_resistance": _clamp(sr_scaled, 0.0, MAX_COMPONENT_SCORES["support_resistance"]),
    }


def score_signal(
    *,
    normalized_forecast: dict[str, Any],
    timeframe_validations: list[dict[str, Any]],
    blockers: dict[str, Any],
    config: SignalConfig,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market = market_context or {}
    candidate_signal = str(normalized_forecast.get("candidate_signal") or "HOLD").upper()

    if blockers.get("blocked"):
        return {
            "candidate_signal": candidate_signal,
            "final_signal": "BLOCKED",
            "confidence_level": "NONE",
            "total_score": 0.0,
            "blocked": True,
            "block_reason": blockers.get("block_reason"),
            "component_scores": {
                "kronos_forecast": 0.0,
                "higher_timeframe_alignment": 0.0,
                "momentum": 0.0,
                "volume": 0.0,
                "cost_liquidity": 0.0,
                "volatility": 0.0,
                "support_resistance": 0.0,
            },
            "penalty_score": 0.0,
            "reason_codes": list(blockers.get("reason_codes") or []),
            "reason_details": list(blockers.get("reason_details") or []),
        }

    net_edge_pct = float(normalized_forecast.get("net_edge_pct") or 0.0)
    path_consistency = float(normalized_forecast.get("forecast_path_consistency_score") or 0.0)
    quality_score = float(normalized_forecast.get("forecast_quality_score") or 0.0)

    edge_scale = max(config.signal_min_net_edge_pct * 4.0, 0.10)
    edge_component = _clamp((net_edge_pct / edge_scale) * 20.0, 0.0, 20.0)
    consistency_component = _clamp((path_consistency / 100.0) * 10.0, 0.0, 10.0)
    quality_component = _clamp((quality_score / 100.0) * 5.0, 0.0, 5.0)
    kronos_forecast_score = _clamp(edge_component + consistency_component + quality_component, 0.0, 35.0)

    tf_scores = _aggregate_timeframe_scores(timeframe_validations)

    cost_liquidity_score = 10.0
    spread_pct = market.get("spread_pct")
    if spread_pct is not None:
        spread_value = float(spread_pct)
        if spread_value > config.signal_max_spread_pct:
            cost_liquidity_score -= 4.0
        elif spread_value > (config.signal_max_spread_pct * 0.75):
            cost_liquidity_score -= 2.0

    if net_edge_pct < (config.signal_min_net_edge_pct * 2.0):
        cost_liquidity_score -= 2.0
    cost_liquidity_score = _clamp(cost_liquidity_score, 0.0, 10.0)

    components = {
        "kronos_forecast": round(kronos_forecast_score, 4),
        "higher_timeframe_alignment": round(tf_scores["alignment"], 4),
        "momentum": round(tf_scores["momentum"], 4),
        "volume": round(tf_scores["volume"], 4),
        "cost_liquidity": round(cost_liquidity_score, 4),
        "volatility": round(tf_scores["volatility"], 4),
        "support_resistance": round(tf_scores["support_resistance"], 4),
    }

    penalty_score = 0.0
    total = _clamp(sum(components.values()) - penalty_score, 0.0, 100.0)

    final_signal = _final_signal(candidate_signal, total, config)
    confidence = _bucket_confidence(total)

    reasons: list[str] = []
    if final_signal in {"WATCH", "HOLD"} and candidate_signal in {"LONG", "SHORT"}:
        reasons.append("Candidate signal did not clear final scoring thresholds.")

    return {
        "candidate_signal": candidate_signal,
        "final_signal": final_signal,
        "confidence_level": confidence,
        "total_score": round(total, 4),
        "blocked": False,
        "block_reason": None,
        "component_scores": components,
        "penalty_score": round(penalty_score, 4),
        "reason_codes": [],
        "reason_details": reasons,
    }
