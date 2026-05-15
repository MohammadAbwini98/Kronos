from __future__ import annotations

import pandas as pd


def add_multi_timeframe_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add lightweight confirmation features without resampling future bars."""

    out = frame.copy()
    close = out["close"]
    fast = close.rolling(window=12, min_periods=2).mean()
    slow = close.rolling(window=48, min_periods=4).mean()
    out["mtf_fast_slow_spread"] = ((fast - slow) / close.replace(0, float("nan"))).fillna(0.0)
    out["mtf_confirmation"] = (out["mtf_fast_slow_spread"] > 0).astype(int) - (out["mtf_fast_slow_spread"] < 0).astype(int)
    return out
