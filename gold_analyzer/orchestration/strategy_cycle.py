from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from gold_analyzer.ai_support.service import AISupportService
from gold_analyzer.repositories.ai_support_repository import AISupportRepository
from gold_analyzer.repositories.strategy_decision_repository import StrategyDecisionRepository
from gold_analyzer.strategy_brain.brain import NullStrategyBrain, StrategyBrain
from gold_analyzer.strategy_brain.context import StrategyContext
from gold_analyzer.strategy_brain.decision import FinalDecisionEngine, StrategyDecision
from gold_analyzer.strategy_brain.risk import RiskManager


@dataclass
class StrategyCycle:
    brain: StrategyBrain = field(default_factory=NullStrategyBrain)
    ai_support_service: AISupportService = field(default_factory=AISupportService)
    risk_manager: RiskManager = field(default_factory=RiskManager)
    decision_engine: FinalDecisionEngine = field(default_factory=FinalDecisionEngine)
    decision_repository: StrategyDecisionRepository | None = None
    ai_support_repository: AISupportRepository | None = None

    def run(self, context: StrategyContext) -> StrategyDecision:
        if not context.data_quality.ok:
            decision = StrategyDecision.no_trade(
                symbol=context.symbol,
                timeframe=context.timeframe,
                computed_at=context.now_utc,
                reason=context.data_quality.reason,
                blocked_by=["DATA_QUALITY"],
                indicators=context.indicators,
                metadata=context.metadata,
            )
            self._save(decision)
            return decision

        candidate = self.brain.generate_candidate(context)
        if candidate is None:
            decision = StrategyDecision.no_trade(
                symbol=context.symbol,
                timeframe=context.timeframe,
                computed_at=context.now_utc,
                reason="NO_STRATEGY_SETUP",
                indicators=context.indicators,
                metadata=context.metadata,
            )
            self._save(decision)
            return decision

        ai_support = self.ai_support_service.evaluate(candidate, context)
        risk = self.risk_manager.evaluate(candidate, context)
        decision = self.decision_engine.decide(candidate, ai_support, risk, context)
        decision_id = self._save(decision)
        self._save_ai_support(
            decision_id=decision_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ai_support=ai_support,
        )
        return decision

    def _save(self, decision: StrategyDecision) -> int | None:
        if self.decision_repository is not None:
            return self.decision_repository.save(decision)
        return None

    def _save_ai_support(
        self,
        *,
        decision_id: int | None,
        symbol: str,
        timeframe: str,
        ai_support,
    ) -> None:
        if self.ai_support_repository is None:
            return
        self.ai_support_repository.save_result(
            decision_id=decision_id,
            symbol=symbol,
            timeframe=timeframe,
            result=ai_support,
        )


def run_strategy_cycle(
    symbol: str,
    *,
    timeframe: str = "5m",
    context: StrategyContext | None = None,
    cycle: StrategyCycle | None = None,
) -> StrategyDecision:
    active_context = context or StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        now_utc=pd.Timestamp.now(tz="UTC"),
    )
    active_cycle = cycle or StrategyCycle()
    return active_cycle.run(active_context)