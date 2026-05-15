from __future__ import annotations

import pandas as pd

from gold_analyzer.forecasting.ensemble import EnsemblePoint
from gold_analyzer.forecasting.regime_validator import RegimeSnapshot
from gold_analyzer.strategy.final_decision import FinalDecisionEngine


def _ensemble(**overrides) -> list[EnsemblePoint]:
    base_votes = {
        "kronos": {"direction": "UP", "predicted_return": 0.01, "confidence": 0.8},
        "chronos2": {"direction": "UP", "predicted_return": 0.011, "confidence": 0.75},
        "timesfm": {"direction": "UP", "predicted_return": 0.009, "confidence": 0.74},
        "moirai": {
            "direction": "UP",
            "predicted_close": 2300.0,
            "predicted_return": 0.01,
            "lower_bound": 2290.0,
            "upper_bound": 2310.0,
            "confidence": 0.7,
        },
    }
    point = EnsemblePoint(
        epic="XAUUSD",
        timeframe="MINUTE_5",
        forecast_for_ts=pd.Timestamp("2026-01-01T00:05:00Z"),
        horizon_bar=1,
        ensemble_return=0.01,
        ensemble_direction="UP",
        agreement_score=0.75,
        dispersion_score=0.02,
        confidence=0.76,
        model_votes=base_votes,
    )
    if overrides:
        point = EnsemblePoint(**{**point.__dict__, **overrides})
    return [point]


def _score(**overrides):
    return {
        "candidate_signal": "LONG",
        "probability_win": 0.68,
        "probability_loss": 0.32,
        "expected_return": 0.01,
        "model_agreement": 0.75,
        "scorer_model": "lightgbm",
        "features": {},
        **overrides,
    }


def _regime(**overrides):
    payload = {
        "epic": "XAUUSD",
        "timeframe": "MINUTE_5",
        "regime": "TRENDING_UP",
        "spread": 0.10,
        "risk_state": "NORMAL",
        **overrides,
    }
    return RegimeSnapshot(**payload)


def test_final_decision_allows_buy_when_required_evidence_passes() -> None:
    decision = FinalDecisionEngine().decide(score=_score(), regime=_regime(), ensemble=_ensemble())

    assert decision["decision"] == "BUY"
    assert "Kronos" in decision["reason"]
    assert "probability_win=0.68" in decision["reason"]


def test_final_decision_blocks_when_agreement_is_below_minimum() -> None:
    decision = FinalDecisionEngine().decide(
        score=_score(model_agreement=0.48),
        regime=_regime(),
        ensemble=_ensemble(agreement_score=0.48),
    )

    assert decision["decision"] == "NO_TRADE"
    assert decision["reason_codes"][0] == "MODEL_AGREEMENT_BELOW_MINIMUM"
    assert "0.48 below minimum 0.60" in decision["reason"]


def test_final_decision_blocks_when_predicted_move_is_smaller_than_2x_spread() -> None:
    decision = FinalDecisionEngine().decide(
        score=_score(expected_return=0.001),
        regime=_regime(spread=0.10),
        ensemble=_ensemble(ensemble_return=0.001),
    )

    assert decision["decision"] == "NO_TRADE"
    assert "PREDICTED_MOVE_BELOW_SPREAD_MULTIPLE" in decision["reason_codes"]


def test_final_decision_requires_kronos_to_agree_with_ensemble() -> None:
    votes = _ensemble()[0].model_votes
    votes = {**votes, "kronos": {**votes["kronos"], "direction": "DOWN"}}
    decision = FinalDecisionEngine().decide(score=_score(), regime=_regime(), ensemble=_ensemble(model_votes=votes))

    assert decision["decision"] == "NO_TRADE"
    assert "KRONOS_DISAGREES_WITH_ENSEMBLE" in decision["reason_codes"]


def test_final_decision_requires_two_supporting_models() -> None:
    votes = {
        "kronos": {"direction": "UP", "predicted_return": 0.01},
        "chronos2": {"direction": "UP", "predicted_return": 0.01},
        "timesfm": {"direction": "DOWN", "predicted_return": -0.01},
    }
    decision = FinalDecisionEngine().decide(score=_score(), regime=_regime(), ensemble=_ensemble(model_votes=votes))

    assert decision["decision"] == "NO_TRADE"
    assert "SUPPORTING_MODEL_AGREEMENT_BELOW_MINIMUM" in decision["reason_codes"]


def test_final_decision_blocks_extreme_garch_risk() -> None:
    decision = FinalDecisionEngine().decide(score=_score(), regime=_regime(risk_state="EXTREME"), ensemble=_ensemble())

    assert decision["decision"] == "NO_TRADE"
    assert "GARCH_RISK_EXTREME" in decision["reason_codes"]
