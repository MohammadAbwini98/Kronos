from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _series(values: pd.Series | list[float] | np.ndarray | Any) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce")


def sma(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")
    values = _series(series)
    return values.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")
    values = _series(series)
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")
    close = _series(series)
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    return out.clip(lower=0.0, upper=100.0)


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if min(fast, slow, signal) <= 0:
        raise ValueError("fast, slow, and signal must be positive")
    values = _series(close)
    macd_line = ema(values, fast) - ema(values, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")
    high_values = _series(high)
    low_values = _series(low)
    close_values = _series(close)
    prev_close = close_values.shift(1)

    tr = pd.concat(
        [
            (high_values - low_values).abs(),
            (high_values - prev_close).abs(),
            (low_values - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")

    high_values = _series(high)
    low_values = _series(low)
    close_values = _series(close)

    up_move = high_values.diff()
    down_move = -low_values.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [
            (high_values - low_values).abs(),
            (high_values - close_values.shift(1)).abs(),
            (low_values - close_values.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_smooth = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=high_values.index).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean() / atr_smooth.replace(0.0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=high_values.index).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean() / atr_smooth.replace(0.0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().clip(lower=0.0, upper=100.0)


def trend_strength_fallback(close: pd.Series, atr_pct: pd.Series, period: int = 14) -> pd.Series:
    """
    Fallback trend strength proxy when ADX is unavailable.

    The score uses normalized EMA slope divided by ATR percentage.
    The output is scaled to a 0-100 range for easier thresholding.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    close_values = _series(close)
    atr_pct_values = _series(atr_pct).replace(0.0, np.nan)
    slope = ema(close_values, period).diff(periods=period) / close_values.shift(period)
    strength = (slope.abs() * 100.0) / atr_pct_values.abs().clip(lower=1e-9)
    return strength.clip(lower=0.0, upper=100.0)


def volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    if period <= 1:
        raise ValueError("period must be greater than 1")
    values = _series(volume)
    mean = values.rolling(window=period, min_periods=period).mean()
    std = values.rolling(window=period, min_periods=period).std(ddof=0).replace(0.0, np.nan)
    return (values - mean) / std


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    high_values = _series(high)
    low_values = _series(low)
    close_values = _series(close)
    volume_values = _series(volume).fillna(0.0)
    typical_price = (high_values + low_values + close_values) / 3.0
    cumulative_volume = volume_values.cumsum().replace(0.0, np.nan)
    cumulative_turnover = (typical_price * volume_values).cumsum()
    return cumulative_turnover / cumulative_volume


def body_ratio(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    open_values = _series(open_)
    high_values = _series(high)
    low_values = _series(low)
    close_values = _series(close)
    full_range = (high_values - low_values).abs().replace(0.0, np.nan)
    body = (close_values - open_values).abs()
    return (body / full_range).fillna(0.0)


def nearest_support_resistance(df: pd.DataFrame, lookback: int = 50) -> dict[str, float | None]:
    if lookback <= 1:
        raise ValueError("lookback must be greater than 1")
    if df.empty:
        return {
            "nearest_support": None,
            "nearest_resistance": None,
            "distance_to_support_pct": None,
            "distance_to_resistance_pct": None,
        }

    required = ["high", "low", "close"]
    if any(column not in df.columns for column in required):
        raise ValueError("DataFrame must contain high, low, and close columns")

    window = df.tail(lookback).copy()
    close_values = pd.to_numeric(window["close"], errors="coerce")
    current_close = close_values.iloc[-1]
    if pd.isna(current_close) or float(current_close) == 0.0:
        return {
            "nearest_support": None,
            "nearest_resistance": None,
            "distance_to_support_pct": None,
            "distance_to_resistance_pct": None,
        }

    lows = pd.to_numeric(window["low"], errors="coerce").iloc[:-1].dropna()
    highs = pd.to_numeric(window["high"], errors="coerce").iloc[:-1].dropna()

    nearest_support = None
    nearest_resistance = None

    if not lows.empty:
        support_candidates = lows[lows <= current_close]
        nearest_support = float(support_candidates.max() if not support_candidates.empty else lows.max())

    if not highs.empty:
        resistance_candidates = highs[highs >= current_close]
        nearest_resistance = float(resistance_candidates.min() if not resistance_candidates.empty else highs.min())

    dist_support = None
    dist_resistance = None
    if nearest_support is not None:
        dist_support = ((float(current_close) - nearest_support) / float(current_close)) * 100.0
    if nearest_resistance is not None:
        dist_resistance = ((nearest_resistance - float(current_close)) / float(current_close)) * 100.0

    return {
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "distance_to_support_pct": dist_support,
        "distance_to_resistance_pct": dist_resistance,
    }
