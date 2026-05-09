from __future__ import annotations

from typing import Any

import pandas as pd

from candle_context import load_recent_candles, resolution_to_timedelta, validate_candle_frame
from technical_indicators import (
    adx,
    atr,
    ema,
    macd,
    nearest_support_resistance,
    rsi,
    trend_strength_fallback,
    volume_zscore,
    vwap,
)


TIMEFRAME_ALIGNMENT_WEIGHTS = {
    "MINUTE_15": 8,
    "MINUTE_30": 6,
    "HOUR": 8,
    "HOUR_4": 3,
}


def _drop_unclosed(df: pd.DataFrame, resolution: str, now_utc: pd.Timestamp | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    current = now_utc or pd.Timestamp.now(tz="UTC")
    cutoff = current - resolution_to_timedelta(resolution)
    closed = df[df["timestamps"] <= cutoff].copy()
    return closed.reset_index(drop=True)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _last_two(series: pd.Series) -> tuple[float | None, float | None]:
    if series.empty:
        return None, None
    latest = _safe_float(series.iloc[-1])
    prev = _safe_float(series.iloc[-2]) if len(series.index) >= 2 else latest
    return latest, prev


def _classify_trend(
    *,
    close: float,
    ema20: float,
    ema50: float,
    rsi14: float,
    macd_hist: float,
    macd_hist_prev: float,
    strength_value: float,
) -> tuple[str, dict[str, bool]]:
    bullish_checks = {
        "close_above_ema20": close > ema20,
        "ema20_above_ema50": ema20 >= ema50,
        "macd_positive_or_improving": macd_hist > 0 or macd_hist >= macd_hist_prev,
        "rsi_preferred": 50.0 <= rsi14 <= 70.0,
        "strength_ok": strength_value >= 20.0,
    }
    bearish_checks = {
        "close_below_ema20": close < ema20,
        "ema20_below_ema50": ema20 <= ema50,
        "macd_negative_or_weakening": macd_hist < 0 or macd_hist <= macd_hist_prev,
        "rsi_preferred": 30.0 <= rsi14 <= 50.0,
        "strength_ok": strength_value >= 20.0,
    }

    bullish_votes = sum(1 for passed in bullish_checks.values() if passed)
    bearish_votes = sum(1 for passed in bearish_checks.values() if passed)

    if bullish_votes >= 3 and bullish_votes > bearish_votes:
        return "BULLISH", bullish_checks
    if bearish_votes >= 3 and bearish_votes > bullish_votes:
        return "BEARISH", bearish_checks
    return "NEUTRAL", {}


def _confirms_candidate(candidate_signal: str, trend: str) -> bool:
    signal = str(candidate_signal).upper()
    trend_value = str(trend).upper()
    if signal == "LONG":
        return trend_value == "BULLISH"
    if signal == "SHORT":
        return trend_value == "BEARISH"
    return trend_value == "NEUTRAL"


def _alignment_state(candidate_signal: str, trend: str) -> str:
    signal = str(candidate_signal).upper()
    trend_value = str(trend).upper()
    if signal == "LONG":
        if trend_value == "BULLISH":
            return "CONFIRMS"
        if trend_value == "BEARISH":
            return "CONFLICTS"
    if signal == "SHORT":
        if trend_value == "BEARISH":
            return "CONFIRMS"
        if trend_value == "BULLISH":
            return "CONFLICTS"
    if trend_value == "NEUTRAL":
        return "NEUTRAL"
    return "UNALIGNED"


def _score_components(
    *,
    timeframe: str,
    trend: str,
    candidate_signal: str,
    macd_hist: float,
    macd_hist_prev: float,
    rsi14: float,
    volume_z: float,
    atr_pct: float,
    distance_to_support_pct: float | None,
    distance_to_resistance_pct: float | None,
) -> dict[str, float]:
    align_max = TIMEFRAME_ALIGNMENT_WEIGHTS.get(timeframe, 0)
    confirms = _confirms_candidate(candidate_signal, trend)

    if trend == "NEUTRAL":
        trend_score = float(max(1, round(align_max * 0.30)))
    elif confirms:
        trend_score = float(align_max)
    else:
        trend_score = 0.0

    momentum_score = 0.0
    if candidate_signal == "LONG":
        if macd_hist > 0:
            momentum_score += 1.0
        if 50.0 <= rsi14 <= 70.0:
            momentum_score += 1.0
    elif candidate_signal == "SHORT":
        if macd_hist < 0:
            momentum_score += 1.0
        if 30.0 <= rsi14 <= 50.0:
            momentum_score += 1.0
    momentum_score = min(momentum_score, 2.0)

    if volume_z >= 0.5:
        volume_score = 2.0
    elif volume_z >= -1.0:
        volume_score = 1.0
    else:
        volume_score = 0.0

    # Penalize only extreme ATR%; moderate volatility keeps score.
    volatility_score = 1.0
    if atr_pct >= 4.0:
        volatility_score = 0.0

    support_resistance_score = 1.0
    if candidate_signal == "LONG" and distance_to_resistance_pct is not None and distance_to_resistance_pct < 0.2:
        support_resistance_score = 0.0
    if candidate_signal == "SHORT" and distance_to_support_pct is not None and distance_to_support_pct < 0.2:
        support_resistance_score = 0.0

    total = trend_score + momentum_score + volume_score + volatility_score + support_resistance_score
    return {
        "trend_score": float(trend_score),
        "momentum_score": float(momentum_score),
        "volume_score": float(volume_score),
        "volatility_score": float(volatility_score),
        "support_resistance_score": float(support_resistance_score),
        "total_timeframe_score": float(total),
    }


def validate_single_timeframe(
    *,
    symbol: str,
    timeframe: str,
    candidate_signal: str,
    price_side: str = "mid",
    limit: int = 240,
    dsn: str | None = None,
    now_utc: pd.Timestamp | None = None,
) -> dict[str, Any]:
    tf = str(timeframe).strip().upper()
    result: dict[str, Any] = {
        "timeframe": tf,
        "timestamp_utc": None,
        "trend": "NEUTRAL",
        "confirms_candidate": False,
        "alignment_state": "UNKNOWN",
        "trend_score": 0.0,
        "momentum_score": 0.0,
        "volume_score": 0.0,
        "volatility_score": 0.0,
        "support_resistance_score": 0.0,
        "total_timeframe_score": 0.0,
        "indicator_snapshot": {},
        "reason_details": [],
    }

    frame = load_recent_candles(symbol, tf, price_side=price_side, limit=max(60, int(limit)), dsn=dsn)
    frame = _drop_unclosed(frame, tf, now_utc=now_utc)

    validation = validate_candle_frame(frame, tf)
    if not validation.get("ok"):
        result["reason_details"] = list(validation.get("errors") or ["Invalid timeframe candles."])
        return result

    if len(frame.index) < 60:
        result["reason_details"].append("Insufficient candle warmup for stable indicators.")
        result["confirms_candidate"] = _confirms_candidate(candidate_signal, "NEUTRAL")
        result["alignment_state"] = _alignment_state(candidate_signal, "NEUTRAL")
        return result

    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]

    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    rsi14 = rsi(close, 14)
    _macd_line, _signal_line, macd_hist = macd(close)
    atr14 = atr(high, low, close, 14)
    adx14 = adx(high, low, close, 14)
    vol_z = volume_zscore(volume, 20)
    vw = vwap(high, low, close, volume)

    last_close = _safe_float(close.iloc[-1]) or 0.0
    last_ema20 = _safe_float(ema20.iloc[-1]) or last_close
    last_ema50 = _safe_float(ema50.iloc[-1]) or last_close
    last_rsi = _safe_float(rsi14.iloc[-1]) or 50.0
    last_macd_hist, prev_macd_hist = _last_two(macd_hist)
    last_macd_hist = 0.0 if last_macd_hist is None else last_macd_hist
    prev_macd_hist = last_macd_hist if prev_macd_hist is None else prev_macd_hist
    last_atr = _safe_float(atr14.iloc[-1]) or 0.0
    last_volume = _safe_float(volume.iloc[-1]) or 0.0
    volume_sma20 = _safe_float(volume.rolling(20, min_periods=1).mean().iloc[-1]) or 0.0
    last_volume_z = _safe_float(vol_z.iloc[-1]) or 0.0
    last_vwap = _safe_float(vw.iloc[-1]) or last_close

    atr_pct = 0.0 if last_close == 0.0 else (last_atr / last_close) * 100.0
    adx_value = _safe_float(adx14.iloc[-1])
    if adx_value is None:
        fallback = trend_strength_fallback(close, (atr14 / close.replace(0.0, pd.NA)) * 100.0, period=14)
        adx_value = _safe_float(fallback.iloc[-1]) or 0.0

    trend, _checks = _classify_trend(
        close=last_close,
        ema20=last_ema20,
        ema50=last_ema50,
        rsi14=last_rsi,
        macd_hist=last_macd_hist,
        macd_hist_prev=prev_macd_hist,
        strength_value=float(adx_value),
    )

    support_resistance = nearest_support_resistance(frame, lookback=50)
    nearest_support = support_resistance.get("nearest_support")
    nearest_resistance = support_resistance.get("nearest_resistance")
    dist_support = support_resistance.get("distance_to_support_pct")
    dist_resistance = support_resistance.get("distance_to_resistance_pct")

    scores = _score_components(
        timeframe=tf,
        trend=trend,
        candidate_signal=str(candidate_signal).upper(),
        macd_hist=last_macd_hist,
        macd_hist_prev=prev_macd_hist,
        rsi14=last_rsi,
        volume_z=last_volume_z,
        atr_pct=atr_pct,
        distance_to_support_pct=dist_support,
        distance_to_resistance_pct=dist_resistance,
    )

    result.update(scores)
    result["trend"] = trend
    result["confirms_candidate"] = _confirms_candidate(candidate_signal, trend)
    result["alignment_state"] = _alignment_state(candidate_signal, trend)
    result["timestamp_utc"] = str(frame["timestamps"].iloc[-1].isoformat())
    result["indicator_snapshot"] = {
        "close": float(last_close),
        "ema20": float(last_ema20),
        "ema50": float(last_ema50),
        "rsi14": float(last_rsi),
        "macd_hist": float(last_macd_hist),
        "atr14": float(last_atr),
        "volume": float(last_volume),
        "volume_sma20": float(volume_sma20),
        "volume_zscore": float(last_volume_z),
        "vwap": float(last_vwap),
        "nearest_support": None if nearest_support is None else float(nearest_support),
        "nearest_resistance": None if nearest_resistance is None else float(nearest_resistance),
        "distance_to_support_pct": None if dist_support is None else float(dist_support),
        "distance_to_resistance_pct": None if dist_resistance is None else float(dist_resistance),
        "trend_strength": float(adx_value),
        "atr_pct": float(atr_pct),
    }

    if trend == "NEUTRAL":
        result["reason_details"].append("Mixed trend signals or weak trend strength across EMA/MACD/RSI.")
    if result["alignment_state"] == "CONFLICTS":
        result["reason_details"].append("Timeframe trend opposes the candidate signal.")

    return result


def validate_higher_timeframes(
    *,
    symbol: str,
    candidate_signal: str,
    timeframes: list[str] | None = None,
    price_side: str = "mid",
    dsn: str | None = None,
    limit: int = 240,
    now_utc: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    selected = [tf.strip().upper() for tf in (timeframes or list(TIMEFRAME_ALIGNMENT_WEIGHTS.keys()))]
    ordered = [tf for tf in TIMEFRAME_ALIGNMENT_WEIGHTS if tf in selected]

    output: list[dict[str, Any]] = []
    for timeframe in ordered:
        output.append(
            validate_single_timeframe(
                symbol=symbol,
                timeframe=timeframe,
                candidate_signal=candidate_signal,
                price_side=price_side,
                limit=limit,
                dsn=dsn,
                now_utc=now_utc,
            )
        )
    return output
