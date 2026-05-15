from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .scoring import is_soft_veto


AI_SUPPORT_STATUSES = {"UNAVAILABLE", "NEUTRAL", "SUPPORTED", "BLOCKED"}


@dataclass(frozen=True)
class AISupportResult:
    candidate_signal: str | None
    support_value: float = 0.0
    confidence: float | None = None
    ai_support_score: float | None = None
    hard_veto: bool = False
    veto_reason: str | None = None
    kronos_support: float = 0.0
    chronos2_support: float = 0.0
    timesfm_support: float = 0.0
    moirai_support: float = 0.0
    patchtst_support: float = 0.0
    itransformer_support: float = 0.0
    garch_support: float = 0.0
    status: str = "UNAVAILABLE"
    reason: str | None = None
    should_block: bool = False
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    model_details: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = str(self.status).upper().strip()
        if status not in AI_SUPPORT_STATUSES:
            raise ValueError(f"Unsupported AI support status: {self.status}")
        object.__setattr__(self, "status", status)
        signal = None if self.candidate_signal is None else str(self.candidate_signal).upper().strip()
        object.__setattr__(self, "candidate_signal", signal)
        ai_score = self.ai_support_score if self.ai_support_score is not None else self.support_value
        should_block = bool(self.should_block or self.hard_veto or is_soft_veto(ai_score))
        object.__setattr__(self, "should_block", should_block)
        if self.hard_veto and self.veto_reason and not self.reason:
            object.__setattr__(self, "reason", self.veto_reason)

    @classmethod
    def unavailable(cls, *, reason: str = "AI_SUPPORT_DISABLED") -> "AISupportResult":
        return cls(
            candidate_signal=None,
            status="UNAVAILABLE",
            reason=reason,
            support_value=0.0,
            ai_support_score=0.0,
        )

    @classmethod
    def neutral(
        cls,
        *,
        candidate_signal: str,
        reason: str = "ROUND_1_PLACEHOLDER",
        support_value: float = 0.0,
        confidence: float | None = None,
        evaluations: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> "AISupportResult":
        return cls(
            candidate_signal=candidate_signal,
            status="NEUTRAL",
            reason=reason,
            support_value=support_value,
            confidence=confidence,
            ai_support_score=support_value,
            evaluations=list(evaluations or []),
            model_details=dict(details or {}),
            details=dict(details or {}),
        )