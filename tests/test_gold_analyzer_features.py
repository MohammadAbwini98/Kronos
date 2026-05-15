from __future__ import annotations

import pandas as pd

from gold_analyzer.features import FeatureBuilder


def _candles(rows: int = 80) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    close = pd.Series(range(rows), dtype=float) + 2300.0
    return pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": close - 0.25,
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "volume": pd.Series(range(rows), dtype=float) + 100.0,
        }
    )


def test_feature_builder_uses_past_only_rows() -> None:
    builder = FeatureBuilder(rolling_window=10)
    full = builder.build(_candles(80))
    prefix = builder.build(_candles(40))

    comparable = [
        "return_1",
        "rolling_volatility",
        "atr_like_range",
        "volume_zscore",
        "price_z",
        "trend_strength",
        "mtf_fast_slow_spread",
    ]

    for column in comparable:
        assert full.loc[39, column] == prefix.loc[39, column]
