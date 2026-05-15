from __future__ import annotations

import numpy as np
import pandas as pd

from gold_analyzer.strategy_brain.regime import (
    MarketRegimeClassifier,
    REGIME_BREAKOUT_DOWN,
    REGIME_BREAKOUT_UP,
    REGIME_HIGH_VOLATILITY,
    REGIME_LOW_LIQUIDITY,
    REGIME_NO_TRADE,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
)


def _indicator_frame(freq: str, rows: int = 6, **overrides: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=rows, freq=freq, tz="UTC"),
            "close": np.full(rows, 100.0),
            "EMA_20": np.full(rows, 100.0),
            "EMA_50": np.full(rows, 100.0),
            "EMA_200": np.full(rows, 100.0),
            "ema_slope_20": np.zeros(rows),
            "plus_di_14": np.full(rows, 10.0),
            "minus_di_14": np.full(rows, 10.0),
            "ADX_14": np.full(rows, 10.0),
            "ATR_14": np.full(rows, 1.0),
            "atr_percentile": np.full(rows, 50.0),
            "BB_width": np.full(rows, 0.02),
            "BB_width_percentile": np.full(rows, 50.0),
            "donchian_range_20": np.full(rows, 2.0),
            "donchian_range_percentile": np.full(rows, 50.0),
            "body_ratio": np.full(rows, 0.30),
            "close_position_in_range": np.full(rows, 0.50),
            "bull_breakout": np.zeros(rows, dtype=bool),
            "bear_breakout": np.zeros(rows, dtype=bool),
            "vol_z": np.zeros(rows),
            "spread_atr": np.full(rows, 0.05),
            "spread": np.full(rows, 0.05),
            "range": np.full(rows, 1.0),
            "distance_ema50_atr": np.zeros(rows),
        }
    )

    for column, value in overrides.items():
        frame[column] = value

    return frame


def _bullish_frame(freq: str) -> pd.DataFrame:
    return _indicator_frame(
        freq,
        close=np.full(6, 105.0),
        EMA_20=np.full(6, 104.0),
        EMA_50=np.full(6, 103.0),
        EMA_200=np.full(6, 100.0),
        ema_slope_20=np.full(6, 0.8),
        plus_di_14=np.full(6, 28.0),
        minus_di_14=np.full(6, 11.0),
    )


def _bearish_frame(freq: str) -> pd.DataFrame:
    return _indicator_frame(
        freq,
        close=np.full(6, 95.0),
        EMA_20=np.full(6, 96.0),
        EMA_50=np.full(6, 97.0),
        EMA_200=np.full(6, 100.0),
        ema_slope_20=np.full(6, -0.8),
        plus_di_14=np.full(6, 11.0),
        minus_di_14=np.full(6, 28.0),
    )


def _neutral_frame(freq: str) -> pd.DataFrame:
    return _indicator_frame(freq)


def test_regime_classifier_classifies_trend_up() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            close=np.full(6, 105.0),
            EMA_20=np.full(6, 104.0),
            EMA_50=np.full(6, 103.0),
            EMA_200=np.full(6, 100.0),
            ema_slope_20=np.full(6, 0.6),
            plus_di_14=np.full(6, 25.0),
            minus_di_14=np.full(6, 10.0),
            ADX_14=np.full(6, 24.0),
            atr_percentile=np.full(6, 50.0),
        ),
        "15m": _bullish_frame("15min"),
        "30m": _bullish_frame("30min"),
        "1h": _bullish_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_TREND_UP
    assert state.details["htf_bias_label"] == "BULLISH"


def test_regime_classifier_classifies_trend_down() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            close=np.full(6, 95.0),
            EMA_20=np.full(6, 96.0),
            EMA_50=np.full(6, 97.0),
            EMA_200=np.full(6, 100.0),
            ema_slope_20=np.full(6, -0.6),
            plus_di_14=np.full(6, 10.0),
            minus_di_14=np.full(6, 25.0),
            ADX_14=np.full(6, 24.0),
            atr_percentile=np.full(6, 50.0),
        ),
        "15m": _bearish_frame("15min"),
        "30m": _bearish_frame("30min"),
        "1h": _bearish_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_TREND_DOWN
    assert state.details["htf_bias_label"] == "BEARISH"


def test_regime_classifier_classifies_range() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            ADX_14=np.full(6, 12.0),
            atr_percentile=np.full(6, 40.0),
            BB_width_percentile=np.full(6, 35.0),
            distance_ema50_atr=np.full(6, 0.15),
        ),
        "15m": _neutral_frame("15min"),
        "30m": _neutral_frame("30min"),
        "1h": _neutral_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_RANGE
    assert state.details["htf_bias_label"] == "NEUTRAL"


def test_regime_classifier_classifies_breakout_up_immediately() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            ADX_14=np.array([10.0, 10.0, 11.0, 12.0, 13.0, 20.0]),
            ATR_14=np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.4]),
            BB_width_percentile=np.array([50.0, 50.0, 50.0, 50.0, 50.0, 10.0]),
            donchian_range_percentile=np.array([50.0, 50.0, 50.0, 50.0, 50.0, 10.0]),
            bull_breakout=np.array([False, False, False, False, False, True]),
            body_ratio=np.array([0.30, 0.30, 0.30, 0.30, 0.30, 0.70]),
            close_position_in_range=np.array([0.50, 0.50, 0.50, 0.50, 0.50, 0.90]),
        ),
        "15m": _neutral_frame("15min"),
        "30m": _neutral_frame("30min"),
        "1h": _neutral_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_BREAKOUT_UP
    assert state.confidence >= 0.85


def test_regime_classifier_classifies_breakout_down_immediately() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            ADX_14=np.array([10.0, 10.0, 11.0, 12.0, 13.0, 20.0]),
            ATR_14=np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.4]),
            BB_width_percentile=np.array([50.0, 50.0, 50.0, 50.0, 50.0, 10.0]),
            donchian_range_percentile=np.array([50.0, 50.0, 50.0, 50.0, 50.0, 10.0]),
            bear_breakout=np.array([False, False, False, False, False, True]),
            body_ratio=np.array([0.30, 0.30, 0.30, 0.30, 0.30, 0.70]),
            close_position_in_range=np.array([0.50, 0.50, 0.50, 0.50, 0.50, 0.10]),
        ),
        "15m": _neutral_frame("15min"),
        "30m": _neutral_frame("30min"),
        "1h": _neutral_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_BREAKOUT_DOWN
    assert state.confidence >= 0.85


def test_regime_classifier_classifies_high_volatility() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            atr_percentile=np.array([50.0, 50.0, 50.0, 97.0, 97.0, 97.0]),
            range=np.array([1.0, 1.0, 1.0, 3.0, 3.0, 3.0]),
            ATR_14=np.ones(6),
        ),
        "15m": _neutral_frame("15min"),
        "30m": _neutral_frame("30min"),
        "1h": _neutral_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_HIGH_VOLATILITY


def test_regime_classifier_classifies_low_liquidity() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            vol_z=np.array([0.0, 0.0, 0.0, -2.0, -2.0, -2.0]),
        ),
        "15m": _neutral_frame("15min"),
        "30m": _neutral_frame("30min"),
        "1h": _neutral_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_LOW_LIQUIDITY


def test_regime_classifier_returns_no_trade_without_persistence() -> None:
    classifier = MarketRegimeClassifier()
    frames = {
        "5m": _indicator_frame(
            "5min",
            close=np.array([100.0, 100.0, 100.0, 100.0, 100.0, 105.0]),
            EMA_20=np.array([100.0, 100.0, 100.0, 100.0, 100.0, 104.0]),
            EMA_50=np.array([100.0, 100.0, 100.0, 100.0, 100.0, 103.0]),
            EMA_200=np.array([100.0, 100.0, 100.0, 100.0, 100.0, 100.0]),
            ema_slope_20=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.8]),
            plus_di_14=np.array([10.0, 10.0, 10.0, 10.0, 10.0, 25.0]),
            minus_di_14=np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0]),
            ADX_14=np.array([10.0, 10.0, 10.0, 10.0, 10.0, 24.0]),
        ),
        "15m": _bullish_frame("15min"),
        "30m": _bullish_frame("30min"),
        "1h": _bullish_frame("1h"),
    }

    state = classifier.classify(frames)

    assert state.regime == REGIME_NO_TRADE
    assert state.details["candidate_regime"] == REGIME_TREND_UP