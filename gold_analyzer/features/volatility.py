from __future__ import annotations

import pandas as pd


def add_volatility_features(frame: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    out = frame.copy()
    returns = out["close"].pct_change().fillna(0.0)
    true_range = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - out["close"].shift(1)).abs(),
            (out["low"] - out["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["rolling_volatility"] = returns.rolling(window=window, min_periods=2).std().fillna(0.0)
    out["atr_like_range"] = true_range.rolling(window=window, min_periods=1).mean().fillna(0.0)
    return out
