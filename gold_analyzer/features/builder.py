from __future__ import annotations

import math

import pandas as pd

from .leakage_guard import assert_monotonic_timestamps, assert_no_future_timestamps
from .multi_timeframe import add_multi_timeframe_features
from .sentiment import add_sentiment_features
from .technical import add_candle_shape_features, add_trend_features
from .volatility import add_volatility_features


REQUIRED_COLUMNS = ("timestamps", "open", "high", "low", "close", "volume")


class FeatureBuilder:
    def __init__(self, rolling_window: int = 20) -> None:
        self.rolling_window = max(2, int(rolling_window))

    def build(self, candles: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in REQUIRED_COLUMNS if column not in candles.columns]
        if missing:
            raise ValueError(f"Candles missing required columns: {', '.join(missing)}")
        frame = candles.copy()
        frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True)
        frame = frame.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
        assert_monotonic_timestamps(frame)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[["open", "high", "low", "close"]].isna().any().any():
            raise ValueError("Candles contain null OHLC values")

        features = add_candle_shape_features(frame)
        features = add_volatility_features(features, window=self.rolling_window)
        features = add_trend_features(features, window=self.rolling_window)
        features = add_sentiment_features(features)
        features = add_multi_timeframe_features(features)
        features = self._add_volume_and_spread(features)
        features = features.replace([math.inf, -math.inf], 0.0).fillna(0.0)
        assert_no_future_timestamps(features, frame)
        return features

    def _add_volume_and_spread(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        volume = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
        mean = volume.rolling(window=self.rolling_window, min_periods=2).mean()
        std = volume.rolling(window=self.rolling_window, min_periods=2).std().replace(0, float("nan"))
        out["volume_zscore"] = ((volume - mean) / std).fillna(0.0)
        if {"bid", "ask"}.issubset(out.columns):
            bid = pd.to_numeric(out["bid"], errors="coerce")
            ask = pd.to_numeric(out["ask"], errors="coerce")
            mid = ((bid + ask) / 2).replace(0, pd.NA)
            out["spread"] = (ask - bid).clip(lower=0).fillna(0.0)
            out["spread_pct"] = ((out["spread"] / mid) * 100.0).fillna(0.0)
        else:
            out["spread"] = 0.0
            out["spread_pct"] = 0.0
        return out


def build_features(candles: pd.DataFrame, *, rolling_window: int = 20) -> pd.DataFrame:
    return FeatureBuilder(rolling_window=rolling_window).build(candles)
