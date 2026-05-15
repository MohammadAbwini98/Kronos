from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STRATEGY_SIGNALS = {"BUY", "SELL"}


@dataclass(frozen=True)
class StrategyCandidate:
    signal: str
    strategy_type: str
    entry_price: float
    stop_loss: float
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    position_size: float | None = None
    regime: str | None = None
    strategy_score: float | None = None
    indicators: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        signal = str(self.signal).upper().strip()
        if signal not in STRATEGY_SIGNALS:
            raise ValueError(f"Unsupported strategy signal: {self.signal}")
        object.__setattr__(self, "signal", signal)