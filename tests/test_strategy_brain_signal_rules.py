from __future__ import annotations

import numpy as np
import pandas as pd

from gold_analyzer.strategy_brain.brain import StrategyBrain
from gold_analyzer.strategy_brain.context import MarketRegimeState, StrategyContext
from gold_analyzer.strategy_brain.regime import REGIME_BREAKOUT_UP, REGIME_RANGE, REGIME_TREND_UP


def _frame(rows: int = 12, **overrides: object) -> pd.DataFrame:
    close = np.full(rows, 100.0)
    frame = pd.DataFrame(
        {
            "ts": pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC"),
            "open": close,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "EMA_20": np.full(rows, 100.0),
            "EMA_50": np.full(rows, 100.0),
            "EMA_200": np.full(rows, 100.0),
            "ema_slope_20": np.zeros(rows),
            "plus_di_14": np.full(rows, 10.0),
            "minus_di_14": np.full(rows, 10.0),
            "ADX_14": np.full(rows, 12.0),
            "ATR_14": np.full(rows, 1.0),
            "RSI_14": np.full(rows, 50.0),
            "rsi_slope": np.zeros(rows),
            "MACD_hist_slope": np.zeros(rows),
            "body_ratio": np.full(rows, 0.3),
            "lower_wick_ratio": np.full(rows, 0.2),
            "upper_wick_ratio": np.full(rows, 0.2),
            "close_position_in_range": np.full(rows, 0.5),
            "candle_direction": ["NEUTRAL"] * rows,
            "price_z_atr": np.zeros(rows),
            "BB_lower": np.full(rows, 99.0),
            "BB_upper": np.full(rows, 101.0),
            "BB_mid": np.full(rows, 100.0),
            "BB_width_percentile": np.full(rows, 50.0),
            "donchian_high_20": np.full(rows, 102.0),
            "donchian_low_20": np.full(rows, 98.0),
            "donchian_range_percentile": np.full(rows, 50.0),
            "bull_breakout": np.zeros(rows, dtype=bool),
            "bear_breakout": np.zeros(rows, dtype=bool),
            "bullish_liquidity_sweep": np.zeros(rows, dtype=bool),
            "bearish_liquidity_sweep": np.zeros(rows, dtype=bool),
            "bullish_bos": np.zeros(rows, dtype=bool),
            "bearish_bos": np.zeros(rows, dtype=bool),
            "last_confirmed_swing_low": np.full(rows, 98.0),
            "last_confirmed_swing_high": np.full(rows, 102.0),
        }
    )

    for column, value in overrides.items():
        frame[column] = value
    return frame


def _context(
    frame: pd.DataFrame,
    regime: str,
    *,
    details: dict[str, float] | None = None,
) -> StrategyContext:
    return StrategyContext(
        symbol="GOLD",
        timeframe="5m",
        now_utc=frame["ts"].iloc[-1],
        candles=frame,
        market_regime=MarketRegimeState(regime=regime, confidence=0.8, details=dict(details or {})),
    )


def test_strategy_brain_generates_trend_pullback_long_candidate() -> None:
    rows = 12
    close = np.full(rows, 105.0)
    low = np.full(rows, 103.8)
    frame = _frame(
        close=close,
        open=np.full(rows, 104.2),
        high=np.full(rows, 105.6),
        low=low,
        EMA_20=np.full(rows, 104.0),
        EMA_50=np.full(rows, 103.0),
        EMA_200=np.full(rows, 100.0),
        ema_slope_20=np.full(rows, 0.6),
        plus_di_14=np.full(rows, 24.0),
        minus_di_14=np.full(rows, 10.0),
        ADX_14=np.full(rows, 24.0),
        RSI_14=np.full(rows, 50.0),
        rsi_slope=np.full(rows, 1.4),
        MACD_hist_slope=np.full(rows, 0.3),
        lower_wick_ratio=np.full(rows, 0.4),
        close_position_in_range=np.full(rows, 0.8),
        candle_direction=["BULLISH"] * rows,
        price_z_atr=np.full(rows, -0.4),
        bullish_bos=np.array([False] * (rows - 1) + [True]),
        last_confirmed_swing_low=np.full(rows, 102.0),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            REGIME_TREND_UP,
            details={"h1_score": 1.0, "m30_score": 1.0, "m15_score": 0.0, "htf_bias_raw": 0.8},
        )
    )

    assert candidate is not None
    assert candidate.signal == "BUY"
    assert candidate.strategy_type == "trend_pullback"
    assert candidate.regime == REGIME_TREND_UP
    assert candidate.stop_loss == 101.8


def test_strategy_brain_generates_trend_pullback_short_candidate() -> None:
    rows = 12
    close = np.full(rows, 95.0)
    high = np.full(rows, 96.2)
    frame = _frame(
        close=close,
        open=np.full(rows, 95.8),
        high=high,
        low=np.full(rows, 94.4),
        EMA_20=np.full(rows, 96.0),
        EMA_50=np.full(rows, 97.0),
        EMA_200=np.full(rows, 100.0),
        ema_slope_20=np.full(rows, -0.6),
        plus_di_14=np.full(rows, 9.0),
        minus_di_14=np.full(rows, 24.0),
        ADX_14=np.full(rows, 24.0),
        RSI_14=np.full(rows, 50.0),
        rsi_slope=np.full(rows, -1.4),
        MACD_hist_slope=np.full(rows, -0.3),
        upper_wick_ratio=np.full(rows, 0.4),
        close_position_in_range=np.full(rows, 0.2),
        candle_direction=["BEARISH"] * rows,
        price_z_atr=np.full(rows, 0.4),
        bearish_bos=np.array([False] * (rows - 1) + [True]),
        last_confirmed_swing_high=np.full(rows, 98.0),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            "TREND_DOWN",
            details={"h1_score": -1.0, "m30_score": -1.0, "m15_score": 0.0, "htf_bias_raw": -0.8},
        )
    )

    assert candidate is not None
    assert candidate.signal == "SELL"
    assert candidate.strategy_type == "trend_pullback"
    assert candidate.regime == "TREND_DOWN"
    assert candidate.stop_loss == 98.2


def test_strategy_brain_generates_breakout_momentum_long_candidate() -> None:
    rows = 12
    adx = np.array([12.0] * (rows - 1) + [20.0])
    atr = np.array([1.0] * (rows - 1) + [1.2])
    donchian_high = np.array([102.0] * (rows - 2) + [103.0, 106.0])
    frame = _frame(
        close=np.array([100.0] * (rows - 1) + [105.0]),
        open=np.array([100.0] * (rows - 1) + [103.5]),
        high=np.array([100.6] * (rows - 1) + [105.8]),
        low=np.array([99.4] * (rows - 1) + [103.2]),
        ADX_14=adx,
        ATR_14=atr,
        body_ratio=np.array([0.3] * (rows - 1) + [0.7]),
        close_position_in_range=np.array([0.5] * (rows - 1) + [0.9]),
        candle_direction=["NEUTRAL"] * (rows - 1) + ["BULLISH"],
        MACD_hist_slope=np.array([0.0] * (rows - 1) + [0.3]),
        lower_wick_ratio=np.array([0.2] * (rows - 1) + [0.4]),
        BB_width_percentile=np.array([50.0] * (rows - 1) + [10.0]),
        donchian_range_percentile=np.array([50.0] * (rows - 1) + [10.0]),
        donchian_high_20=donchian_high,
        bull_breakout=np.array([False] * (rows - 1) + [True]),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            REGIME_BREAKOUT_UP,
            details={"h1_score": 0.0, "m30_score": 0.0, "m15_score": 0.0, "htf_bias_raw": 0.0},
        )
    )

    assert candidate is not None
    assert candidate.signal == "BUY"
    assert candidate.strategy_type == "breakout_momentum"
    assert candidate.metadata["entry_style"] == "aggressive"
    assert candidate.stop_loss == 102.4


def test_strategy_brain_generates_breakout_momentum_short_candidate() -> None:
    rows = 12
    adx = np.array([12.0] * (rows - 1) + [20.0])
    atr = np.array([1.0] * (rows - 1) + [1.2])
    donchian_low = np.array([98.0] * (rows - 2) + [97.0, 94.0])
    frame = _frame(
        close=np.array([100.0] * (rows - 1) + [95.0]),
        open=np.array([100.0] * (rows - 1) + [96.5]),
        high=np.array([100.6] * (rows - 1) + [96.8]),
        low=np.array([99.4] * (rows - 1) + [94.2]),
        ADX_14=adx,
        ATR_14=atr,
        body_ratio=np.array([0.3] * (rows - 1) + [0.7]),
        close_position_in_range=np.array([0.5] * (rows - 1) + [0.1]),
        candle_direction=["NEUTRAL"] * (rows - 1) + ["BEARISH"],
        MACD_hist_slope=np.array([0.0] * (rows - 1) + [-0.3]),
        upper_wick_ratio=np.array([0.2] * (rows - 1) + [0.4]),
        BB_width_percentile=np.array([50.0] * (rows - 1) + [10.0]),
        donchian_range_percentile=np.array([50.0] * (rows - 1) + [10.0]),
        donchian_low_20=donchian_low,
        bear_breakout=np.array([False] * (rows - 1) + [True]),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            "BREAKOUT_DOWN",
            details={"h1_score": 0.0, "m30_score": 0.0, "m15_score": 0.0, "htf_bias_raw": 0.0},
        )
    )

    assert candidate is not None
    assert candidate.signal == "SELL"
    assert candidate.strategy_type == "breakout_momentum"
    assert candidate.metadata["entry_style"] == "aggressive"
    assert candidate.stop_loss == 97.6


def test_strategy_brain_generates_range_mean_reversion_short_candidate() -> None:
    rows = 12
    close = np.array([100.0] * (rows - 2) + [101.2, 100.5])
    high = np.array([100.6] * (rows - 2) + [101.5, 101.3])
    low = np.array([99.4] * (rows - 2) + [100.8, 100.3])
    frame = _frame(
        close=close,
        open=np.array([100.0] * (rows - 2) + [101.0, 100.9]),
        high=high,
        low=low,
        ADX_14=np.full(rows, 14.0),
        RSI_14=np.array([50.0] * (rows - 1) + [70.0]),
        rsi_slope=np.array([0.0] * (rows - 1) + [-1.5]),
        MACD_hist_slope=np.array([0.0] * (rows - 1) + [-0.4]),
        upper_wick_ratio=np.array([0.2] * (rows - 1) + [0.5]),
        close_position_in_range=np.array([0.5] * (rows - 1) + [0.2]),
        candle_direction=["NEUTRAL"] * (rows - 1) + ["BEARISH"],
        price_z_atr=np.array([0.0] * (rows - 1) + [1.7]),
        bearish_liquidity_sweep=np.array([False] * (rows - 2) + [True, False]),
        last_confirmed_swing_high=np.full(rows, 102.0),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            REGIME_RANGE,
            details={"h1_score": 0.0, "m30_score": 0.0, "m15_score": 0.0, "htf_bias_raw": 0.0},
        )
    )

    assert candidate is not None
    assert candidate.signal == "SELL"
    assert candidate.strategy_type == "range_mean_reversion"
    assert candidate.regime == REGIME_RANGE
    assert candidate.take_profit_1 == 100.0


def test_strategy_brain_generates_range_mean_reversion_long_candidate() -> None:
    rows = 12
    close = np.array([100.0] * (rows - 2) + [98.8, 99.4])
    high = np.array([100.6] * (rows - 2) + [99.2, 99.8])
    low = np.array([99.4] * (rows - 2) + [98.2, 98.6])
    frame = _frame(
        close=close,
        open=np.array([100.0] * (rows - 2) + [98.9, 98.8]),
        high=high,
        low=low,
        ADX_14=np.full(rows, 14.0),
        RSI_14=np.array([50.0] * (rows - 1) + [30.0]),
        rsi_slope=np.array([0.0] * (rows - 1) + [1.5]),
        MACD_hist_slope=np.array([0.0] * (rows - 1) + [0.4]),
        lower_wick_ratio=np.array([0.2] * (rows - 1) + [0.5]),
        close_position_in_range=np.array([0.5] * (rows - 1) + [0.8]),
        candle_direction=["NEUTRAL"] * (rows - 1) + ["BULLISH"],
        price_z_atr=np.array([0.0] * (rows - 1) + [-1.7]),
        bullish_liquidity_sweep=np.array([False] * (rows - 2) + [True, False]),
        last_confirmed_swing_low=np.full(rows, 98.0),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            REGIME_RANGE,
            details={"h1_score": 0.0, "m30_score": 0.0, "m15_score": 0.0, "htf_bias_raw": 0.0},
        )
    )

    assert candidate is not None
    assert candidate.signal == "BUY"
    assert candidate.strategy_type == "range_mean_reversion"
    assert candidate.regime == REGIME_RANGE
    assert candidate.take_profit_1 == 100.0


def test_strategy_brain_blocks_breakout_against_h1_without_priority_score() -> None:
    rows = 12
    donchian_high = np.array([102.0] * (rows - 3) + [102.0, 103.0, 106.0])
    frame = _frame(
        close=np.array([100.0] * (rows - 2) + [104.0, 103.4]),
        open=np.array([100.0] * (rows - 2) + [103.0, 103.0]),
        high=np.array([100.6] * (rows - 2) + [104.5, 103.8]),
        low=np.array([99.4] * (rows - 2) + [102.8, 102.9]),
        ADX_14=np.array([12.0] * (rows - 2) + [18.0, 17.5]),
        ATR_14=np.array([1.0] * (rows - 2) + [1.2, 1.1]),
        body_ratio=np.array([0.3] * (rows - 2) + [0.7, 0.4]),
        close_position_in_range=np.array([0.5] * (rows - 2) + [0.9, 0.75]),
        candle_direction=["NEUTRAL"] * (rows - 2) + ["BULLISH", "BULLISH"],
        MACD_hist_slope=np.array([0.0] * (rows - 2) + [0.3, 0.2]),
        lower_wick_ratio=np.array([0.2] * (rows - 2) + [0.4, 0.4]),
        BB_width_percentile=np.array([50.0] * (rows - 2) + [10.0, 20.0]),
        donchian_range_percentile=np.array([50.0] * (rows - 2) + [10.0, 20.0]),
        donchian_high_20=donchian_high,
        bull_breakout=np.array([False] * (rows - 2) + [True, False]),
    )

    candidate = StrategyBrain().generate_candidate(
        _context(
            frame,
            "UNKNOWN",
            details={"h1_score": -1.0, "m30_score": 0.0, "m15_score": 0.0, "htf_bias_raw": -0.5},
        )
    )

    assert candidate is None