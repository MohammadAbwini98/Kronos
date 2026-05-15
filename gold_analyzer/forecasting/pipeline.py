from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from gold_analyzer.features.builder import FeatureBuilder
from gold_analyzer.forecasting.ensemble import EnsembleBuilder, EnsemblePoint
from gold_analyzer.forecasting.forecast_validator import QualityReport, validate_candles
from gold_analyzer.forecasting.normalizer import normalize_result
from gold_analyzer.forecasting.regime_validator import RegimeSnapshot, RegimeValidator
from gold_analyzer.models.scorer import HeuristicSignalScorer, ScorerResult
from gold_analyzer.models.base import ForecastModel, ForecastRequest, ForecastResult
from gold_analyzer.strategy.final_decision import FinalDecisionEngine


@dataclass(frozen=True)
class PipelineResult:
    quality: QualityReport
    model_results: list[ForecastResult] = field(default_factory=list)
    ensemble: list[EnsemblePoint] = field(default_factory=list)
    regime: RegimeSnapshot | None = None
    score: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None


class ForecastingPipeline:
    def __init__(
        self,
        *,
        data_loader: Callable[[str, str, int], pd.DataFrame],
        models: list[ForecastModel] | None = None,
        model_registry: object | None = None,
        feature_builder: FeatureBuilder | None = None,
        ensemble_builder: EnsembleBuilder | None = None,
        regime_validator: RegimeValidator | None = None,
        signal_scorer: object | None = None,
        forecast_repository: object | None = None,
        regime_repository: object | None = None,
        signal_score_repository: object | None = None,
        health_repository: object | None = None,
        decision_engine: object | None = None,
        signal_repository: object | None = None,
    ) -> None:
        self.data_loader = data_loader
        self.models = models or []
        self.model_registry = model_registry
        self.feature_builder = feature_builder or FeatureBuilder()
        self.ensemble_builder = ensemble_builder or EnsembleBuilder()
        self.regime_validator = regime_validator or RegimeValidator()
        self.signal_scorer = signal_scorer or HeuristicSignalScorer()
        self.forecast_repository = forecast_repository
        self.regime_repository = regime_repository
        self.signal_score_repository = signal_score_repository
        self.health_repository = health_repository
        self.decision_engine = decision_engine or FinalDecisionEngine()
        self.signal_repository = signal_repository

    def run_cycle(
        self,
        *,
        epic: str,
        timeframe: str,
        context_bars: int = 512,
        horizon_bars: int = 12,
    ) -> PipelineResult:
        candles = self.data_loader(epic, timeframe, context_bars)
        quality = validate_candles(candles, min_rows=min(32, int(context_bars)))
        if not quality.ok:
            self._save_blocked_cycle(reason="bad_data", details=quality.details | {"errors": quality.errors})
            return PipelineResult(quality=quality)

        features = self.feature_builder.build(candles)
        request = ForecastRequest(
            epic=epic,
            timeframe=timeframe,
            horizon_bars=horizon_bars,
            context_bars=context_bars,
            candles=candles,
            features=features,
        )
        results: list[ForecastResult] = []
        for model in self._enabled_models(timeframe=timeframe):
            started = time.perf_counter()
            try:
                result = normalize_result(model.predict(request))
            except Exception as exc:  # noqa: BLE001
                result = ForecastResult.failed(
                    model_key=model.model_key,
                    model_version=model.model_version,
                    epic=epic,
                    timeframe=timeframe,
                    error=str(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            results.append(result)
            if self.forecast_repository is not None:
                save_result = getattr(self.forecast_repository, "save_result", None)
                if callable(save_result):
                    save_result(result)
        ensemble = self.ensemble_builder.combine(results)
        if self.forecast_repository is not None and ensemble:
            save_ensemble = getattr(self.forecast_repository, "save_ensemble", None)
            if callable(save_ensemble):
                save_ensemble(ensemble)
        regime = self.regime_validator.evaluate(candles=candles, features=features, ensemble=ensemble, epic=epic, timeframe=timeframe)
        self._save_regime(regime)
        score = self._score_candidate(epic=epic, timeframe=timeframe, ensemble=ensemble, regime=regime, features=features)
        decision = self._decide(score=score, regime=regime, ensemble=ensemble)
        score["decision"] = decision.get("decision", score.get("decision", "NO_TRADE"))
        score_features = score.get("features") if isinstance(score.get("features"), dict) else {}
        score_features["final_decision"] = decision
        score["features"] = score_features
        self._save_score(score)
        self._save_signal_decision(decision)
        return PipelineResult(
            quality=quality,
            model_results=results,
            ensemble=ensemble,
            regime=regime,
            score=score,
            decision=decision,
        )

    def _enabled_models(self, *, timeframe: str) -> list[ForecastModel]:
        if self.model_registry is None:
            return list(self.models)
        enabled_models = getattr(self.model_registry, "enabled_models", None)
        if not callable(enabled_models):
            return list(self.models)
        try:
            return list(enabled_models(timeframe=timeframe))
        except TypeError:
            return list(enabled_models())

    def _save_blocked_cycle(self, *, reason: str, details: dict[str, Any]) -> None:
        if self.health_repository is None:
            return
        save = getattr(self.health_repository, "save_blocked_cycle", None)
        if callable(save):
            save(reason=reason, details=details)

    def _save_regime(self, regime: RegimeSnapshot) -> None:
        repository = self.regime_repository
        if repository is None:
            return
        save = getattr(repository, "save_regime", None) or getattr(repository, "save", None)
        if callable(save):
            save(regime.to_dict())

    def _score_candidate(
        self,
        *,
        epic: str,
        timeframe: str,
        ensemble: list[EnsemblePoint],
        regime: RegimeSnapshot,
        features: pd.DataFrame,
    ) -> dict[str, Any]:
        risk_score = _risk_score(regime.risk_state)
        first = ensemble[0] if ensemble else None
        scorer_features = {
            "ensemble_return": None if first is None else first.ensemble_return,
            "ensemble_direction": None if first is None else first.ensemble_direction,
            "agreement": 0.0 if first is None else first.agreement_score,
            "forecast_dispersion": 0.0 if first is None else first.dispersion_score,
            "risk_score": risk_score,
            "regime": regime.regime,
            "risk_state": regime.risk_state,
            "spread": regime.spread,
            "model_votes": {} if first is None else _json_safe_mapping(first.model_votes),
            "latest_features": _json_safe_mapping(features.iloc[-1].to_dict()) if not features.empty else {},
        }
        result = self._call_signal_scorer(
            ensemble=ensemble,
            regime=regime,
            features=features,
            scorer_features=scorer_features,
        )
        if isinstance(result, ScorerResult):
            score = result.to_dict()
        elif isinstance(result, dict):
            score = dict(result)
        else:
            fallback = HeuristicSignalScorer().score(
                ensemble_return=scorer_features["ensemble_return"],
                agreement=scorer_features["agreement"],
                risk_score=risk_score,
            )
            score = fallback.to_dict()
        score.update(
            {
                "epic": epic if first is None else first.epic,
                "timeframe": timeframe if first is None else first.timeframe,
                "model_agreement": score.get("model_agreement", scorer_features["agreement"]),
                "forecast_dispersion": score.get("forecast_dispersion", scorer_features["forecast_dispersion"]),
                "risk_score": score.get("risk_score", risk_score),
                "features": _json_safe_mapping(score.get("features") or scorer_features),
            }
        )
        score.setdefault("candidate_signal", "HOLD")
        score.setdefault("decision", "HOLD")
        score.setdefault("scorer_model", getattr(self.signal_scorer, "scorer_model", "unknown"))
        return score

    def _call_signal_scorer(
        self,
        *,
        ensemble: list[EnsemblePoint],
        regime: RegimeSnapshot,
        features: pd.DataFrame,
        scorer_features: dict[str, Any],
    ) -> Any:
        score = getattr(self.signal_scorer, "score", None)
        if not callable(score):
            return None
        try:
            return score(ensemble=ensemble, regime=regime, features=features)
        except TypeError:
            try:
                return score(scorer_features)
            except TypeError:
                try:
                    return score(
                        ensemble_return=scorer_features["ensemble_return"],
                        agreement=scorer_features["agreement"],
                        risk_score=scorer_features["risk_score"],
                    )
                except Exception as exc:  # noqa: BLE001
                    return ScorerResult(
                        status="FAILED",
                        candidate_signal="HOLD",
                        probability_win=None,
                        probability_loss=None,
                        expected_return=scorer_features["ensemble_return"],
                        decision="HOLD",
                        scorer_model=getattr(self.signal_scorer, "scorer_model", "unknown"),
                        features=scorer_features,
                        error_message=str(exc),
                    )
        except Exception as exc:  # noqa: BLE001
            return ScorerResult(
                status="FAILED",
                candidate_signal="HOLD",
                probability_win=None,
                probability_loss=None,
                expected_return=scorer_features["ensemble_return"],
                decision="HOLD",
                scorer_model=getattr(self.signal_scorer, "scorer_model", "unknown"),
                features=scorer_features,
                error_message=str(exc),
            )

    def _save_score(self, score: dict[str, Any]) -> None:
        if self.signal_score_repository is None:
            return
        save = getattr(self.signal_score_repository, "save_score", None) or getattr(self.signal_score_repository, "save", None)
        if callable(save):
            save(score)

    def _decide(self, *, score: dict[str, Any], regime: RegimeSnapshot, ensemble: list[EnsemblePoint]) -> dict[str, Any]:
        if self.decision_engine is None:
            return {
                "decision": score.get("decision", "NO_TRADE"),
                "candidate_signal": score.get("candidate_signal", "HOLD"),
                "risk_state": regime.risk_state,
                "regime": regime.regime,
            }
        decide = getattr(self.decision_engine, "decide", None)
        if callable(decide):
            try:
                return dict(decide(score=score, regime=regime, ensemble=ensemble))
            except TypeError:
                return dict(decide(score=score, regime=regime))
        return {}

    def _save_signal_decision(self, decision: dict[str, Any]) -> None:
        if self.signal_repository is None:
            return
        save = getattr(self.signal_repository, "save", None)
        if callable(save):
            save(decision)


def _risk_score(risk_state: str) -> float:
    return {
        "LOW": 0.1,
        "NORMAL": 0.25,
        "HIGH": 0.65,
        "EXTREME": 1.0,
    }.get(str(risk_state or "UNKNOWN").upper(), 0.5)


def _json_safe_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_mapping(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_mapping(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            pass
    if pd.isna(value):
        return None
    return value
