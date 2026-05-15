from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .context import StrategyContext
from .indicators import IndicatorBuilder, IndicatorConfig
from .models import StrategyCandidate
from .regime import (
    REGIME_BREAKOUT_DOWN,
    REGIME_BREAKOUT_UP,
    REGIME_HIGH_VOLATILITY,
    REGIME_LOW_LIQUIDITY,
    REGIME_NO_TRADE,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
)


_RAW_PRICE_COLUMNS = {"open", "high", "low", "close"}
_SIGNAL_COLUMNS = {
    "high",
    "low",
    "close",
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "ema_slope_20",
    "plus_di_14",
    "minus_di_14",
    "ADX_14",
    "ATR_14",
    "RSI_14",
    "rsi_slope",
    "MACD_hist_slope",
    "body_ratio",
    "lower_wick_ratio",
    "upper_wick_ratio",
    "close_position_in_range",
    "candle_direction",
    "price_z_atr",
    "BB_lower",
    "BB_upper",
    "BB_mid",
    "BB_width_percentile",
    "donchian_high_20",
    "donchian_low_20",
    "donchian_range_percentile",
    "bull_breakout",
    "bear_breakout",
    "bullish_liquidity_sweep",
    "bearish_liquidity_sweep",
    "bullish_bos",
    "bearish_bos",
    "last_confirmed_swing_low",
    "last_confirmed_swing_high",
}


@dataclass(frozen=True)
class StrategyBrainConfig:
    trend_adx_min: float = 18.0
    trend_conflict_adx_min: float = 20.0
    trend_trigger_min_count: int = 2
    trend_sweep_lookback: int = 5
    trend_bos_lookback: int = 10
    trend_long_price_z_min: float = -1.2
    trend_long_price_z_max: float = 0.2
    trend_short_price_z_min: float = -0.2
    trend_short_price_z_max: float = 1.2
    breakout_entry_score_min: float = 0.85
    breakout_priority_score_min: float = 0.90
    breakout_trigger_min_count: int = 2
    breakout_retest_lookback: int = 3
    breakout_wick_ratio_min: float = 0.35
    range_trigger_min_count: int = 2
    range_sweep_lookback: int = 5
    epsilon: float = 1e-12


class StrategyBrain:
    """Rule-based strategy selector for additive StrategyCandidate generation."""

    def __init__(
        self,
        config: StrategyBrainConfig | None = None,
        *,
        indicator_config: IndicatorConfig | None = None,
    ) -> None:
        self.config = config or StrategyBrainConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        self.indicator_builder = IndicatorBuilder(config=self.indicator_config)

    def generate_candidate(self, context: StrategyContext) -> StrategyCandidate | None:
        frame = self._prepare_frame(context)
        if frame is None or len(frame) < 2:
            return None

        regime = str(context.market_regime.regime or "UNKNOWN").upper().strip()
        if regime in {REGIME_HIGH_VOLATILITY, REGIME_LOW_LIQUIDITY, REGIME_NO_TRADE}:
            return None

        htf = self._resolve_htf_state(context)
        trend_candidate = self._build_trend_pullback_candidate(frame, regime, htf)
        breakout_candidate = self._build_breakout_candidate(frame, regime, htf)
        range_candidate = self._build_range_mean_reversion_candidate(frame, regime, htf)
        return self._select_candidate(frame, trend_candidate, breakout_candidate, range_candidate)

    def _prepare_frame(self, context: StrategyContext) -> pd.DataFrame | None:
        frame = context.candles
        if frame is None or frame.empty:
            return None

        prepared = frame.copy()
        if "ts" in prepared.columns:
            prepared["ts"] = pd.to_datetime(prepared["ts"], utc=True)
            prepared = prepared.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)

        if not _SIGNAL_COLUMNS.issubset(prepared.columns):
            has_timestamp = ("ts" in prepared.columns) or ("timestamps" in prepared.columns)
            if _RAW_PRICE_COLUMNS.issubset(prepared.columns) and has_timestamp:
                prepared = self.indicator_builder.build(prepared)
            else:
                return None

        if not _SIGNAL_COLUMNS.issubset(prepared.columns):
            return None
        return prepared

    def _resolve_htf_state(self, context: StrategyContext) -> dict[str, float]:
        details = dict(context.market_regime.details or {})
        scores = {
            "h1_score": self._coerce_float(details.get("h1_score")),
            "m30_score": self._coerce_float(details.get("m30_score")),
            "m15_score": self._coerce_float(details.get("m15_score")),
        }

        for timeframe, key in (("1h", "h1_score"), ("30m", "m30_score"), ("15m", "m15_score")):
            if scores[key] is None:
                scores[key] = self._htf_score_from_context(context, timeframe)

        scores = {key: float(value if value is not None else 0.0) for key, value in scores.items()}
        raw = self._coerce_float(details.get("htf_bias_raw"))
        if raw is None:
            raw = (0.50 * scores["h1_score"]) + (0.30 * scores["m30_score"]) + (0.20 * scores["m15_score"])
        scores["htf_bias_raw"] = float(raw)
        return scores

    def _htf_score_from_context(self, context: StrategyContext, timeframe: str) -> float:
        value = context.indicators.get(timeframe)
        if not isinstance(value, pd.DataFrame) or value.empty:
            return 0.0
        row = value.iloc[-1]
        bullish = (
            (self._coerce_float(row.get("EMA_20")) is not None)
            and (self._coerce_float(row.get("EMA_50")) is not None)
            and (self._coerce_float(row.get("EMA_200")) is not None)
            and (self._coerce_float(row.get("close")) is not None)
            and (self._coerce_float(row.get("ema_slope_20")) is not None)
            and (self._coerce_float(row.get("plus_di_14")) is not None)
            and (self._coerce_float(row.get("minus_di_14")) is not None)
            and (float(row["EMA_20"]) > float(row["EMA_50"]))
            and ((float(row["EMA_50"]) >= float(row["EMA_200"])) or (float(row["close"]) > float(row["EMA_200"])))
            and (float(row["ema_slope_20"]) > 0.0)
            and (float(row["plus_di_14"]) > float(row["minus_di_14"]))
        )
        bearish = (
            (self._coerce_float(row.get("EMA_20")) is not None)
            and (self._coerce_float(row.get("EMA_50")) is not None)
            and (self._coerce_float(row.get("EMA_200")) is not None)
            and (self._coerce_float(row.get("close")) is not None)
            and (self._coerce_float(row.get("ema_slope_20")) is not None)
            and (self._coerce_float(row.get("plus_di_14")) is not None)
            and (self._coerce_float(row.get("minus_di_14")) is not None)
            and (float(row["EMA_20"]) < float(row["EMA_50"]))
            and ((float(row["EMA_50"]) <= float(row["EMA_200"])) or (float(row["close"]) < float(row["EMA_200"])))
            and (float(row["ema_slope_20"]) < 0.0)
            and (float(row["minus_di_14"]) > float(row["plus_di_14"]))
        )
        if bullish:
            return 1.0
        if bearish:
            return -1.0
        return 0.0

    def _build_trend_pullback_candidate(
        self,
        frame: pd.DataFrame,
        regime: str,
        htf: dict[str, float],
    ) -> StrategyCandidate | None:
        if regime == REGIME_TREND_UP:
            return self._build_trend_long(frame, htf)
        if regime == REGIME_TREND_DOWN:
            return self._build_trend_short(frame, htf)
        return None

    def _build_trend_long(self, frame: pd.DataFrame, htf: dict[str, float]) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        atr = self._coerce_float(current.get("ATR_14"))
        entry = self._coerce_float(current.get("close"))
        swing_low = self._coerce_float(current.get("last_confirmed_swing_low"))
        if atr is None or atr <= 0.0 or entry is None:
            return None

        htf_ok = (htf["h1_score"] >= 0.0) and (htf["m30_score"] > 0.0) and (htf["m15_score"] >= 0.0)
        trend_checks = {
            "close_above_ema50": entry > float(current["EMA_50"]),
            "ema20_above_ema50": float(current["EMA_20"]) > float(current["EMA_50"]),
            "ema20_slope_positive": float(current["ema_slope_20"]) > 0.0,
            "adx_min": float(current["ADX_14"]) >= self.config.trend_adx_min,
            "plus_di_control": float(current["plus_di_14"]) > float(current["minus_di_14"]),
        }
        pullback_hits = {
            "ema20_reclaim": (float(current["low"]) <= float(current["EMA_20"])) and (entry > float(current["EMA_20"])),
            "ema50_reclaim": (float(current["low"]) <= float(current["EMA_50"])) and (entry > float(current["EMA_50"])),
            "price_z_reset": self.config.trend_long_price_z_min <= float(current["price_z_atr"]) <= self.config.trend_long_price_z_max,
        }
        momentum_ok = (40.0 <= float(current["RSI_14"]) <= 58.0) and (float(current["rsi_slope"]) > 0.0)
        trigger_hits = {
            "bullish_candle": str(current["candle_direction"]).upper() == "BULLISH",
            "lower_wick": float(current["lower_wick_ratio"]) >= 0.35,
            "close_near_high": float(current["close_position_in_range"]) >= 0.65,
            "macd_hist_rising": float(current["MACD_hist_slope"]) > 0.0,
            "recent_liquidity_sweep": self._recent_true(frame, "bullish_liquidity_sweep", self.config.trend_sweep_lookback),
            "recent_bos": self._recent_true(frame, "bullish_bos", self.config.trend_bos_lookback),
        }

        if not htf_ok or not all(trend_checks.values()) or not any(pullback_hits.values()) or not momentum_ok:
            return None
        if self._hit_count(trigger_hits) < self.config.trend_trigger_min_count:
            return None

        stop_candidates = [entry - (1.20 * atr)]
        if swing_low is not None:
            stop_candidates.append(swing_low - (0.20 * atr))
        stop = min(stop_candidates)
        if stop >= entry:
            return None

        risk = entry - stop
        strategy_score = 100.0 * self._average(
            [
                1.0 if htf_ok else 0.0,
                self._fraction(list(trend_checks.values())),
                self._fraction(list(pullback_hits.values())),
                1.0 if momentum_ok else 0.0,
                self._fraction(list(trigger_hits.values())),
            ]
        )
        return StrategyCandidate(
            signal="BUY",
            strategy_type="trend_pullback",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=entry + (0.80 * risk),
            take_profit_2=entry + (1.50 * risk),
            regime=REGIME_TREND_UP,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "RSI_14",
                    "price_z_atr",
                    "EMA_20",
                    "EMA_50",
                    "plus_di_14",
                    "minus_di_14",
                },
            ),
            notes=self._hit_names(pullback_hits) + self._hit_names(trigger_hits),
            metadata={
                "direction": "LONG",
                "trigger_count": self._hit_count(trigger_hits),
                "pullback_count": self._hit_count(pullback_hits),
                "htf_scores": dict(htf),
            },
        )

    def _build_trend_short(self, frame: pd.DataFrame, htf: dict[str, float]) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        atr = self._coerce_float(current.get("ATR_14"))
        entry = self._coerce_float(current.get("close"))
        swing_high = self._coerce_float(current.get("last_confirmed_swing_high"))
        if atr is None or atr <= 0.0 or entry is None:
            return None

        htf_ok = (htf["h1_score"] <= 0.0) and (htf["m30_score"] < 0.0) and (htf["m15_score"] <= 0.0)
        trend_checks = {
            "close_below_ema50": entry < float(current["EMA_50"]),
            "ema20_below_ema50": float(current["EMA_20"]) < float(current["EMA_50"]),
            "ema20_slope_negative": float(current["ema_slope_20"]) < 0.0,
            "adx_min": float(current["ADX_14"]) >= self.config.trend_adx_min,
            "minus_di_control": float(current["minus_di_14"]) > float(current["plus_di_14"]),
        }
        pullback_hits = {
            "ema20_reject": (float(current["high"]) >= float(current["EMA_20"])) and (entry < float(current["EMA_20"])),
            "ema50_reject": (float(current["high"]) >= float(current["EMA_50"])) and (entry < float(current["EMA_50"])),
            "price_z_reset": self.config.trend_short_price_z_min <= float(current["price_z_atr"]) <= self.config.trend_short_price_z_max,
        }
        momentum_ok = (42.0 <= float(current["RSI_14"]) <= 60.0) and (float(current["rsi_slope"]) < 0.0)
        trigger_hits = {
            "bearish_candle": str(current["candle_direction"]).upper() == "BEARISH",
            "upper_wick": float(current["upper_wick_ratio"]) >= 0.35,
            "close_near_low": float(current["close_position_in_range"]) <= 0.35,
            "macd_hist_falling": float(current["MACD_hist_slope"]) < 0.0,
            "recent_liquidity_sweep": self._recent_true(frame, "bearish_liquidity_sweep", self.config.trend_sweep_lookback),
            "recent_bos": self._recent_true(frame, "bearish_bos", self.config.trend_bos_lookback),
        }

        if not htf_ok or not all(trend_checks.values()) or not any(pullback_hits.values()) or not momentum_ok:
            return None
        if self._hit_count(trigger_hits) < self.config.trend_trigger_min_count:
            return None

        stop_candidates = [entry + (1.20 * atr)]
        if swing_high is not None:
            stop_candidates.append(swing_high + (0.20 * atr))
        stop = max(stop_candidates)
        if stop <= entry:
            return None

        risk = stop - entry
        strategy_score = 100.0 * self._average(
            [
                1.0 if htf_ok else 0.0,
                self._fraction(list(trend_checks.values())),
                self._fraction(list(pullback_hits.values())),
                1.0 if momentum_ok else 0.0,
                self._fraction(list(trigger_hits.values())),
            ]
        )
        return StrategyCandidate(
            signal="SELL",
            strategy_type="trend_pullback",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=entry - (0.80 * risk),
            take_profit_2=entry - (1.50 * risk),
            regime=REGIME_TREND_DOWN,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "RSI_14",
                    "price_z_atr",
                    "EMA_20",
                    "EMA_50",
                    "plus_di_14",
                    "minus_di_14",
                },
            ),
            notes=self._hit_names(pullback_hits) + self._hit_names(trigger_hits),
            metadata={
                "direction": "SHORT",
                "trigger_count": self._hit_count(trigger_hits),
                "pullback_count": self._hit_count(pullback_hits),
                "htf_scores": dict(htf),
            },
        )

    def _build_breakout_candidate(
        self,
        frame: pd.DataFrame,
        regime: str,
        htf: dict[str, float],
    ) -> StrategyCandidate | None:
        long_candidate = self._build_breakout_long(frame, regime, htf)
        short_candidate = self._build_breakout_short(frame, regime, htf)
        if long_candidate is None:
            return short_candidate
        if short_candidate is None:
            return long_candidate
        if float(long_candidate.metadata.get("breakout_score", 0.0)) >= float(short_candidate.metadata.get("breakout_score", 0.0)):
            return long_candidate
        return short_candidate

    def _build_breakout_long(
        self,
        frame: pd.DataFrame,
        regime: str,
        htf: dict[str, float],
    ) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        previous = frame.iloc[-2]
        entry = self._coerce_float(current.get("close"))
        atr = self._coerce_float(current.get("ATR_14"))
        breakout_level_now = self._coerce_float(frame["donchian_high_20"].shift(1).iloc[-1])
        if entry is None or atr is None or atr <= 0.0 or breakout_level_now is None:
            return None

        breakout_checks = {
            "squeeze": (float(current["BB_width_percentile"]) <= 25.0) or (float(current["donchian_range_percentile"]) <= 25.0),
            "breakout": bool(current["bull_breakout"]),
            "adx_rising": float(current["ADX_14"]) > float(previous["ADX_14"]),
            "atr_rising": float(current["ATR_14"]) > float(previous["ATR_14"]),
            "body_strength": float(current["body_ratio"]) >= 0.55,
            "close_strength": float(current["close_position_in_range"]) >= 0.75,
        }
        breakout_score = self._fraction(list(breakout_checks.values()))
        breakout_level = breakout_level_now
        recent_breakout_level = self._recent_breakout_level(frame, "bull_breakout", "donchian_high_20")
        retest_triggers = {
            "bullish_candle": str(current["candle_direction"]).upper() == "BULLISH",
            "lower_wick": float(current["lower_wick_ratio"]) >= self.config.breakout_wick_ratio_min,
            "close_near_high": float(current["close_position_in_range"]) >= 0.65,
            "macd_hist_rising": float(current["MACD_hist_slope"]) > 0.0,
        }
        preferred_entry = (
            recent_breakout_level is not None
            and (float(current["low"]) <= recent_breakout_level)
            and (entry > recent_breakout_level)
            and (self._hit_count(retest_triggers) >= self.config.breakout_trigger_min_count)
        )
        aggressive_entry = breakout_score >= self.config.breakout_entry_score_min
        if not aggressive_entry and not preferred_entry:
            return None
        if regime in {REGIME_HIGH_VOLATILITY, REGIME_LOW_LIQUIDITY, REGIME_NO_TRADE}:
            return None
        if htf["h1_score"] < 0.0 and breakout_score < self.config.breakout_priority_score_min:
            return None

        entry_style = "aggressive" if aggressive_entry else "preferred_retest"
        if preferred_entry and recent_breakout_level is not None:
            breakout_level = recent_breakout_level
        stop = breakout_level - (0.50 * atr)
        if stop >= entry:
            return None

        risk = entry - stop
        strategy_score = 100.0 * max(
            breakout_score,
            self._fraction(list(retest_triggers.values())) if preferred_entry else breakout_score,
        )
        return StrategyCandidate(
            signal="BUY",
            strategy_type="breakout_momentum",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=entry + risk,
            take_profit_2=entry + (2.0 * risk),
            regime=REGIME_BREAKOUT_UP,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "body_ratio",
                    "close_position_in_range",
                    "BB_width_percentile",
                    "donchian_range_percentile",
                },
            ),
            notes=self._hit_names(breakout_checks) + self._hit_names(retest_triggers),
            metadata={
                "direction": "LONG",
                "entry_style": entry_style,
                "breakout_score": round(breakout_score, 4),
                "breakout_level": breakout_level,
                "htf_scores": dict(htf),
            },
        )

    def _build_breakout_short(
        self,
        frame: pd.DataFrame,
        regime: str,
        htf: dict[str, float],
    ) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        previous = frame.iloc[-2]
        entry = self._coerce_float(current.get("close"))
        atr = self._coerce_float(current.get("ATR_14"))
        breakout_level_now = self._coerce_float(frame["donchian_low_20"].shift(1).iloc[-1])
        if entry is None or atr is None or atr <= 0.0 or breakout_level_now is None:
            return None

        breakout_checks = {
            "squeeze": (float(current["BB_width_percentile"]) <= 25.0) or (float(current["donchian_range_percentile"]) <= 25.0),
            "breakout": bool(current["bear_breakout"]),
            "adx_rising": float(current["ADX_14"]) > float(previous["ADX_14"]),
            "atr_rising": float(current["ATR_14"]) > float(previous["ATR_14"]),
            "body_strength": float(current["body_ratio"]) >= 0.55,
            "close_strength": float(current["close_position_in_range"]) <= 0.25,
        }
        breakout_score = self._fraction(list(breakout_checks.values()))
        breakout_level = breakout_level_now
        recent_breakout_level = self._recent_breakout_level(frame, "bear_breakout", "donchian_low_20")
        retest_triggers = {
            "bearish_candle": str(current["candle_direction"]).upper() == "BEARISH",
            "upper_wick": float(current["upper_wick_ratio"]) >= self.config.breakout_wick_ratio_min,
            "close_near_low": float(current["close_position_in_range"]) <= 0.35,
            "macd_hist_falling": float(current["MACD_hist_slope"]) < 0.0,
        }
        preferred_entry = (
            recent_breakout_level is not None
            and (float(current["high"]) >= recent_breakout_level)
            and (entry < recent_breakout_level)
            and (self._hit_count(retest_triggers) >= self.config.breakout_trigger_min_count)
        )
        aggressive_entry = breakout_score >= self.config.breakout_entry_score_min
        if not aggressive_entry and not preferred_entry:
            return None
        if regime in {REGIME_HIGH_VOLATILITY, REGIME_LOW_LIQUIDITY, REGIME_NO_TRADE}:
            return None
        if htf["h1_score"] > 0.0 and breakout_score < self.config.breakout_priority_score_min:
            return None

        entry_style = "aggressive" if aggressive_entry else "preferred_retest"
        if preferred_entry and recent_breakout_level is not None:
            breakout_level = recent_breakout_level
        stop = breakout_level + (0.50 * atr)
        if stop <= entry:
            return None

        risk = stop - entry
        strategy_score = 100.0 * max(
            breakout_score,
            self._fraction(list(retest_triggers.values())) if preferred_entry else breakout_score,
        )
        return StrategyCandidate(
            signal="SELL",
            strategy_type="breakout_momentum",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=entry - risk,
            take_profit_2=entry - (2.0 * risk),
            regime=REGIME_BREAKOUT_DOWN,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "body_ratio",
                    "close_position_in_range",
                    "BB_width_percentile",
                    "donchian_range_percentile",
                },
            ),
            notes=self._hit_names(breakout_checks) + self._hit_names(retest_triggers),
            metadata={
                "direction": "SHORT",
                "entry_style": entry_style,
                "breakout_score": round(breakout_score, 4),
                "breakout_level": breakout_level,
                "htf_scores": dict(htf),
            },
        )

    def _build_range_mean_reversion_candidate(
        self,
        frame: pd.DataFrame,
        regime: str,
        htf: dict[str, float],
    ) -> StrategyCandidate | None:
        if regime != REGIME_RANGE:
            return None

        long_candidate = self._build_range_long(frame, htf)
        short_candidate = self._build_range_short(frame, htf)
        if long_candidate is None:
            return short_candidate
        if short_candidate is None:
            return long_candidate
        if float(long_candidate.strategy_score or 0.0) >= float(short_candidate.strategy_score or 0.0):
            return long_candidate
        return short_candidate

    def _build_range_long(self, frame: pd.DataFrame, htf: dict[str, float]) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        previous = frame.iloc[-2]
        entry = self._coerce_float(current.get("close"))
        atr = self._coerce_float(current.get("ATR_14"))
        bb_mid = self._coerce_float(current.get("BB_mid"))
        if entry is None or atr is None or atr <= 0.0 or bb_mid is None:
            return None

        regime_ok = (float(current["ADX_14"]) < 18.0) and (abs(htf["htf_bias_raw"]) < 0.50)
        oversold_hits = {
            "below_bb_lower": entry <= float(current["BB_lower"]),
            "price_z_extreme": float(current["price_z_atr"]) <= -1.5,
            "rsi_oversold": float(current["RSI_14"]) <= 32.0,
            "recent_sweep": self._recent_true(frame, "bullish_liquidity_sweep", self.config.range_sweep_lookback),
        }
        reversal_hits = {
            "close_back_above_bb": (float(previous["close"]) <= float(previous["BB_lower"])) and (entry > float(current["BB_lower"])),
            "bullish_reversal_candle": (str(current["candle_direction"]).upper() == "BULLISH") and (float(current["lower_wick_ratio"]) >= 0.45),
            "rsi_turns_up": float(current["rsi_slope"]) > 0.0,
            "macd_turns_up": float(current["MACD_hist_slope"]) > 0.0,
            "close_above_prev_high": entry > float(previous["high"]),
        }
        if not regime_ok or self._hit_count(oversold_hits) < 2 or self._hit_count(reversal_hits) < self.config.range_trigger_min_count:
            return None

        sweep_low = self._recent_event_price(frame, "bullish_liquidity_sweep", "low", self.config.range_sweep_lookback)
        stop_anchor = sweep_low
        if stop_anchor is None:
            stop_anchor = self._coerce_float(current.get("last_confirmed_swing_low"))
        if stop_anchor is None:
            stop_anchor = self._coerce_float(current.get("low"))
        if stop_anchor is None:
            return None

        stop = stop_anchor - (0.25 * atr)
        if stop >= entry or bb_mid <= entry:
            return None

        risk = entry - stop
        boundary = self._coerce_float(current.get("donchian_high_20"))
        ema50 = self._coerce_float(current.get("EMA_50"))
        tp2 = max(value for value in (boundary, ema50, entry + (1.50 * risk)) if value is not None and value > entry)
        strategy_score = 100.0 * self._average(
            [
                1.0 if regime_ok else 0.0,
                self._fraction(list(oversold_hits.values())),
                self._fraction(list(reversal_hits.values())),
            ]
        )
        return StrategyCandidate(
            signal="BUY",
            strategy_type="range_mean_reversion",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=bb_mid,
            take_profit_2=tp2,
            regime=REGIME_RANGE,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "RSI_14",
                    "price_z_atr",
                    "BB_lower",
                    "BB_mid",
                    "EMA_50",
                    "donchian_high_20",
                },
            ),
            notes=self._hit_names(oversold_hits) + self._hit_names(reversal_hits),
            metadata={
                "direction": "LONG",
                "oversold_count": self._hit_count(oversold_hits),
                "reversal_count": self._hit_count(reversal_hits),
                "htf_scores": dict(htf),
            },
        )

    def _build_range_short(self, frame: pd.DataFrame, htf: dict[str, float]) -> StrategyCandidate | None:
        current = frame.iloc[-1]
        previous = frame.iloc[-2]
        entry = self._coerce_float(current.get("close"))
        atr = self._coerce_float(current.get("ATR_14"))
        bb_mid = self._coerce_float(current.get("BB_mid"))
        if entry is None or atr is None or atr <= 0.0 or bb_mid is None:
            return None

        regime_ok = (float(current["ADX_14"]) < 18.0) and (abs(htf["htf_bias_raw"]) < 0.50)
        overbought_hits = {
            "above_bb_upper": entry >= float(current["BB_upper"]),
            "price_z_extreme": float(current["price_z_atr"]) >= 1.5,
            "rsi_overbought": float(current["RSI_14"]) >= 68.0,
            "recent_sweep": self._recent_true(frame, "bearish_liquidity_sweep", self.config.range_sweep_lookback),
        }
        reversal_hits = {
            "close_back_below_bb": (float(previous["close"]) >= float(previous["BB_upper"])) and (entry < float(current["BB_upper"])),
            "bearish_reversal_candle": (str(current["candle_direction"]).upper() == "BEARISH") and (float(current["upper_wick_ratio"]) >= 0.45),
            "rsi_turns_down": float(current["rsi_slope"]) < 0.0,
            "macd_turns_down": float(current["MACD_hist_slope"]) < 0.0,
            "close_below_prev_low": entry < float(previous["low"]),
        }
        if not regime_ok or self._hit_count(overbought_hits) < 2 or self._hit_count(reversal_hits) < self.config.range_trigger_min_count:
            return None

        sweep_high = self._recent_event_price(frame, "bearish_liquidity_sweep", "high", self.config.range_sweep_lookback)
        stop_anchor = sweep_high
        if stop_anchor is None:
            stop_anchor = self._coerce_float(current.get("last_confirmed_swing_high"))
        if stop_anchor is None:
            stop_anchor = self._coerce_float(current.get("high"))
        if stop_anchor is None:
            return None

        stop = stop_anchor + (0.25 * atr)
        if stop <= entry or bb_mid >= entry:
            return None

        risk = stop - entry
        boundary = self._coerce_float(current.get("donchian_low_20"))
        ema50 = self._coerce_float(current.get("EMA_50"))
        tp2 = min(value for value in (boundary, ema50, entry - (1.50 * risk)) if value is not None and value < entry)
        strategy_score = 100.0 * self._average(
            [
                1.0 if regime_ok else 0.0,
                self._fraction(list(overbought_hits.values())),
                self._fraction(list(reversal_hits.values())),
            ]
        )
        return StrategyCandidate(
            signal="SELL",
            strategy_type="range_mean_reversion",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=bb_mid,
            take_profit_2=tp2,
            regime=REGIME_RANGE,
            strategy_score=round(strategy_score, 2),
            indicators=self._indicator_snapshot(
                current,
                {
                    "ATR_14",
                    "ADX_14",
                    "RSI_14",
                    "price_z_atr",
                    "BB_upper",
                    "BB_mid",
                    "EMA_50",
                    "donchian_low_20",
                },
            ),
            notes=self._hit_names(overbought_hits) + self._hit_names(reversal_hits),
            metadata={
                "direction": "SHORT",
                "overbought_count": self._hit_count(overbought_hits),
                "reversal_count": self._hit_count(reversal_hits),
                "htf_scores": dict(htf),
            },
        )

    def _select_candidate(
        self,
        frame: pd.DataFrame,
        trend_candidate: StrategyCandidate | None,
        breakout_candidate: StrategyCandidate | None,
        range_candidate: StrategyCandidate | None,
    ) -> StrategyCandidate | None:
        if breakout_candidate is not None:
            breakout_score = float(breakout_candidate.metadata.get("breakout_score", 0.0))
            if breakout_score >= self.config.breakout_priority_score_min:
                return breakout_candidate

        if trend_candidate is not None and range_candidate is not None:
            if float(frame.iloc[-1]["ADX_14"]) >= self.config.trend_conflict_adx_min:
                return trend_candidate
            return None

        if trend_candidate is not None:
            return trend_candidate
        if breakout_candidate is not None:
            return breakout_candidate
        if range_candidate is not None:
            return range_candidate
        return None

    def _recent_true(self, frame: pd.DataFrame, column: str, lookback: int) -> bool:
        return bool(frame[column].fillna(False).tail(lookback).any())

    def _recent_event_price(
        self,
        frame: pd.DataFrame,
        event_column: str,
        price_column: str,
        lookback: int,
    ) -> float | None:
        window = frame.tail(lookback)
        hits = window[window[event_column].fillna(False)]
        if hits.empty:
            return None
        value = hits[price_column].iloc[-1]
        return self._coerce_float(value)

    def _recent_breakout_level(
        self,
        frame: pd.DataFrame,
        event_column: str,
        level_column: str,
    ) -> float | None:
        if len(frame) < 3:
            return None
        prior = frame.iloc[:-1].tail(self.config.breakout_retest_lookback)
        hits = prior[prior[event_column].fillna(False)]
        if hits.empty:
            return None
        breakout_index = hits.index[-1]
        shifted_level = frame[level_column].shift(1)
        return self._coerce_float(shifted_level.loc[breakout_index])

    def _indicator_snapshot(self, row: pd.Series, keys: set[str]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for key in sorted(keys):
            value = row.get(key)
            if pd.isna(value):
                continue
            if isinstance(value, (pd.Timestamp,)):
                snapshot[key] = value.isoformat()
            elif isinstance(value, (bool, str, int, float)):
                snapshot[key] = value
            else:
                snapshot[key] = float(value) if hasattr(value, "__float__") else value
        return snapshot

    def _coerce_float(self, value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        return float(value)

    def _fraction(self, values: list[bool]) -> float:
        if not values:
            return 0.0
        return sum(1.0 for value in values if value) / len(values)

    def _average(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _hit_count(self, values: dict[str, bool]) -> int:
        return sum(1 for value in values.values() if value)

    def _hit_names(self, values: dict[str, bool]) -> list[str]:
        return [name for name, matched in values.items() if matched]


class NullStrategyBrain(StrategyBrain):
    """Safe default that preserves current behavior by producing no setup."""

    def generate_candidate(self, context: StrategyContext) -> StrategyCandidate | None:
        del context
        return None