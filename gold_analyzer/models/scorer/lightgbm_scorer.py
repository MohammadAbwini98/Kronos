from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from .trainer import HeuristicSignalScorer, ScorerResult


class LightGBMScorer:
    scorer_model = "lightgbm"

    def __init__(self, artifact_path: str | Path | None = None, fallback: HeuristicSignalScorer | None = None) -> None:
        self.artifact_path = Path(artifact_path) if artifact_path else None
        self.fallback = fallback or HeuristicSignalScorer()

    def score(self, features: dict[str, Any]) -> ScorerResult:
        if importlib.util.find_spec("lightgbm") is None:
            return ScorerResult(
                status="SKIPPED",
                candidate_signal="HOLD",
                probability_win=None,
                probability_loss=None,
                expected_return=None,
                decision="HOLD",
                scorer_model=self.scorer_model,
                features=features,
                error_message="Optional dependency 'lightgbm' is not installed.",
            )
        if self.artifact_path is None or not self.artifact_path.exists():
            return ScorerResult(
                status="SKIPPED",
                candidate_signal="HOLD",
                probability_win=None,
                probability_loss=None,
                expected_return=None,
                decision="HOLD",
                scorer_model=self.scorer_model,
                features=features,
                error_message="LightGBM scorer artifact is not configured.",
            )
        return self.fallback.score(
            ensemble_return=features.get("ensemble_return"),
            agreement=features.get("agreement", 0.5),
            risk_score=features.get("risk_score", 0.0),
        )
