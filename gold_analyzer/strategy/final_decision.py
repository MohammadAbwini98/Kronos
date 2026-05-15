from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gold_analyzer.forecasting.ensemble import EnsemblePoint
from gold_analyzer.forecasting.regime_validator import RegimeSnapshot


DECISION_BUY = "BUY"
DECISION_SELL = "SELL"
DECISION_NO_TRADE = "NO_TRADE"

_ENSEMBLE_TO_DECISION = {
    "UP": DECISION_BUY,
    "LONG": DECISION_BUY,
    "BUY": DECISION_BUY,
    "DOWN": DECISION_SELL,
    "SHORT": DECISION_SELL,
    "SELL": DECISION_SELL,
}

_SCORER_TO_DECISION = {
    "LONG": DECISION_BUY,
    "BUY": DECISION_BUY,
    "SHORT": DECISION_SELL,
    "SELL": DECISION_SELL,
}


@dataclass(frozen=True)
class FinalDecisionThresholds:
    min_model_agreement: float = 0.60
    max_forecast_dispersion: float = 0.40
    min_probability_win: float = 0.62
    min_predicted_move_spread_multiple: float = 2.0
    max_spread_pct: float = 0.12
    max_moirai_uncertainty_width: float = 0.40
    block_when_garch_risk: str = "EXTREME"
    min_supporting_model_agreements: int = 2


class FinalDecisionEngine:
    """Convert model/scorer evidence into BUY, SELL, or NO_TRADE."""

    def __init__(self, thresholds: FinalDecisionThresholds | None = None) -> None:
        self.thresholds = thresholds or FinalDecisionThresholds()

    def decide(
        self,
        *,
        score: dict[str, Any],
        regime: RegimeSnapshot,
        ensemble: list[EnsemblePoint] | None = None,
    ) -> dict[str, Any]:
        points = list(ensemble or [])
        first = points[0] if points else None
        if first is None:
            return self._no_trade("NO_ENSEMBLE", "NO_TRADE because no ensemble forecast is available.", score, regime)

        ensemble_decision = _decision_from_direction(first.ensemble_direction)
        if ensemble_decision is None:
            return self._no_trade(
                "ENSEMBLE_DIRECTION_FLAT",
                f"NO_TRADE because ensemble direction is {first.ensemble_direction or 'UNKNOWN'}.",
                score,
                regime,
                first,
            )

        votes = _votes(first)
        reasons: list[str] = []
        reason_codes: list[str] = []

        agreement = _float(score.get("model_agreement"), first.agreement_score)
        if agreement < self.thresholds.min_model_agreement:
            reason_codes.append("MODEL_AGREEMENT_BELOW_MINIMUM")
            reasons.append(
                f"NO_TRADE because forecast agreement is {agreement:.2f} below minimum {self.thresholds.min_model_agreement:.2f}."
            )

        dispersion = _float(score.get("forecast_dispersion"), first.dispersion_score)
        if dispersion > self.thresholds.max_forecast_dispersion:
            reason_codes.append("FORECAST_DISPERSION_TOO_WIDE")
            reasons.append(
                f"NO_TRADE because forecast dispersion is {dispersion:.2f} above maximum {self.thresholds.max_forecast_dispersion:.2f}."
            )

        scorer_decision = _decision_from_scorer(score.get("candidate_signal") or score.get("decision"))
        if scorer_decision is None:
            reason_codes.append("SCORER_DIRECTION_NOT_ACTIONABLE")
            reasons.append("NO_TRADE because scorer direction is not actionable.")
        elif scorer_decision != ensemble_decision:
            reason_codes.append("SCORER_DIRECTION_DISAGREES_WITH_ENSEMBLE")
            reasons.append(
                f"NO_TRADE because scorer direction {scorer_decision} disagrees with ensemble {ensemble_decision}."
            )

        probability_win = _float(score.get("probability_win"))
        if probability_win is None or probability_win < self.thresholds.min_probability_win:
            reason_codes.append("SCORER_PROBABILITY_BELOW_MINIMUM")
            observed = "unavailable" if probability_win is None else f"{probability_win:.2f}"
            reasons.append(
                f"NO_TRADE because scorer probability_win is {observed} below minimum {self.thresholds.min_probability_win:.2f}."
            )

        kronos_vote = _find_vote(votes, ("kronos",))
        if kronos_vote is None:
            reason_codes.append("KRONOS_VOTE_MISSING")
            reasons.append("NO_TRADE because Kronos vote is missing from the ensemble.")
        elif _decision_from_direction(kronos_vote.get("direction")) != ensemble_decision:
            reason_codes.append("KRONOS_DISAGREES_WITH_ENSEMBLE")
            reasons.append("NO_TRADE because Kronos does not agree with the ensemble direction.")

        supporting = _supporting_agreements(votes, ensemble_decision)
        if len(supporting) < self.thresholds.min_supporting_model_agreements:
            reason_codes.append("SUPPORTING_MODEL_AGREEMENT_BELOW_MINIMUM")
            reasons.append(
                "NO_TRADE because fewer than "
                f"{self.thresholds.min_supporting_model_agreements} Chronos-2/TimesFM/local models agree with the ensemble."
            )

        moirai_width = _moirai_uncertainty_width(votes)
        if moirai_width is not None and moirai_width > self.thresholds.max_moirai_uncertainty_width:
            reason_codes.append("MOIRAI_UNCERTAINTY_TOO_WIDE")
            reasons.append(
                f"NO_TRADE because Moirai uncertainty width is {moirai_width:.2f} above maximum "
                f"{self.thresholds.max_moirai_uncertainty_width:.2f}."
            )

        score_features = score.get("features") if isinstance(score.get("features"), dict) else {}
        risk_state = str(regime.risk_state or score_features.get("risk_state") or "UNKNOWN").upper()
        if risk_state == self.thresholds.block_when_garch_risk.upper():
            reason_codes.append("GARCH_RISK_EXTREME")
            reasons.append(f"NO_TRADE because GARCH/volatility risk is {risk_state}.")

        spread_pct = _spread_pct(score=score, regime=regime)
        if spread_pct is None:
            reason_codes.append("SPREAD_UNAVAILABLE")
            reasons.append("NO_TRADE because spread is unavailable.")
        elif spread_pct > self.thresholds.max_spread_pct:
            reason_codes.append("SPREAD_ABOVE_MAXIMUM")
            reasons.append(
                f"NO_TRADE because spread is {spread_pct:.4f}% above maximum {self.thresholds.max_spread_pct:.4f}%."
            )

        predicted_move = abs(_float(score.get("expected_return"), first.ensemble_return) or 0.0)
        spread_return = None if spread_pct is None else spread_pct / 100.0
        if spread_return is not None and predicted_move < (spread_return * self.thresholds.min_predicted_move_spread_multiple):
            reason_codes.append("PREDICTED_MOVE_BELOW_SPREAD_MULTIPLE")
            reasons.append("NO_TRADE because predicted move is smaller than 2x spread.")

        if _higher_timeframe_strongly_opposes(score, ensemble_decision):
            reason_codes.append("HIGHER_TIMEFRAME_STRONGLY_OPPOSES")
            reasons.append("NO_TRADE because higher timeframe context strongly opposes the ensemble direction.")

        if reasons:
            return self._no_trade(reason_codes[0], reasons[0], score, regime, first, reasons, reason_codes)

        reason = (
            f"{ensemble_decision} because Kronos, {', '.join(supporting[:3])} agree "
            f"and scorer probability_win={probability_win:.2f}."
        )
        return {
            "decision": ensemble_decision,
            "candidate_signal": score.get("candidate_signal"),
            "reason": reason,
            "reason_codes": [],
            "reason_details": [reason],
            "checks": self._checks(
                score=score,
                regime=regime,
                ensemble=first,
                spread_pct=spread_pct,
                predicted_move=predicted_move,
                supporting_models=supporting,
                moirai_uncertainty_width=moirai_width,
            ),
        }

    def _no_trade(
        self,
        code: str,
        reason: str,
        score: dict[str, Any],
        regime: RegimeSnapshot,
        ensemble: EnsemblePoint | None = None,
        reasons: list[str] | None = None,
        reason_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "decision": DECISION_NO_TRADE,
            "candidate_signal": score.get("candidate_signal"),
            "reason": reason,
            "reason_codes": list(reason_codes or [code]),
            "reason_details": list(reasons or [reason]),
            "checks": self._checks(
                score=score,
                regime=regime,
                ensemble=ensemble,
                spread_pct=_spread_pct(score=score, regime=regime),
                predicted_move=abs(_float(score.get("expected_return"), None) or 0.0),
                supporting_models=[] if ensemble is None else _supporting_agreements(_votes(ensemble), _decision_from_direction(ensemble.ensemble_direction) or ""),
                moirai_uncertainty_width=None if ensemble is None else _moirai_uncertainty_width(_votes(ensemble)),
            ),
        }

    def _checks(
        self,
        *,
        score: dict[str, Any],
        regime: RegimeSnapshot,
        ensemble: EnsemblePoint | None,
        spread_pct: float | None,
        predicted_move: float,
        supporting_models: list[str],
        moirai_uncertainty_width: float | None,
    ) -> dict[str, Any]:
        return {
            "min_model_agreement": self.thresholds.min_model_agreement,
            "max_forecast_dispersion": self.thresholds.max_forecast_dispersion,
            "min_probability_win": self.thresholds.min_probability_win,
            "min_predicted_move_spread_multiple": self.thresholds.min_predicted_move_spread_multiple,
            "max_spread_pct": self.thresholds.max_spread_pct,
            "model_agreement": _float(score.get("model_agreement"), None if ensemble is None else ensemble.agreement_score),
            "forecast_dispersion": None if ensemble is None else ensemble.dispersion_score,
            "probability_win": _float(score.get("probability_win")),
            "predicted_move": predicted_move,
            "spread_pct": spread_pct,
            "risk_state": regime.risk_state,
            "supporting_model_agreements": supporting_models,
            "moirai_uncertainty_width": moirai_uncertainty_width,
        }


def _decision_from_direction(value: Any) -> str | None:
    return _ENSEMBLE_TO_DECISION.get(str(value or "").strip().upper())


def _decision_from_scorer(value: Any) -> str | None:
    return _SCORER_TO_DECISION.get(str(value or "").strip().upper())


def _votes(point: EnsemblePoint) -> dict[str, dict[str, Any]]:
    raw = point.model_votes or {}
    return {str(key).lower(): dict(value or {}) for key, value in raw.items() if isinstance(value, dict)}


def _find_vote(votes: dict[str, dict[str, Any]], aliases: tuple[str, ...]) -> dict[str, Any] | None:
    for key, vote in votes.items():
        compact = key.replace("-", "").replace("_", "")
        if any(alias.replace("-", "").replace("_", "") in compact for alias in aliases):
            return vote
    return None


def _supporting_agreements(votes: dict[str, dict[str, Any]], ensemble_decision: str) -> list[str]:
    aliases = ("chronos2", "chronos", "timesfm", "patchtst", "itransformer")
    output: list[str] = []
    for key, vote in votes.items():
        compact = key.replace("-", "").replace("_", "")
        if "kronos" in compact and "chronos" not in compact:
            continue
        if not any(alias in compact for alias in aliases):
            continue
        if _decision_from_direction(vote.get("direction")) == ensemble_decision:
            output.append(key)
    return output


def _moirai_uncertainty_width(votes: dict[str, dict[str, Any]]) -> float | None:
    vote = _find_vote(votes, ("moirai",))
    if not vote:
        return None
    raw = vote.get("raw") if isinstance(vote.get("raw"), dict) else {}
    for key in ("uncertainty_width", "moirai_uncertainty_width", "interval_width"):
        value = _float(raw.get(key))
        if value is not None:
            return abs(value)
    lower = _float(vote.get("lower_bound"), _float(raw.get("lower_bound")))
    upper = _float(vote.get("upper_bound"), _float(raw.get("upper_bound")))
    close = abs(_float(vote.get("predicted_close"), _float(raw.get("predicted_close"))) or 0.0)
    if lower is None or upper is None:
        return None
    width = abs(upper - lower)
    return width if close <= 0 else width / close


def _spread_pct(*, score: dict[str, Any], regime: RegimeSnapshot) -> float | None:
    features = score.get("features") if isinstance(score.get("features"), dict) else {}
    latest_features = features.get("latest_features") if isinstance(features.get("latest_features"), dict) else {}
    return _float(
        regime.spread,
        _float(features.get("spread"), _float(latest_features.get("spread_pct"), _float(latest_features.get("spread")))),
    )


def _higher_timeframe_strongly_opposes(score: dict[str, Any], ensemble_decision: str) -> bool:
    features = score.get("features") if isinstance(score.get("features"), dict) else {}
    latest_features = features.get("latest_features") if isinstance(features.get("latest_features"), dict) else {}
    explicit = latest_features.get("higher_timeframe_strongly_opposes")
    if explicit is not None:
        return bool(explicit)
    direction = str(latest_features.get("higher_timeframe_direction") or "").upper()
    if ensemble_decision == DECISION_BUY:
        return direction in {"DOWN", "SHORT", "SELL", "BEARISH"}
    if ensemble_decision == DECISION_SELL:
        return direction in {"UP", "LONG", "BUY", "BULLISH"}
    return False


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
