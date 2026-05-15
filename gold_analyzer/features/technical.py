from __future__ import annotations

import math

import pandas as pd


def add_candle_shape_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    high_low = (out["high"] - out["low"]).replace(0, float("nan"))
    out["candle_range"] = out["high"] - out["low"]
    out["candle_body"] = out["close"] - out["open"]
    out["body_pct_of_range"] = (out["candle_body"].abs() / high_low).fillna(0.0)
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["buyers_sellers_imbalance"] = ((out["close"] - out["open"]) / high_low).fillna(0.0)
    out["return_1"] = out["close"].pct_change().fillna(0.0)
    out["log_return_1"] = (out["close"] / out["close"].shift(1)).apply(
        lambda value: 0.0 if pd.isna(value) or value <= 0 else math.log(float(value))
    )
    return out


def add_trend_features(frame: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    out = frame.copy()
    returns = out["close"].pct_change().fillna(0.0)
    rolling_mean = out["close"].rolling(window=window, min_periods=2).mean()
    rolling_std = out["close"].rolling(window=window, min_periods=2).std().replace(0, float("nan"))
    out["price_z"] = ((out["close"] - rolling_mean) / rolling_std).fillna(0.0)
    out["trend_return_mean"] = returns.rolling(window=window, min_periods=2).mean().fillna(0.0)
    out["trend_strength"] = (
        out["trend_return_mean"].abs()
        / returns.rolling(window=window, min_periods=2).std().replace(0, float("nan"))
    ).fillna(0.0)
    return out
