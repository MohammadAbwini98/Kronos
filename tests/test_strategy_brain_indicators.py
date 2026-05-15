from __future__ import annotations

import math

import numpy as np
import pandas as pd

from gold_analyzer.strategy_brain.indicators import IndicatorBuilder, IndicatorConfig, build_indicators


def _candles(rows: int = 120) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    index = pd.Series(range(rows), dtype=float)
    close = index + 2300.0
    return pd.DataFrame(
        {
            "ts": timestamps,
            "open": close - 0.4,
            "high": close + 1.2,
            "low": close - 1.0,
            "close": close,
            "vol": index + 100.0,
            "buyers_pct": 45.0 + (index * 0.1),
            "sellers_pct": 55.0 - (index * 0.1),
            "bid": close - 0.1,
            "ask": close + 0.1,
        }
    )


def test_ema_calculation() -> None:
    frame = build_indicators(_candles(80))
    expected = _candles(80)["close"].ewm(span=20, adjust=False).mean().iloc[-1]

    assert frame["EMA_20"].iloc[-1] == expected


def test_atr_calculation() -> None:
    candles = _candles(80)
    frame = build_indicators(candles)
    prev_close = candles["close"].shift(1)
    true_range = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - prev_close).abs(),
            (candles["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    expected_atr = true_range.ewm(alpha=1.0 / 14.0, adjust=False).mean().iloc[-1]

    assert frame["true_range"].iloc[-1] == true_range.iloc[-1]
    assert frame["ATR_14"].iloc[-1] == expected_atr


def test_rsi_calculation() -> None:
    candles = _candles(80)
    frame = build_indicators(candles)
    delta = candles["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta.clip(upper=0.0)).abs()
    avg_gain = gain.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    expected = 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss.replace(0.0, 1e-12))))

    assert frame["RSI_14"].iloc[-1] == expected.iloc[-1]


def test_macd_calculation() -> None:
    candles = _candles(80)
    frame = build_indicators(candles)
    ema12 = candles["close"].ewm(span=12, adjust=False).mean()
    ema26 = candles["close"].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()

    assert frame["MACD_line"].iloc[-1] == macd_line.iloc[-1]
    assert frame["MACD_signal"].iloc[-1] == signal.iloc[-1]
    assert frame["MACD_hist"].iloc[-1] == (macd_line.iloc[-1] - signal.iloc[-1])


def test_bollinger_calculation() -> None:
    candles = _candles(80)
    frame = build_indicators(candles)
    mid = candles["close"].rolling(window=20, min_periods=20).mean()
    std = candles["close"].rolling(window=20, min_periods=20).std(ddof=0)
    upper = mid + (2.0 * std)
    lower = mid - (2.0 * std)

    assert frame["BB_mid"].iloc[-1] == mid.iloc[-1]
    assert frame["BB_upper"].iloc[-1] == upper.iloc[-1]
    assert frame["BB_lower"].iloc[-1] == lower.iloc[-1]


def test_percentile_features_are_added() -> None:
    frame = build_indicators(_candles(80))
    bb_expected = (frame["BB_width"].dropna() <= frame["BB_width"].dropna().iloc[-1]).mean() * 100.0
    donchian_expected = (
        (frame["donchian_range_20"].dropna() <= frame["donchian_range_20"].dropna().iloc[-1]).mean() * 100.0
    )

    assert frame["BB_width_percentile"].iloc[-1] == bb_expected
    assert frame["donchian_range_percentile"].iloc[-1] == donchian_expected


def test_adx_calculation() -> None:
    candles = _candles(80)
    frame = build_indicators(candles)
    up_move = candles["high"].diff()
    down_move = candles["low"].shift(1) - candles["low"]
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0))
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0))
    prev_close = candles["close"].shift(1)
    true_range = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - prev_close).abs(),
            (candles["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / 14.0, adjust=False).mean() / atr.replace(0.0, 1e-12)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / 14.0, adjust=False).mean() / atr.replace(0.0, 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, 1e-12)
    adx = dx.ewm(alpha=1.0 / 14.0, adjust=False).mean()

    assert frame["plus_di_14"].iloc[-1] == plus_di.iloc[-1]
    assert frame["minus_di_14"].iloc[-1] == minus_di.iloc[-1]
    assert frame["ADX_14"].iloc[-1] == adx.iloc[-1]


def test_donchian_channels() -> None:
    candles = _candles(40)
    frame = build_indicators(candles)
    expected_high = candles["high"].rolling(window=20, min_periods=20).max().iloc[-1]
    expected_low = candles["low"].rolling(window=20, min_periods=20).min().iloc[-1]

    assert frame["donchian_high_20"].iloc[-1] == expected_high
    assert frame["donchian_low_20"].iloc[-1] == expected_low


def test_volume_zscore_zero_when_volume_missing_or_zero() -> None:
    candles = _candles(60)
    candles.loc[10, "vol"] = 0.0
    candles.loc[11, "vol"] = np.nan

    frame = build_indicators(candles)

    assert frame.loc[10, "vol_z"] == 0.0
    assert frame.loc[11, "vol_z"] == 0.0


def test_spread_metrics_and_sentiment_imbalance() -> None:
    candles = _candles(30)
    frame = build_indicators(candles)
    last = frame.iloc[-1]

    assert last["spread"] == last["ask"] - last["bid"]
    assert last["spread_pct"] == last["spread"] / last["close"]
    assert last["spread_atr"] == last["spread"] / last["ATR_14"]
    assert last["sentiment_imbalance"] == last["buyers_pct"] - last["sellers_pct"]


def test_indicator_builder_uses_past_only_rows() -> None:
    builder = IndicatorBuilder()
    full = builder.build(_candles(120))
    prefix = builder.build(_candles(70))

    comparable = [
        "true_range",
        "ATR_14",
        "EMA_20",
        "EMA_50",
        "RSI_14",
        "MACD_hist",
        "BB_width",
        "ADX_14",
        "donchian_high_20",
        "vol_z",
        "spread_atr",
        "sentiment_imbalance",
        "last_confirmed_swing_high",
        "last_confirmed_swing_low",
        "bullish_bos",
        "bearish_bos",
    ]

    for column in comparable:
        left = full.loc[69, column]
        right = prefix.loc[69, column]
        if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
            assert bool(left) is bool(right)
        elif pd.isna(left) and pd.isna(right):
            continue
        else:
            assert left == right


def test_swing_detection_no_lookahead() -> None:
    candles = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=7, freq="5min", tz="UTC"),
            "open": [10.0, 11.0, 12.0, 11.0, 10.0, 10.5, 11.0],
            "high": [11.0, 12.0, 15.0, 12.0, 11.0, 11.5, 12.0],
            "low": [9.0, 10.0, 11.0, 10.5, 9.5, 10.0, 10.5],
            "close": [10.5, 11.5, 12.5, 11.2, 10.2, 11.0, 11.4],
            "vol": [100.0] * 7,
        }
    )

    frame = build_indicators(candles, config=IndicatorConfig(swing_len=2))

    assert bool(frame["swing_high_confirmed"].iloc[2]) is False
    assert bool(frame["swing_high_confirmed"].iloc[3]) is False
    assert bool(frame["swing_high_confirmed"].iloc[4]) is True
    assert frame["swing_high_price"].iloc[4] == 15.0


def test_bos_and_choch_detection() -> None:
    candles = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=12, freq="5min", tz="UTC"),
            "open": [10.0, 9.5, 7.0, 9.0, 10.0, 7.0, 6.5, 8.0, 9.0, 11.0, 12.0, 11.5],
            "high": [11.0, 10.0, 9.0, 10.0, 13.0, 8.0, 7.0, 9.0, 10.0, 14.0, 13.0, 12.0],
            "low": [9.0, 8.0, 6.0, 8.0, 9.0, 5.0, 6.0, 7.0, 8.0, 10.0, 11.0, 10.0],
            "close": [10.0, 9.0, 7.2, 9.4, 10.8, 5.5, 6.8, 8.5, 9.2, 13.5, 12.5, 11.0],
            "vol": [100.0] * 12,
        }
    )

    frame = build_indicators(candles, config=IndicatorConfig(swing_len=2))

    assert bool(frame["bearish_bos"].any()) is True
    assert bool(frame["bullish_bos"].any()) is True
    assert bool(frame["bullish_choch"].any()) is True


def test_liquidity_sweep_detection() -> None:
    candles = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=7, freq="5min", tz="UTC"),
            "open": [10.0, 9.5, 7.0, 9.0, 10.0, 6.4, 7.0],
            "high": [11.0, 10.0, 9.0, 10.0, 11.0, 7.0, 8.0],
            "low": [9.0, 8.0, 6.0, 8.0, 9.0, 5.0, 6.0],
            "close": [10.0, 9.0, 7.2, 9.4, 10.2, 6.6, 7.5],
            "vol": [100.0] * 7,
        }
    )

    frame = build_indicators(candles, config=IndicatorConfig(swing_len=2))

    assert bool(frame["bullish_liquidity_sweep"].iloc[5]) is True


def test_build_indicators_accepts_timestamps_alias() -> None:
    candles = _candles(30).rename(columns={"ts": "timestamps"})
    frame = build_indicators(candles)

    assert "ts" in frame.columns
    assert frame["ts"].dtype == "datetime64[ns, UTC]"