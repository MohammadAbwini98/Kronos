from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import pandas as pd

from gold_analyzer.ai_support.scoring import clamp_support_value, is_soft_veto
from gold_analyzer.ai_support.adapters import score_garch_support, score_kronos_support
from gold_analyzer.strategy_brain.indicators import IndicatorBuilder, IndicatorConfig
from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.models import StrategyCandidate

from .models import AISupportResult


_MODEL_KEYS = ("kronos", "chronos2", "timesfm", "moirai", "patchtst", "itransformer", "garch")
_MODEL_WEIGHTS = {
    "kronos": 35.0,
    "chronos2": 15.0,
    "timesfm": 15.0,
    "local_models": 15.0,
    "moirai": 10.0,
    "garch": 10.0,
}
_MODEL_ALIASES = {
    "kronos": "kronos",
    "chronos2": "chronos2",
    "chronos-2": "chronos2",
    "chronos_2": "chronos2",
    "timesfm": "timesfm",
    "moirai": "moirai",
    "patchtst": "patchtst",
    "itransformer": "itransformer",
    "i-transformer": "itransformer",
    "i_transformer": "itransformer",
    "garch": "garch",
}
_RAW_PRICE_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class AISupportConfig:
    soft_veto_threshold: float = -60.0
    uncertainty_strong_support_atr: float = 1.5
    uncertainty_soft_support_atr: float = 2.5
    uncertainty_warning_atr: float = 3.0
    garch_hard_block_state: str = "EXTREME"


class AISupportService:
    """Model-support layer that can confirm, reduce confidence, or veto a strategy candidate."""

    def __init__(
        self,
        config: AISupportConfig | None = None,
        *,
        indicator_config: IndicatorConfig | None = None,
    ) -> None:
        self.config = config or AISupportConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        self.indicator_builder = IndicatorBuilder(config=self.indicator_config)

    def evaluate(self, candidate: StrategyCandidate | None, context: StrategyContext) -> AISupportResult:
        if candidate is None:
            return AISupportResult.unavailable(reason="NO_STRATEGY_CANDIDATE")

        market_row = self._current_row(context)
        close = self._coerce_float(
            self._first_not_none(
                self._value_from_row(market_row, "close"),
                candidate.entry_price,
            )
        )
        if close is None or close <= 0.0:
            return AISupportResult.neutral(
                candidate_signal=candidate.signal,
                reason="AI_SUPPORT_MISSING_PRICE_CONTEXT",
            )

        atr = self._coerce_float(
            self._first_not_none(
                self._value_from_row(market_row, "ATR_14"),
                candidate.indicators.get("ATR_14"),
                context.indicators.get("ATR_14"),
                abs(float(candidate.entry_price) - float(candidate.stop_loss)),
            )
        )
        spread = self._coerce_float(
            self._first_not_none(
                self._value_from_row(market_row, "spread"),
                candidate.indicators.get("spread"),
                context.metadata.get("spread"),
            )
        )
        required_move = self._required_move(close=close, spread=spread or 0.0, atr=atr or 0.0)
        model_payloads = self._model_payloads(context.metadata)

        evaluations: list[dict[str, Any]] = []
        model_details: dict[str, Any] = {}
        supports: dict[str, float] = {key: 0.0 for key in _MODEL_KEYS}
        hard_veto = False
        veto_reason: str | None = None
        confidences: list[float] = []

        for model_key in _MODEL_KEYS:
            payload = model_payloads.get(model_key)
            evaluation, support, detail = self._evaluate_model(
                model_key=model_key,
                payload=payload,
                candidate=candidate,
                required_move=required_move,
                atr=atr or 0.0,
            )
            evaluations.append(evaluation)
            model_details[model_key] = detail
            supports[model_key] = support
            confidence = self._coerce_float(evaluation.get("confidence"))
            if confidence is not None:
                confidences.append(confidence)
            if model_key == "garch" and detail.get("risk_state") == self.config.garch_hard_block_state:
                hard_veto = True
                veto_reason = "GARCH_RISK_EXTREME"

        local_model_support = (supports["patchtst"] + supports["itransformer"]) / 2.0
        ai_support_score = clamp_support_value(
            (
                (_MODEL_WEIGHTS["kronos"] * supports["kronos"])
                + (_MODEL_WEIGHTS["chronos2"] * supports["chronos2"])
                + (_MODEL_WEIGHTS["timesfm"] * supports["timesfm"])
                + (_MODEL_WEIGHTS["local_models"] * local_model_support)
                + (_MODEL_WEIGHTS["moirai"] * supports["moirai"])
                + (_MODEL_WEIGHTS["garch"] * supports["garch"])
            )
        )
        soft_veto = is_soft_veto(ai_support_score, threshold=self.config.soft_veto_threshold)
        if hard_veto:
            status = "BLOCKED"
            reason = veto_reason or "AI_HARD_VETO"
        elif soft_veto:
            status = "BLOCKED"
            reason = "AI_SOFT_VETO"
        elif ai_support_score > 0.0:
            status = "SUPPORTED"
            reason = "AI_MODEL_CONFIRMATION"
        elif ai_support_score < 0.0:
            status = "NEUTRAL"
            reason = "AI_CONFIDENCE_REDUCED"
        else:
            status = "NEUTRAL"
            reason = "AI_NEUTRAL"

        confidence = (sum(confidences) / len(confidences)) if confidences else min(1.0, abs(ai_support_score) / 100.0)
        details = {
            "required_move": required_move,
            "close": close,
            "ATR_14": atr,
            "spread": spread or 0.0,
            "local_model_support": local_model_support,
            "soft_veto_threshold": self.config.soft_veto_threshold,
            "soft_veto": soft_veto,
        }
        return AISupportResult(
            candidate_signal=candidate.signal,
            support_value=ai_support_score,
            confidence=confidence,
            ai_support_score=ai_support_score,
            hard_veto=hard_veto,
            veto_reason=veto_reason,
            kronos_support=supports["kronos"],
            chronos2_support=supports["chronos2"],
            timesfm_support=supports["timesfm"],
            moirai_support=supports["moirai"],
            patchtst_support=supports["patchtst"],
            itransformer_support=supports["itransformer"],
            garch_support=supports["garch"],
            status=status,
            reason=reason,
            should_block=hard_veto or soft_veto,
            evaluations=evaluations,
            model_details=model_details,
            details=details,
        )

    def _evaluate_model(
        self,
        *,
        model_key: str,
        payload: dict[str, Any] | None,
        candidate: StrategyCandidate,
        required_move: float,
        atr: float,
    ) -> tuple[dict[str, Any], float, dict[str, Any]]:
        if not isinstance(payload, dict):
            detail = {"status": "SKIPPED", "support": 0.0}
            evaluation = self._evaluation_entry(
                model_key=model_key,
                model_status="SKIPPED",
                candidate=candidate,
                support_value=0.0,
                raw_json=detail,
                error_message=None,
            )
            return evaluation, 0.0, detail

        model_status = str(payload.get("status") or "AVAILABLE").upper().strip()
        if model_status in {"FAILED", "SKIPPED"}:
            detail = {
                "status": model_status,
                "support": 0.0,
                "error_message": payload.get("error_message"),
            }
            evaluation = self._evaluation_entry(
                model_key=model_key,
                model_status=model_status,
                candidate=candidate,
                predicted_return=self._coerce_float(payload.get("predicted_return")),
                predicted_direction=self._normalize_direction(payload.get("predicted_direction")),
                support_value=0.0,
                confidence=self._coerce_float(payload.get("confidence")),
                latency_ms=self._coerce_int(payload.get("latency_ms")),
                raw_json=dict(payload),
                error_message=payload.get("error_message"),
            )
            return evaluation, 0.0, detail

        predicted_return = self._predicted_return(payload)
        predicted_direction = self._normalize_direction(
            self._first_not_none(payload.get("predicted_direction"), payload.get("direction"), payload.get("signal"))
        )
        support = 0.0
        detail: dict[str, Any] = {
            "status": model_status,
            "predicted_return": predicted_return,
            "predicted_direction": predicted_direction,
        }
        if model_key == "kronos":
            support = self._kronos_support(candidate.signal, predicted_return, required_move)
        elif model_key in {"chronos2", "timesfm", "patchtst", "itransformer"}:
            support = self._direction_support(candidate.signal, predicted_return, required_move)
        elif model_key == "moirai":
            lower_bound = self._coerce_float(payload.get("lower_bound"))
            upper_bound = self._coerce_float(payload.get("upper_bound"))
            uncertainty_width = None
            uncertainty_atr = None
            if lower_bound is not None and upper_bound is not None:
                uncertainty_width = upper_bound - lower_bound
                if atr > 0.0:
                    uncertainty_atr = uncertainty_width / atr
            support = self._moirai_support(
                candidate.signal,
                predicted_return,
                required_move,
                uncertainty_atr,
            )
            detail.update(
                {
                    "lower_bound": lower_bound,
                    "upper_bound": upper_bound,
                    "uncertainty_width": uncertainty_width,
                    "uncertainty_atr": uncertainty_atr,
                }
            )
        elif model_key == "garch":
            risk_state = str(payload.get("risk_state") or payload.get("state") or "").upper().strip()
            support = self._garch_support(risk_state)
            detail["risk_state"] = risk_state or None

        detail["support"] = support
        evaluation = self._evaluation_entry(
            model_key=model_key,
            model_status=model_status,
            candidate=candidate,
            predicted_return=predicted_return,
            predicted_direction=predicted_direction,
            support_value=support,
            confidence=self._coerce_float(payload.get("confidence")),
            latency_ms=self._coerce_int(payload.get("latency_ms")),
            raw_json={**dict(payload), **detail},
            error_message=payload.get("error_message"),
        )
        return evaluation, support, detail

    def _evaluation_entry(
        self,
        *,
        model_key: str,
        model_status: str,
        candidate: StrategyCandidate,
        predicted_return: float | None = None,
        predicted_direction: str | None = None,
        support_value: float = 0.0,
        confidence: float | None = None,
        latency_ms: int | None = None,
        raw_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        return {
            "model_key": model_key,
            "model_status": model_status,
            "candidate_signal": candidate.signal,
            "predicted_return": predicted_return,
            "predicted_direction": predicted_direction,
            "support_value": support_value,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "raw_json": dict(raw_json or {}),
            "error_message": error_message,
        }

    def _current_row(self, context: StrategyContext) -> dict[str, Any] | None:
        frame = context.candles
        if frame is None or frame.empty:
            return None

        prepared = frame.copy()
        if "ts" not in prepared.columns and "timestamps" in prepared.columns:
            prepared = prepared.rename(columns={"timestamps": "ts"})
        if "ts" in prepared.columns:
            prepared["ts"] = pd.to_datetime(prepared["ts"], utc=True)
            prepared = prepared.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)

        if "ATR_14" not in prepared.columns:
            has_timestamps = ("ts" in prepared.columns) or ("timestamps" in prepared.columns)
            if _RAW_PRICE_COLUMNS.issubset(prepared.columns) and has_timestamps:
                prepared = self.indicator_builder.build(prepared)

        return prepared.iloc[-1].to_dict()

    def _model_payloads(self, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = self._first_not_none(
            metadata.get("ai_support_models"),
            metadata.get("model_outputs"),
            metadata.get("ai_models"),
        )
        if raw is None:
            return {}
        if isinstance(raw, list):
            outputs: dict[str, dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                key = self._normalize_model_key(item.get("model_key") or item.get("name"))
                if key is not None:
                    outputs[key] = item
            return outputs
        if isinstance(raw, dict):
            outputs = {}
            for key, value in raw.items():
                normalized = self._normalize_model_key(key)
                if normalized is None:
                    continue
                outputs[normalized] = value if isinstance(value, dict) else {"value": value}
            return outputs
        return {}

    def _normalize_model_key(self, value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"[^a-z0-9_-]", "", str(value).strip().lower())
        return _MODEL_ALIASES.get(text, text if text in _MODEL_KEYS else None)

    def _required_move(self, *, close: float, spread: float, atr: float) -> float:
        if close <= 0.0:
            return 0.0
        spread_move = max(0.0, (spread * 2.0) / close)
        atr_move = max(0.0, (0.25 * atr) / close)
        return max(spread_move, atr_move)

    def _direction_support(self, candidate_signal: str, predicted_return: float | None, required_move: float) -> float:
        if predicted_return is None:
            return 0.0
        if candidate_signal == "BUY":
            if predicted_return >= required_move:
                return 1.0
            if predicted_return <= -required_move:
                return -1.0
            return 0.0
        if predicted_return <= -required_move:
            return 1.0
        if predicted_return >= required_move:
            return -1.0
        return 0.0

    def _kronos_support(self, candidate_signal: str, predicted_return: float | None, required_move: float) -> float:
        return score_kronos_support(candidate_signal, predicted_return, required_move)

    def _moirai_support(
        self,
        candidate_signal: str,
        predicted_return: float | None,
        required_move: float,
        uncertainty_atr: float | None,
    ) -> float:
        if predicted_return is None or uncertainty_atr is None:
            return 0.0
        agreement = (candidate_signal == "BUY" and predicted_return > 0.0) or (
            candidate_signal == "SELL" and predicted_return < 0.0
        )
        strong_direction = self._direction_support(candidate_signal, predicted_return, required_move)
        disagreement = strong_direction < 0.0 or (
            (candidate_signal == "BUY" and predicted_return < 0.0)
            or (candidate_signal == "SELL" and predicted_return > 0.0)
        )
        if disagreement and uncertainty_atr <= self.config.uncertainty_strong_support_atr:
            return -1.0
        if uncertainty_atr > self.config.uncertainty_warning_atr:
            return -0.5
        if strong_direction > 0.0 and uncertainty_atr <= self.config.uncertainty_strong_support_atr:
            return 1.0
        if agreement and uncertainty_atr <= self.config.uncertainty_soft_support_atr:
            return 0.5
        return 0.0

    def _garch_support(self, risk_state: str) -> float:
        return score_garch_support(risk_state)

    def _predicted_return(self, payload: dict[str, Any]) -> float | None:
        direct = self._coerce_float(
            self._first_not_none(
                payload.get("predicted_return"),
                payload.get("forecast_return"),
                payload.get("return"),
            )
        )
        if direct is not None:
            return direct
        lower_bound = self._coerce_float(payload.get("lower_bound"))
        upper_bound = self._coerce_float(payload.get("upper_bound"))
        if lower_bound is not None and upper_bound is not None:
            return (lower_bound + upper_bound) / 2.0
        return None

    def _normalize_direction(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).upper().strip()
        if text in {"BUY", "SELL", "NEUTRAL"}:
            return text
        return None

    def _first_not_none(self, *values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    def _value_from_row(self, row: dict[str, Any] | None, key: str) -> Any:
        if row is None:
            return None
        return row.get(key)

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            if value != value:
                return None
        except Exception:
            pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None