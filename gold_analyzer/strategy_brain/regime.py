from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .context import MarketRegimeState
from .indicators import IndicatorBuilder, IndicatorConfig


REGIME_TREND_UP = "TREND_UP"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_RANGE = "RANGE"
REGIME_BREAKOUT_UP = "BREAKOUT_UP"
REGIME_BREAKOUT_DOWN = "BREAKOUT_DOWN"
REGIME_HIGH_VOLATILITY = "HIGH_VOLATILITY"
REGIME_LOW_LIQUIDITY = "LOW_LIQUIDITY"
REGIME_NO_TRADE = "NO_TRADE"

_BASE_TIMEFRAME = "5m"
_HIGHER_TIMEFRAMES = ("15m", "30m", "1h")
_REQUIRED_TIMEFRAMES = (_BASE_TIMEFRAME, *_HIGHER_TIMEFRAMES)
_PERSISTENCE_PRIORITY = (
    REGIME_LOW_LIQUIDITY,
    REGIME_HIGH_VOLATILITY,
    REGIME_BREAKOUT_UP,
    REGIME_BREAKOUT_DOWN,
    REGIME_TREND_UP,
    REGIME_TREND_DOWN,
    REGIME_RANGE,
    REGIME_NO_TRADE,
)
_REQUIRED_COLUMNS = {
    "close",
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "ema_slope_20",
    "plus_di_14",
    "minus_di_14",
    "ADX_14",
    "ATR_14",
    "atr_percentile",
    "BB_width",
    "donchian_range_20",
    "body_ratio",
    "close_position_in_range",
    "bull_breakout",
    "bear_breakout",
    "vol_z",
    "spread_atr",
    "spread",
    "range",
}


@dataclass(frozen=True)
class RegimeConfig:
    trend_adx_min: float = 18.0
    trend_atr_percentile_min: float = 20.0
    trend_atr_percentile_max: float = 90.0
    range_adx_max: float = 18.0
    range_atr_percentile_min: float = 15.0
    range_atr_percentile_max: float = 80.0
    range_bb_width_percentile_max: float = 60.0
    range_ema_distance_atr_max: float = 0.5
    breakout_squeeze_percentile_max: float = 25.0
    breakout_body_ratio_min: float = 0.55
    breakout_close_position_up: float = 0.75
    breakout_close_position_down: float = 0.25
    breakout_immediate_score_min: float = 0.85
    high_volatility_atr_percentile_min: float = 95.0
    high_volatility_range_atr_multiple: float = 2.5
    low_liquidity_vol_z_threshold: float = -1.5
    low_liquidity_min_bars: int = 2
    low_liquidity_window: int = 3
    low_liquidity_spread_atr_max: float = 0.15
    low_liquidity_spread_max: float | None = None
    persistence_window: int = 3
    persistence_min_count: int = 2
    epsilon: float = 1e-12


class MarketRegimeClassifier:
    def __init__(
        self,
        config: RegimeConfig | None = None,
        *,
        indicator_config: IndicatorConfig | None = None,
    ) -> None:
        self.config = config or RegimeConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        self.indicator_builder = IndicatorBuilder(config=self.indicator_config)

    def classify(self, frames: Mapping[str, pd.DataFrame]) -> MarketRegimeState:
        missing_timeframes = [timeframe for timeframe in _REQUIRED_TIMEFRAMES if timeframe not in frames]
        if missing_timeframes:
            return MarketRegimeState(
                regime=REGIME_NO_TRADE,
                confidence=0.0,
                details={
                    "reason": "MISSING_TIMEFRAMES",
                    "missing_timeframes": missing_timeframes,
                },
            )

        annotated = self.annotate(frames)
        if annotated.empty:
            return MarketRegimeState(
                regime=REGIME_NO_TRADE,
                confidence=0.0,
                details={"reason": "NO_CANDLES"},
            )

        last = annotated.iloc[-1]
        return MarketRegimeState(
            regime=str(last["market_regime"]),
            confidence=float(last["regime_confidence"]),
            details={
                "candidate_regime": str(last["regime_candidate"]),
                "candidate_history": [str(value) for value in annotated["regime_candidate"].tail(self.config.persistence_window)],
                "regime_history": [str(value) for value in annotated["market_regime"].tail(self.config.persistence_window)],
                "htf_bias_raw": float(last["htf_bias_raw"]),
                "htf_bias_label": str(last["htf_bias_label"]),
                "h1_score": float(last["h1_bias_score"]),
                "m30_score": float(last["m30_bias_score"]),
                "m15_score": float(last["m15_bias_score"]),
                "breakout_score_up": float(last["breakout_score_up"]),
                "breakout_score_down": float(last["breakout_score_down"]),
                "regime_score": float(last["regime_candidate_score"]),
            },
        )

    def annotate(self, frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        aligned = self._aligned_frame(frames)
        if aligned.empty:
            return aligned

        config = self.config
        aligned["h1_bias_score"] = _trend_bias_score(aligned, suffix="_1h")
        aligned["m30_bias_score"] = _trend_bias_score(aligned, suffix="_30m")
        aligned["m15_bias_score"] = _trend_bias_score(aligned, suffix="_15m")
        aligned["htf_bias_raw"] = (
            0.50 * aligned["h1_bias_score"]
            + 0.30 * aligned["m30_bias_score"]
            + 0.20 * aligned["m15_bias_score"]
        )
        aligned["htf_bias_label"] = np.select(
            [aligned["htf_bias_raw"] >= 0.50, aligned["htf_bias_raw"] <= -0.50],
            ["BULLISH", "BEARISH"],
            default="NEUTRAL",
        )

        adx_rising = aligned["ADX_14"] > aligned["ADX_14"].shift(1)
        atr_rising = aligned["ATR_14"] > aligned["ATR_14"].shift(1)
        squeeze = (aligned["BB_width_percentile"] <= config.breakout_squeeze_percentile_max) | (
            aligned["donchian_range_percentile"] <= config.breakout_squeeze_percentile_max
        )
        low_volume = aligned["vol_z"] < config.low_liquidity_vol_z_threshold
        low_volume_multi = (
            low_volume.rolling(window=config.low_liquidity_window, min_periods=1).sum()
            >= config.low_liquidity_min_bars
        )
        spread_limit = pd.Series(False, index=aligned.index)
        if config.low_liquidity_spread_max is not None:
            spread_limit = aligned["spread"] > config.low_liquidity_spread_max

        trend_up = (
            (aligned["htf_bias_raw"] >= 0.50)
            & (aligned["close"] > aligned["EMA_50"])
            & (aligned["close_15m"] > aligned["EMA_50_15m"])
            & (aligned["ADX_14"] >= config.trend_adx_min)
            & (aligned["plus_di_14"] > aligned["minus_di_14"])
            & _between(
                aligned["atr_percentile"],
                config.trend_atr_percentile_min,
                config.trend_atr_percentile_max,
            )
        )
        trend_down = (
            (aligned["htf_bias_raw"] <= -0.50)
            & (aligned["close"] < aligned["EMA_50"])
            & (aligned["close_15m"] < aligned["EMA_50_15m"])
            & (aligned["ADX_14"] >= config.trend_adx_min)
            & (aligned["minus_di_14"] > aligned["plus_di_14"])
            & _between(
                aligned["atr_percentile"],
                config.trend_atr_percentile_min,
                config.trend_atr_percentile_max,
            )
        )
        range_regime = (
            (aligned["htf_bias_raw"].abs() < 0.50)
            & (aligned["ADX_14"] < config.range_adx_max)
            & (aligned["BB_width_percentile"] < config.range_bb_width_percentile_max)
            & _between(
                aligned["atr_percentile"],
                config.range_atr_percentile_min,
                config.range_atr_percentile_max,
            )
            & (aligned["distance_ema50_atr"].abs() <= config.range_ema_distance_atr_max)
        )
        breakout_up = (
            squeeze
            & aligned["bull_breakout"]
            & adx_rising
            & atr_rising
            & (aligned["body_ratio"] >= config.breakout_body_ratio_min)
            & (aligned["close_position_in_range"] >= config.breakout_close_position_up)
        )
        breakout_down = (
            squeeze
            & aligned["bear_breakout"]
            & adx_rising
            & atr_rising
            & (aligned["body_ratio"] >= config.breakout_body_ratio_min)
            & (aligned["close_position_in_range"] <= config.breakout_close_position_down)
        )
        high_volatility = (
            (aligned["atr_percentile"] >= config.high_volatility_atr_percentile_min)
            | (aligned["range"] > (config.high_volatility_range_atr_multiple * aligned["ATR_14"]))
        )
        low_liquidity = (
            low_volume_multi
            | (aligned["spread_atr"] > config.low_liquidity_spread_atr_max)
            | spread_limit
        )

        aligned["trend_up_score"] = _score(
            aligned["htf_bias_raw"] >= 0.50,
            aligned["close"] > aligned["EMA_50"],
            aligned["close_15m"] > aligned["EMA_50_15m"],
            aligned["ADX_14"] >= config.trend_adx_min,
            aligned["plus_di_14"] > aligned["minus_di_14"],
            _between(
                aligned["atr_percentile"],
                config.trend_atr_percentile_min,
                config.trend_atr_percentile_max,
            ),
        )
        aligned["trend_down_score"] = _score(
            aligned["htf_bias_raw"] <= -0.50,
            aligned["close"] < aligned["EMA_50"],
            aligned["close_15m"] < aligned["EMA_50_15m"],
            aligned["ADX_14"] >= config.trend_adx_min,
            aligned["minus_di_14"] > aligned["plus_di_14"],
            _between(
                aligned["atr_percentile"],
                config.trend_atr_percentile_min,
                config.trend_atr_percentile_max,
            ),
        )
        aligned["range_score"] = _score(
            aligned["htf_bias_raw"].abs() < 0.50,
            aligned["ADX_14"] < config.range_adx_max,
            aligned["BB_width_percentile"] < config.range_bb_width_percentile_max,
            _between(
                aligned["atr_percentile"],
                config.range_atr_percentile_min,
                config.range_atr_percentile_max,
            ),
            aligned["distance_ema50_atr"].abs() <= config.range_ema_distance_atr_max,
        )
        aligned["breakout_score_up"] = _score(
            squeeze,
            aligned["bull_breakout"],
            adx_rising,
            atr_rising,
            aligned["body_ratio"] >= config.breakout_body_ratio_min,
            aligned["close_position_in_range"] >= config.breakout_close_position_up,
        )
        aligned["breakout_score_down"] = _score(
            squeeze,
            aligned["bear_breakout"],
            adx_rising,
            atr_rising,
            aligned["body_ratio"] >= config.breakout_body_ratio_min,
            aligned["close_position_in_range"] <= config.breakout_close_position_down,
        )
        aligned["high_volatility_score"] = _score(
            aligned["atr_percentile"] >= config.high_volatility_atr_percentile_min,
            aligned["range"] > (config.high_volatility_range_atr_multiple * aligned["ATR_14"]),
        )
        low_liquidity_conditions: list[pd.Series] = [
            low_volume_multi,
            aligned["spread_atr"] > config.low_liquidity_spread_atr_max,
        ]
        if config.low_liquidity_spread_max is not None:
            low_liquidity_conditions.append(spread_limit)
        aligned["low_liquidity_score"] = _score(*low_liquidity_conditions)

        candidate_conditions = [
            low_liquidity,
            high_volatility,
            breakout_up,
            breakout_down,
            trend_up,
            trend_down,
            range_regime,
        ]
        candidate_values = [
            REGIME_LOW_LIQUIDITY,
            REGIME_HIGH_VOLATILITY,
            REGIME_BREAKOUT_UP,
            REGIME_BREAKOUT_DOWN,
            REGIME_TREND_UP,
            REGIME_TREND_DOWN,
            REGIME_RANGE,
        ]
        candidate_scores = [
            aligned["low_liquidity_score"],
            aligned["high_volatility_score"],
            aligned["breakout_score_up"],
            aligned["breakout_score_down"],
            aligned["trend_up_score"],
            aligned["trend_down_score"],
            aligned["range_score"],
        ]

        aligned["regime_candidate"] = pd.Series(
            np.select(candidate_conditions, candidate_values, default=REGIME_NO_TRADE),
            index=aligned.index,
        )
        aligned["regime_candidate_score"] = np.select(
            candidate_conditions,
            candidate_scores,
            default=0.0,
        )

        score_lookup = {
            REGIME_LOW_LIQUIDITY: aligned["low_liquidity_score"],
            REGIME_HIGH_VOLATILITY: aligned["high_volatility_score"],
            REGIME_BREAKOUT_UP: aligned["breakout_score_up"],
            REGIME_BREAKOUT_DOWN: aligned["breakout_score_down"],
            REGIME_TREND_UP: aligned["trend_up_score"],
            REGIME_TREND_DOWN: aligned["trend_down_score"],
            REGIME_RANGE: aligned["range_score"],
            REGIME_NO_TRADE: pd.Series(0.0, index=aligned.index),
        }
        market_regime, regime_confidence = _apply_persistence(
            aligned["regime_candidate"],
            breakout_score_up=aligned["breakout_score_up"],
            breakout_score_down=aligned["breakout_score_down"],
            score_lookup=score_lookup,
            config=config,
        )
        aligned["market_regime"] = market_regime
        aligned["regime_confidence"] = regime_confidence
        return aligned

    def _aligned_frame(self, frames: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
        base = self._prepare_frame(frames[_BASE_TIMEFRAME])
        if base.empty:
            return base

        for timeframe in _HIGHER_TIMEFRAMES:
            suffix = f"_{timeframe}"
            other = self._prepare_frame(frames[timeframe])
            aligned_columns = other[
                [
                    "ts",
                    "close",
                    "EMA_20",
                    "EMA_50",
                    "EMA_200",
                    "ema_slope_20",
                    "plus_di_14",
                    "minus_di_14",
                ]
            ].rename(
                columns={
                    column: f"{column}{suffix}"
                    for column in (
                        "close",
                        "EMA_20",
                        "EMA_50",
                        "EMA_200",
                        "ema_slope_20",
                        "plus_di_14",
                        "minus_di_14",
                    )
                }
            )
            base = pd.merge_asof(base, aligned_columns, on="ts", direction="backward")

        return base

    def _prepare_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        prepared = frame.copy()
        if "ts" not in prepared.columns and "timestamps" in prepared.columns:
            prepared = prepared.rename(columns={"timestamps": "ts"})
        if "ts" not in prepared.columns:
            raise ValueError("Regime frames must include a ts column")

        prepared["ts"] = pd.to_datetime(prepared["ts"], utc=True)
        prepared = prepared.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
        if prepared.empty:
            return prepared

        if not _REQUIRED_COLUMNS.issubset(prepared.columns):
            raw_columns = {"open", "high", "low", "close"}
            if raw_columns.issubset(prepared.columns):
                prepared = self.indicator_builder.build(prepared)

        missing_columns = sorted(_REQUIRED_COLUMNS.difference(prepared.columns))
        if missing_columns:
            raise ValueError(
                "Regime frame missing required columns: " + ", ".join(missing_columns)
            )

        if "distance_ema50_atr" not in prepared.columns:
            prepared["distance_ema50_atr"] = (prepared["close"] - prepared["EMA_50"]) / _safe_divisor(
                prepared["ATR_14"],
                self.config.epsilon,
            )
        if "BB_width_percentile" not in prepared.columns:
            prepared["BB_width_percentile"] = prepared["BB_width"].rolling(
                window=self.indicator_config.bb_width_percentile_window,
                min_periods=1,
            ).apply(_percentile_rank_last, raw=False)
        if "donchian_range_percentile" not in prepared.columns:
            prepared["donchian_range_percentile"] = prepared["donchian_range_20"].rolling(
                window=self.indicator_config.donchian_percentile_window,
                min_periods=1,
            ).apply(_percentile_rank_last, raw=False)

        return prepared


def classify_market_regime(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: RegimeConfig | None = None,
    indicator_config: IndicatorConfig | None = None,
) -> MarketRegimeState:
    return MarketRegimeClassifier(config=config, indicator_config=indicator_config).classify(frames)


def _safe_divisor(series: pd.Series, epsilon: float) -> pd.Series:
    return series.where(series.abs() > epsilon, epsilon)


def _between(series: pd.Series, low: float, high: float) -> pd.Series:
    return series.ge(low) & series.le(high)


def _percentile_rank_last(window: pd.Series) -> float:
    clean = window.dropna()
    if clean.empty:
        return float("nan")
    last = clean.iloc[-1]
    return float((clean <= last).mean() * 100.0)


def _score(*conditions: pd.Series) -> pd.Series:
    return pd.concat([condition.fillna(False).astype(float) for condition in conditions], axis=1).mean(axis=1)


def _trend_bias_score(frame: pd.DataFrame, *, suffix: str) -> pd.Series:
    bullish = (
        (frame[f"EMA_20{suffix}"] > frame[f"EMA_50{suffix}"])
        & (
            (frame[f"EMA_50{suffix}"] >= frame[f"EMA_200{suffix}"])
            | (frame[f"close{suffix}"] > frame[f"EMA_200{suffix}"])
        )
        & (frame[f"ema_slope_20{suffix}"] > 0.0)
        & (frame[f"plus_di_14{suffix}"] > frame[f"minus_di_14{suffix}"])
    )
    bearish = (
        (frame[f"EMA_20{suffix}"] < frame[f"EMA_50{suffix}"])
        & (
            (frame[f"EMA_50{suffix}"] <= frame[f"EMA_200{suffix}"])
            | (frame[f"close{suffix}"] < frame[f"EMA_200{suffix}"])
        )
        & (frame[f"ema_slope_20{suffix}"] < 0.0)
        & (frame[f"minus_di_14{suffix}"] > frame[f"plus_di_14{suffix}"])
    )

    return pd.Series(
        np.select([bullish, bearish], [1.0, -1.0], default=0.0),
        index=frame.index,
    )


def _apply_persistence(
    candidate_regime: pd.Series,
    *,
    breakout_score_up: pd.Series,
    breakout_score_down: pd.Series,
    score_lookup: dict[str, pd.Series],
    config: RegimeConfig,
) -> tuple[pd.Series, pd.Series]:
    final_regimes: list[str] = []
    confidences: list[float] = []

    for index in range(len(candidate_regime)):
        candidate = str(candidate_regime.iloc[index])
        breakout_score = 0.0
        if candidate == REGIME_BREAKOUT_UP:
            breakout_score = float(breakout_score_up.iloc[index])
        elif candidate == REGIME_BREAKOUT_DOWN:
            breakout_score = float(breakout_score_down.iloc[index])

        if candidate in {REGIME_BREAKOUT_UP, REGIME_BREAKOUT_DOWN} and breakout_score >= config.breakout_immediate_score_min:
            final_regimes.append(candidate)
            confidences.append(breakout_score)
            continue

        window = candidate_regime.iloc[max(0, index - config.persistence_window + 1) : index + 1]
        counts = window.value_counts()
        selected_regime = REGIME_NO_TRADE
        selected_count = 0

        for regime in _PERSISTENCE_PRIORITY:
            count = int(counts.get(regime, 0))
            if count >= config.persistence_min_count:
                selected_regime = regime
                selected_count = count
                break

        final_regimes.append(selected_regime)
        if selected_regime == REGIME_NO_TRADE:
            confidences.append(0.0)
            continue

        persistence_share = selected_count / len(window)
        regime_score = float(score_lookup[selected_regime].iloc[index])
        confidences.append(max(persistence_share, regime_score))

    return (
        pd.Series(final_regimes, index=candidate_regime.index),
        pd.Series(confidences, index=candidate_regime.index, dtype=float),
    )


__all__ = [
    "MarketRegimeClassifier",
    "REGIME_BREAKOUT_DOWN",
    "REGIME_BREAKOUT_UP",
    "REGIME_HIGH_VOLATILITY",
    "REGIME_LOW_LIQUIDITY",
    "REGIME_NO_TRADE",
    "REGIME_RANGE",
    "REGIME_TREND_DOWN",
    "REGIME_TREND_UP",
    "RegimeConfig",
    "classify_market_regime",
]