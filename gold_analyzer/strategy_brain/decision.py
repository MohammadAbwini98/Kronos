from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from gold_analyzer.ai_support.models import AISupportResult

from .context import StrategyContext
from .models import StrategyCandidate
from .risk import RiskDecision
from .scoring import combine_weighted_scores


DECISION_BUY = "BUY"
DECISION_SELL = "SELL"
DECISION_NO_TRADE = "NO_TRADE"


def _risk_reward(entry: float | None, stop: float | None, target: float | None) -> float | None:
    if entry is None or stop is None or target is None:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    return abs(target - entry) / risk


@dataclass(frozen=True)
class StrategyDecision:
    symbol: str
    timeframe: str
    computed_at: pd.Timestamp
    signal: str
    decision_status: str
    reason: str
    strategy_type: str | None = None
    regime: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    position_size: float | None = None
    risk_reward_1: float | None = None
    risk_reward_2: float | None = None
    strategy_score: float | None = None
    ai_support_score: float | None = None
    risk_score: float | None = None
    final_score: float | None = None
    blocked_by: list[str] = field(default_factory=list)
    indicators: dict[str, Any] = field(default_factory=dict)
    ai_details: dict[str, Any] = field(default_factory=dict)
    risk_details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "computed_at", pd.to_datetime(self.computed_at, utc=True))
        object.__setattr__(self, "signal", str(self.signal).upper().strip())
        object.__setattr__(self, "decision_status", str(self.decision_status).upper().strip())

    @classmethod
    def no_trade(
        cls,
        *,
        symbol: str,
        timeframe: str,
        reason: str,
        computed_at: pd.Timestamp | None = None,
        blocked_by: list[str] | None = None,
        indicators: dict[str, Any] | None = None,
        ai_details: dict[str, Any] | None = None,
        risk_details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            computed_at=computed_at or pd.Timestamp.now(tz="UTC"),
            signal=DECISION_NO_TRADE,
            decision_status=DECISION_NO_TRADE,
            reason=reason,
            blocked_by=list(blocked_by or []),
            indicators=dict(indicators or {}),
            ai_details=dict(ai_details or {}),
            risk_details=dict(risk_details or {}),
            metadata=dict(metadata or {}),
        )


class FinalDecisionEngine:
    def decide(
        self,
        candidate: StrategyCandidate | None,
        ai_support: AISupportResult | None,
        risk: RiskDecision | None,
        context: StrategyContext,
    ) -> StrategyDecision:
        if candidate is None:
            return StrategyDecision.no_trade(
                symbol=context.symbol,
                timeframe=context.timeframe,
                computed_at=context.now_utc,
                reason="NO_STRATEGY_SETUP",
                indicators=context.indicators,
            )

        ai_result = ai_support or AISupportResult.unavailable(reason="AI_SUPPORT_NOT_RUN")
        risk_result = risk or RiskDecision.blocked("RISK_NOT_RUN")

        if ai_result.should_block:
            return StrategyDecision.no_trade(
                symbol=context.symbol,
                timeframe=context.timeframe,
                computed_at=context.now_utc,
                reason=ai_result.reason or "AI_SUPPORT_BLOCKED",
                blocked_by=["AI_SUPPORT"],
                indicators=candidate.indicators,
                ai_details={
                    "status": ai_result.status,
                    "support_value": ai_result.support_value,
                    "confidence": ai_result.confidence,
                    "evaluations": list(ai_result.evaluations),
                    "reason": ai_result.reason,
                },
            )

        if not risk_result.approved:
            return StrategyDecision.no_trade(
                symbol=context.symbol,
                timeframe=context.timeframe,
                computed_at=context.now_utc,
                reason=risk_result.reason,
                blocked_by=list(risk_result.blocked_by),
                indicators=candidate.indicators,
                ai_details={
                    "status": ai_result.status,
                    "support_value": ai_result.support_value,
                    "confidence": ai_result.confidence,
                    "evaluations": list(ai_result.evaluations),
                    "reason": ai_result.reason,
                },
                risk_details={
                    "approved": risk_result.approved,
                    "risk_score": risk_result.risk_score,
                    "blocked_by": list(risk_result.blocked_by),
                    "details": dict(risk_result.details),
                },
            )

        ai_score = ai_result.ai_support_score if ai_result.ai_support_score is not None else ai_result.support_value
        final_score = combine_weighted_scores(
            {
                "strategy": candidate.strategy_score,
                "ai": ai_score,
                "risk": risk_result.risk_score,
            }
        )
        position_size = risk_result.position_size if risk_result.position_size is not None else candidate.position_size
        return StrategyDecision(
            symbol=context.symbol,
            timeframe=context.timeframe,
            computed_at=context.now_utc,
            signal=candidate.signal,
            decision_status="APPROVED",
            reason="STRATEGY_CANDIDATE_APPROVED",
            strategy_type=candidate.strategy_type,
            regime=candidate.regime or context.market_regime.regime,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            take_profit_1=candidate.take_profit_1,
            take_profit_2=candidate.take_profit_2,
            position_size=position_size,
            risk_reward_1=_risk_reward(candidate.entry_price, candidate.stop_loss, candidate.take_profit_1),
            risk_reward_2=_risk_reward(candidate.entry_price, candidate.stop_loss, candidate.take_profit_2),
            strategy_score=candidate.strategy_score,
            ai_support_score=ai_score,
            risk_score=risk_result.risk_score,
            final_score=final_score,
            blocked_by=[],
            indicators=dict(candidate.indicators),
            ai_details={
                "status": ai_result.status,
                "support_value": ai_result.support_value,
                "confidence": ai_result.confidence,
                "evaluations": list(ai_result.evaluations),
                "reason": ai_result.reason,
            },
            risk_details={
                "approved": risk_result.approved,
                "risk_score": risk_result.risk_score,
                "position_size": risk_result.position_size,
                "details": dict(risk_result.details),
            },
            metadata=dict(candidate.metadata),
        )