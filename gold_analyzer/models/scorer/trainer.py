from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .calibration import calibrate_probability


@dataclass(frozen=True)
class ScorerResult:
    status: str
    candidate_signal: str
    probability_win: float | None
    probability_loss: float | None
    expected_return: float | None
    decision: str
    scorer_model: str
    features: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_signal": self.candidate_signal,
            "probability_win": self.probability_win,
            "probability_loss": self.probability_loss,
            "expected_return": self.expected_return,
            "decision": self.decision,
            "scorer_model": self.scorer_model,
            "features": dict(self.features or {}),
            "error_message": self.error_message,
        }


class HeuristicSignalScorer:
    """Fallback scorer used until LightGBM/CatBoost artifacts are enabled."""

    scorer_model = "logistic_regression_fallback"

    def __init__(self, probability_threshold: float = 0.62) -> None:
        self.probability_threshold = float(probability_threshold)

    def score(self, *, ensemble_return: float | None, agreement: float, risk_score: float = 0.0) -> ScorerResult:
        if ensemble_return is None:
            return ScorerResult(
                status="SKIPPED",
                candidate_signal="HOLD",
                probability_win=None,
                probability_loss=None,
                expected_return=None,
                decision="HOLD",
                scorer_model=self.scorer_model,
                error_message="No ensemble return available.",
            )
        edge = min(0.25, abs(float(ensemble_return)) * 4.0)
        probability = calibrate_probability(0.5 + edge + (float(agreement) - 0.5) * 0.2 - float(risk_score) * 0.1)
        candidate = "LONG" if ensemble_return > 0 else "SHORT" if ensemble_return < 0 else "HOLD"
        decision = candidate if probability >= self.probability_threshold and candidate != "HOLD" else "HOLD"
        return ScorerResult(
            status="OK",
            candidate_signal=candidate,
            probability_win=probability,
            probability_loss=1.0 - probability,
            expected_return=float(ensemble_return),
            decision=decision,
            scorer_model=self.scorer_model,
            features={"agreement": float(agreement), "risk_score": float(risk_score)},
        )
