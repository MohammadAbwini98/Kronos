from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .market_structure import add_market_structure_features


REQUIRED_COLUMNS = ("ts", "open", "high", "low", "close")
_ALIASES = {
    "timestamp": "ts",
    "timestamps": "ts",
    "volume": "vol",
}


@dataclass(frozen=True)
class IndicatorConfig:
    atr_period: int = 14
    atr_percentile_window: int = 500
    bb_width_percentile_window: int = 500
    donchian_percentile_window: int = 500
    ema_slope_lookback: int = 5
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    adx_period: int = 14
    donchian_period: int = 20
    volume_z_window: int = 50
    sentiment_z_window: int = 100
    swing_len: int = 2
    epsilon: float = 1e-12


class IndicatorBuilder:
    def __init__(self, config: IndicatorConfig | None = None) -> None:
        self.config = config or IndicatorConfig()

    def build(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = _normalize_candles(candles)
        frame = _add_candle_features(frame, epsilon=self.config.epsilon)
        frame = _add_return_features(frame)
        frame = _add_atr_features(frame, self.config)
        frame = _add_ema_features(frame, self.config)
        frame = _add_rsi_features(frame, self.config)
        frame = _add_macd_features(frame, self.config)
        frame = _add_bollinger_features(frame, self.config)
        frame = _add_adx_features(frame, self.config)
        frame = _add_donchian_features(frame, self.config)
        frame = _add_volume_features(frame, self.config)
        frame = _add_spread_features(frame, epsilon=self.config.epsilon)
        frame = _add_sentiment_features(frame, self.config)
        frame = add_market_structure_features(frame, swing_len=self.config.swing_len, epsilon=self.config.epsilon)
        return frame.replace([math.inf, -math.inf], np.nan)


def build_indicators(candles: pd.DataFrame, *, config: IndicatorConfig | None = None) -> pd.DataFrame:
    return IndicatorBuilder(config=config).build(candles)


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    rename_map = {
        alias: canonical
        for alias, canonical in _ALIASES.items()
        if alias in frame.columns and canonical not in frame.columns
    }
    if rename_map:
        frame = frame.rename(columns=rename_map)

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Candles missing required columns: {', '.join(missing)}")

    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    if not frame["ts"].is_monotonic_increasing:
        raise ValueError("Candle timestamps must be strictly increasing")

    numeric_columns = [
        column
        for column in (
            "open",
            "high",
            "low",
            "close",
            "vol",
            "buyers_pct",
            "sellers_pct",
            "bid",
            "ask",
            "spread",
        )
        if column in frame.columns
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if frame["close"].isna().any():
        raise ValueError("Candles contain missing close values")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("Candles contain invalid highs")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("Candles contain invalid lows")

    if "vol" not in frame.columns:
        frame["vol"] = np.nan
    if "buyers_pct" not in frame.columns:
        frame["buyers_pct"] = np.nan
    if "sellers_pct" not in frame.columns:
        frame["sellers_pct"] = np.nan
    if "spread" not in frame.columns:
        frame["spread"] = np.nan

    return frame


def _safe_denominator(series: pd.Series, epsilon: float) -> pd.Series:
    return series.where(series.abs() > epsilon, epsilon)


def _percentile_rank_last(window: pd.Series) -> float:
    clean = window.dropna()
    if clean.empty:
        return float("nan")
    last = clean.iloc[-1]
    return float((clean <= last).mean() * 100.0)


def _rolling_zscore(series: pd.Series, *, window: int) -> pd.Series:
    mean = series.rolling(window=window, min_periods=2).mean()
    std = series.rolling(window=window, min_periods=2).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def _wilder_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def _add_candle_features(frame: pd.DataFrame, *, epsilon: float) -> pd.DataFrame:
    out = frame.copy()
    candle_range = out["high"] - out["low"]
    range_floor = _safe_denominator(candle_range, epsilon)
    out["body"] = out["close"] - out["open"]
    out["body_abs"] = out["body"].abs()
    out["range"] = candle_range
    out["range_pct"] = out["range"] / _safe_denominator(out["close"], epsilon)
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["upper_wick_ratio"] = out["upper_wick"] / range_floor
    out["lower_wick_ratio"] = out["lower_wick"] / range_floor
    out["body_ratio"] = out["body_abs"] / range_floor
    out["close_position_in_range"] = (out["close"] - out["low"]) / range_floor
    out["candle_direction"] = np.where(
        out["close"] > out["open"],
        "BULLISH",
        np.where(out["close"] < out["open"], "BEARISH", "NEUTRAL"),
    )
    return out


def _add_return_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    ratio = out["close"] / out["close"].shift(1)
    out["return_1"] = ratio - 1.0
    out["log_ret"] = np.log(ratio.where(ratio > 0.0))
    return out


def _add_atr_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    prev_close = out["close"].shift(1)
    out["tr1"] = out["high"] - out["low"]
    out["tr2"] = (out["high"] - prev_close).abs()
    out["tr3"] = (out["low"] - prev_close).abs()
    out["true_range"] = pd.concat([out["tr1"], out["tr2"], out["tr3"]], axis=1).max(axis=1)
    out["ATR_14"] = _wilder_ema(out["true_range"], config.atr_period)
    out["atr_pct"] = out["ATR_14"] / _safe_denominator(out["close"], config.epsilon)
    out["atr_percentile"] = out["ATR_14"].rolling(
        window=config.atr_percentile_window,
        min_periods=1,
    ).apply(_percentile_rank_last, raw=False)
    out["atr_volatility_regime"] = np.select(
        [
            out["atr_percentile"] < 20.0,
            out["atr_percentile"] >= 95.0,
            out["atr_percentile"] >= 80.0,
        ],
        ["LOW_VOL", "EXTREME_VOL", "HIGH_VOL"],
        default="NORMAL_VOL",
    )
    return out


def _add_ema_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    for period in (9, 20, 50, 200):
        column = f"EMA_{period}"
        out[column] = out["close"].ewm(span=period, adjust=False).mean()
        out[f"ema_slope_{period}"] = (
            out[column] - out[column].shift(config.ema_slope_lookback)
        ) / _safe_denominator(config.ema_slope_lookback * out["ATR_14"], config.epsilon)

    out["ema_bullish_alignment"] = (out["EMA_20"] > out["EMA_50"]) & (out["EMA_50"] > out["EMA_200"])
    out["ema_bearish_alignment"] = (out["EMA_20"] < out["EMA_50"]) & (out["EMA_50"] < out["EMA_200"])
    out["distance_ema20_atr"] = (out["close"] - out["EMA_20"]) / _safe_denominator(out["ATR_14"], config.epsilon)
    out["distance_ema50_atr"] = (out["close"] - out["EMA_50"]) / _safe_denominator(out["ATR_14"], config.epsilon)
    out["distance_ema200_atr"] = (out["close"] - out["EMA_200"]) / _safe_denominator(out["ATR_14"], config.epsilon)
    out["price_z_atr"] = out["distance_ema50_atr"]
    return out


def _add_rsi_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    delta = out["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta.clip(upper=0.0)).abs()
    avg_gain = _wilder_ema(gain, config.rsi_period)
    avg_loss = _wilder_ema(loss, config.rsi_period)
    rs = avg_gain / _safe_denominator(avg_loss, config.epsilon)
    out["RSI_14"] = 100.0 - (100.0 / (1.0 + rs))
    out["rsi_slope"] = out["RSI_14"] - out["RSI_14"].shift(3)
    return out


def _add_macd_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    ema_fast = out["close"].ewm(span=config.macd_fast, adjust=False).mean()
    ema_slow = out["close"].ewm(span=config.macd_slow, adjust=False).mean()
    out["MACD_line"] = ema_fast - ema_slow
    out["MACD_signal"] = out["MACD_line"].ewm(span=config.macd_signal, adjust=False).mean()
    out["MACD_hist"] = out["MACD_line"] - out["MACD_signal"]
    out["MACD_hist_slope"] = out["MACD_hist"] - out["MACD_hist"].shift(1)
    return out


def _add_bollinger_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    out["BB_mid"] = out["close"].rolling(window=config.bb_period, min_periods=config.bb_period).mean()
    out["BB_std"] = out["close"].rolling(window=config.bb_period, min_periods=config.bb_period).std(ddof=0)
    out["BB_upper"] = out["BB_mid"] + (config.bb_std * out["BB_std"])
    out["BB_lower"] = out["BB_mid"] - (config.bb_std * out["BB_std"])
    bb_width = out["BB_upper"] - out["BB_lower"]
    out["BB_width"] = bb_width / _safe_denominator(out["BB_mid"], config.epsilon)
    out["BB_width_percentile"] = out["BB_width"].rolling(
        window=config.bb_width_percentile_window,
        min_periods=1,
    ).apply(_percentile_rank_last, raw=False)
    out["BB_percent_b"] = (out["close"] - out["BB_lower"]) / _safe_denominator(bb_width, config.epsilon)
    return out


def _add_adx_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    up_move = out["high"].diff()
    down_move = out["low"].shift(1) - out["low"]

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0),
        index=out.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0),
        index=out.index,
    )

    plus_di = 100.0 * _wilder_ema(plus_dm, config.adx_period) / _safe_denominator(out["ATR_14"], config.epsilon)
    minus_di = 100.0 * _wilder_ema(minus_dm, config.adx_period) / _safe_denominator(out["ATR_14"], config.epsilon)
    out["plus_di_14"] = plus_di
    out["minus_di_14"] = minus_di
    out["dx"] = 100.0 * (plus_di - minus_di).abs() / _safe_denominator(plus_di + minus_di, config.epsilon)
    out["ADX_14"] = _wilder_ema(out["dx"], config.adx_period)
    return out


def _add_donchian_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    out["donchian_high_20"] = out["high"].rolling(
        window=config.donchian_period,
        min_periods=config.donchian_period,
    ).max()
    out["donchian_low_20"] = out["low"].rolling(
        window=config.donchian_period,
        min_periods=config.donchian_period,
    ).min()
    out["donchian_mid_20"] = (out["donchian_high_20"] + out["donchian_low_20"]) / 2.0
    out["donchian_range_20"] = out["donchian_high_20"] - out["donchian_low_20"]
    out["donchian_range_percentile"] = out["donchian_range_20"].rolling(
        window=config.donchian_percentile_window,
        min_periods=1,
    ).apply(_percentile_rank_last, raw=False)
    out["bull_breakout"] = out["close"] > out["donchian_high_20"].shift(1)
    out["bear_breakout"] = out["close"] < out["donchian_low_20"].shift(1)
    return out


def _add_volume_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    volume = out["vol"].fillna(0.0).clip(lower=0.0)
    out["vol_log"] = np.log1p(volume)
    out["vol_z"] = _rolling_zscore(out["vol_log"], window=config.volume_z_window)
    out.loc[volume <= 0.0, "vol_z"] = 0.0
    return out


def _add_spread_features(frame: pd.DataFrame, *, epsilon: float) -> pd.DataFrame:
    out = frame.copy()
    spread = out["spread"]
    if {"bid", "ask"}.issubset(out.columns):
        bid_ask_spread = (out["ask"] - out["bid"]).clip(lower=0.0)
        spread = spread.fillna(bid_ask_spread)
    out["spread"] = spread.clip(lower=0.0)
    out["spread_pct"] = out["spread"] / _safe_denominator(out["close"], epsilon)
    out["spread_atr"] = out["spread"] / _safe_denominator(out["ATR_14"], epsilon)
    return out


def _add_sentiment_features(frame: pd.DataFrame, config: IndicatorConfig) -> pd.DataFrame:
    out = frame.copy()
    buyers = out["buyers_pct"]
    sellers = out["sellers_pct"]

    if buyers.notna().any() and sellers.isna().all():
        sellers = 100.0 - buyers
    if sellers.notna().any() and buyers.isna().all():
        buyers = 100.0 - sellers

    imbalance = (buyers.fillna(0.0) - sellers.fillna(0.0)).fillna(0.0)
    out["sentiment_imbalance"] = imbalance
    out["sentiment_delta"] = imbalance.diff()
    out["sentiment_z"] = _rolling_zscore(imbalance, window=config.sentiment_z_window)
    return out