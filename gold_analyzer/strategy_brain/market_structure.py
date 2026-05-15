from __future__ import annotations

import numpy as np
import pandas as pd


def add_market_structure_features(
    frame: pd.DataFrame,
    *,
    swing_len: int = 2,
    epsilon: float = 1e-12,
) -> pd.DataFrame:
    out = frame.copy()
    length = max(1, int(swing_len))

    pivot_high = pd.Series(True, index=out.index)
    pivot_low = pd.Series(True, index=out.index)
    for offset in range(1, length + 1):
        pivot_high &= out["high"] > out["high"].shift(offset)
        pivot_high &= out["high"] > out["high"].shift(-offset)
        pivot_low &= out["low"] < out["low"].shift(offset)
        pivot_low &= out["low"] < out["low"].shift(-offset)

    swing_high_confirmed = pivot_high.shift(length, fill_value=False)
    swing_low_confirmed = pivot_low.shift(length, fill_value=False)

    out["swing_high_confirmed"] = swing_high_confirmed.astype(bool)
    out["swing_low_confirmed"] = swing_low_confirmed.astype(bool)
    out["swing_high_price"] = out["high"].where(pivot_high).shift(length)
    out["swing_low_price"] = out["low"].where(pivot_low).shift(length)
    out["last_confirmed_swing_high"] = out["swing_high_price"].ffill()
    out["last_confirmed_swing_low"] = out["swing_low_price"].ffill()

    out["previous_swing_high"] = out["last_confirmed_swing_high"].shift(1)
    out["previous_swing_low"] = out["last_confirmed_swing_low"].shift(1)

    bullish_break = out["previous_swing_high"].notna() & (out["close"] > out["previous_swing_high"])
    bearish_break = out["previous_swing_low"].notna() & (out["close"] < out["previous_swing_low"])
    prior_bullish_break = bullish_break.shift(1, fill_value=False)
    prior_bearish_break = bearish_break.shift(1, fill_value=False)

    out["bullish_bos"] = bullish_break & ~prior_bullish_break
    out["bearish_bos"] = bearish_break & ~prior_bearish_break

    bias_event = pd.Series(np.nan, index=out.index, dtype=float)
    bias_event.loc[out["bullish_bos"]] = 1.0
    bias_event.loc[out["bearish_bos"]] = -1.0
    prior_bias = bias_event.ffill().shift(1).fillna(0.0)

    out["bullish_choch"] = out["bullish_bos"] & (prior_bias < 0.0)
    out["bearish_choch"] = out["bearish_bos"] & (prior_bias > 0.0)
    out["structure_bias"] = bias_event.ffill().fillna(0.0).astype(int)

    wick_floor = out["range"].where(out["range"].abs() > epsilon, epsilon)
    lower_wick_ratio = out.get("lower_wick_ratio")
    upper_wick_ratio = out.get("upper_wick_ratio")
    if lower_wick_ratio is None:
        lower_wick_ratio = out["lower_wick"] / wick_floor
    if upper_wick_ratio is None:
        upper_wick_ratio = out["upper_wick"] / wick_floor

    out["bullish_liquidity_sweep"] = (
        out["previous_swing_low"].notna()
        & (out["low"] < out["previous_swing_low"])
        & (out["close"] > out["previous_swing_low"])
        & (lower_wick_ratio >= 0.45)
    )
    out["bearish_liquidity_sweep"] = (
        out["previous_swing_high"].notna()
        & (out["high"] > out["previous_swing_high"])
        & (out["close"] < out["previous_swing_high"])
        & (upper_wick_ratio >= 0.45)
    )

    return out