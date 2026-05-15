from __future__ import annotations

from typing import Any

import pandas as pd

from gold_analyzer.strategy_brain.models import StrategyCandidate


def build_breakout_candidate(
    *,
    brain: Any,
    frame: pd.DataFrame,
    regime: str,
    htf: dict[str, float],
) -> StrategyCandidate | None:
    return brain._build_breakout_candidate(frame, regime, htf)


__all__ = ["build_breakout_candidate"]