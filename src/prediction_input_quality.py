from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


RESOLUTION_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}


@dataclass(frozen=True)
class InputQualityDecision:
    allow: bool
    reason: str
    checks: dict[str, Any]
    rejection_reasons: list[str]


@dataclass(frozen=True)
class FeatureExperimentSelection:
    feature_mode: str
    feature_columns: list[str]
    dataframe: pd.DataFrame
    amount_available: bool
    amount_derivation_method: str | None
    regime_context_used: bool
    model_input_compatible: bool
    notes: list[str]


FEATURE_MODE_ALIASES = {
    "auto": "AUTO",
    "ohlc": "OHLC",
    "ohlcv": "OHLCV_ONLY",
    "ohlcv_only": "OHLCV_ONLY",
    "ohlcva": "OHLCVA_DERIVED_AMOUNT",
    "ohlcva_derived": "OHLCVA_DERIVED_AMOUNT",
    "ohlcva_derived_amount": "OHLCVA_DERIVED_AMOUNT",
    "ohlcv_with_regime_context": "OHLCV_WITH_REGIME_CONTEXT",
    "multi_timeframe_validation_only": "MULTI_TIMEFRAME_VALIDATION_ONLY",
}


def resolution_minutes(resolution: str) -> int:
    return RESOLUTION_MINUTES.get(str(resolution).upper(), 5)


def latest_closed_timestamp(now_utc: pd.Timestamp, resolution: str) -> pd.Timestamp:
    minutes = resolution_minutes(resolution)
    timestamp = pd.to_datetime(now_utc, utc=True)
    floored = timestamp.floor(f"{minutes}min")
    return floored - pd.Timedelta(minutes=minutes)


def expected_cadence_minutes(resolution: str) -> int:
    return resolution_minutes(resolution)


def _gap_list(unique: pd.DataFrame, resolution: str) -> list[dict[str, Any]]:
    minutes = expected_cadence_minutes(resolution)
    gaps: list[dict[str, Any]] = []
    timestamps = list(pd.to_datetime(unique["timestamps"], utc=True))
    for previous, current in zip(timestamps, timestamps[1:]):
        diff_minutes = int((current - previous).total_seconds() // 60)
        if diff_minutes != minutes:
            gaps.append(
                {
                    "previous_timestamp_utc": previous.isoformat(),
                    "timestamp_utc": current.isoformat(),
                    "gap_minutes": diff_minutes,
                    "missing_candles": max(0, round(diff_minutes / minutes) - 1),
                }
            )
    return gaps


def input_window_audit(
    df: pd.DataFrame,
    *,
    resolution: str,
    requested_lookback: int,
    selected_feature_columns: list[str] | None = None,
    source_label: str | None = None,
    symbol: str | None = None,
    price_side: str | None = None,
) -> dict[str, Any]:
    clean = df.copy()
    if clean.empty:
        return {
            "source_counts": {},
            "missing_candle_count": max(0, int(requested_lookback)),
            "largest_gap_minutes": 0,
            "duplicate_timestamp_count": 0,
            "first_timestamp_utc": None,
            "last_timestamp_utc": None,
            "row_count": 0,
            "requested_lookback": int(requested_lookback),
            "actual_lookback": 0,
            "selected_feature_columns": selected_feature_columns or [],
            "amount_available": False,
            "volume_available": False,
            "terminal_close": None,
            "price_side": price_side,
            "resolution": resolution,
            "symbol": symbol,
            "gap_list": [],
        }
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    clean = clean.sort_values("timestamps").reset_index(drop=True)
    duplicate_count = int(clean["timestamps"].duplicated().sum())
    unique = clean.drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    gaps = _gap_list(unique, resolution)
    largest_gap = max([int(gap["gap_minutes"]) for gap in gaps], default=(expected_cadence_minutes(resolution) if len(unique) > 1 else 0))
    gap_missing = sum(int(gap["missing_candles"]) for gap in gaps)
    actual_lookback = int(len(unique))
    source_counts: dict[str, int] = {}
    if "source" in unique.columns:
        source_counts = {str(key): int(value) for key, value in unique["source"].fillna("unknown").value_counts().to_dict().items()}
    elif source_label:
        source_counts = {str(source_label): actual_lookback}
    amount_col = pd.to_numeric(unique["amount"], errors="coerce") if "amount" in unique.columns else pd.Series(dtype=float)
    volume_col = pd.to_numeric(unique["volume"], errors="coerce") if "volume" in unique.columns else pd.Series(dtype=float)
    return {
        "source_counts": source_counts,
        "missing_candle_count": max(0, int(requested_lookback) - actual_lookback, int(gap_missing)),
        "largest_gap_minutes": int(largest_gap),
        "expected_gap_minutes": expected_cadence_minutes(resolution),
        "duplicate_timestamp_count": duplicate_count,
        "first_timestamp_utc": unique["timestamps"].iloc[0].isoformat(),
        "last_timestamp_utc": unique["timestamps"].iloc[-1].isoformat(),
        "row_count": int(len(clean)),
        "requested_lookback": int(requested_lookback),
        "actual_lookback": actual_lookback,
        "selected_feature_columns": selected_feature_columns or [],
        "amount_available": bool(not amount_col.empty and amount_col.notna().any() and (amount_col.fillna(0).abs() > 1e-12).any()),
        "volume_available": bool(not volume_col.empty and volume_col.notna().any() and (volume_col.fillna(0).abs() > 1e-12).any()),
        "terminal_close": None if "close" not in unique.columns else float(pd.to_numeric(unique["close"], errors="coerce").iloc[-1]),
        "price_side": price_side,
        "resolution": resolution,
        "symbol": symbol,
        "gap_list": gaps,
    }


def evaluate_strict_input_policy(
    df: pd.DataFrame,
    *,
    resolution: str,
    requested_lookback: int,
    now_utc: pd.Timestamp | None = None,
    allow_short_lookback: bool = False,
    max_stale_intervals: int = 1,
    selected_feature_columns: list[str] | None = None,
    source_label: str | None = None,
    symbol: str | None = None,
    price_side: str | None = None,
) -> InputQualityDecision:
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.to_datetime(now_utc, utc=True)
    audit = input_window_audit(
        df,
        resolution=resolution,
        requested_lookback=requested_lookback,
        selected_feature_columns=selected_feature_columns,
        source_label=source_label,
        symbol=symbol,
        price_side=price_side,
    )
    minutes = expected_cadence_minutes(resolution)
    rejection_reasons: list[str] = []
    terminal_ts = pd.to_datetime(audit["last_timestamp_utc"], utc=True) if audit["last_timestamp_utc"] else None
    latest_closed = latest_closed_timestamp(now, resolution)
    if int(audit["missing_candle_count"]) != 0:
        rejection_reasons.append(f"missing_candle_count={audit['missing_candle_count']} must be 0")
    if int(audit["duplicate_timestamp_count"]) != 0:
        rejection_reasons.append(f"duplicate_timestamp_count={audit['duplicate_timestamp_count']} must be 0")
    largest_gap = int(audit["largest_gap_minutes"] or 0)
    if int(audit["actual_lookback"]) > 1 and largest_gap != minutes:
        rejection_reasons.append(f"largest_gap_minutes={largest_gap} must equal expected_gap_minutes={minutes}")
    if not allow_short_lookback and int(audit["actual_lookback"]) != int(requested_lookback):
        rejection_reasons.append(f"actual_lookback={audit['actual_lookback']} must equal requested_lookback={requested_lookback}")
    if terminal_ts is None:
        rejection_reasons.append("terminal candle is missing")
    else:
        if terminal_ts > latest_closed:
            rejection_reasons.append(
                f"terminal candle {terminal_ts.isoformat()} is not closed; latest_closed={latest_closed.isoformat()}"
            )
        stale_cutoff = latest_closed - pd.Timedelta(minutes=minutes * max(0, int(max_stale_intervals)))
        if terminal_ts < stale_cutoff:
            rejection_reasons.append(
                f"terminal candle {terminal_ts.isoformat()} is stale; stale_cutoff={stale_cutoff.isoformat()}"
            )
        if terminal_ts != terminal_ts.floor(f"{minutes}min"):
            rejection_reasons.append(f"terminal candle {terminal_ts.isoformat()} is not aligned to {minutes}-minute boundary")
    checks = {
        **audit,
        "latest_closed_timestamp_utc": latest_closed.isoformat(),
        "checked_at_utc": now.isoformat(),
        "allow_short_lookback": bool(allow_short_lookback),
        "max_stale_intervals": int(max_stale_intervals),
    }
    return InputQualityDecision(
        allow=not rejection_reasons,
        reason="input_quality_passed" if not rejection_reasons else "; ".join(rejection_reasons),
        checks=checks,
        rejection_reasons=rejection_reasons,
    )


def feature_mode_for_columns(feature_columns: list[str], *, amount_available: bool) -> str:
    if "amount" in feature_columns:
        return "OHLCVA_DERIVED_AMOUNT" if amount_available else "OHLCVA_UNAVAILABLE"
    if "volume" in feature_columns:
        return "OHLCV_ONLY"
    return "OHLC"


def _normalise_feature_mode(feature_set: str) -> str:
    key = str(feature_set or "auto").strip().lower().replace("-", "_")
    if key not in FEATURE_MODE_ALIASES:
        raise ValueError(f"Unsupported feature_set/feature_mode: {feature_set}")
    return FEATURE_MODE_ALIASES[key]


def _amount_is_available(df: pd.DataFrame) -> bool:
    amount_col = pd.to_numeric(df["amount"], errors="coerce") if "amount" in df.columns else pd.Series(dtype=float)
    return bool(not amount_col.empty and amount_col.notna().any() and (amount_col.fillna(0).abs() > 1e-12).any())


def _volume_is_available(df: pd.DataFrame) -> bool:
    volume_col = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(dtype=float)
    return bool(not volume_col.empty and volume_col.notna().any() and (volume_col.fillna(0).abs() > 1e-12).any())


def resolve_feature_experiment(df: pd.DataFrame, feature_set: str) -> FeatureExperimentSelection:
    """Select a leakage-safe experiment input mode without changing forecasting unless requested."""
    mode = _normalise_feature_mode(feature_set)
    prepared = df.copy()
    notes: list[str] = []
    amount_derivation_method: str | None = None
    regime_context_used = False
    model_input_compatible = True

    if mode == "AUTO":
        amount_available = _amount_is_available(prepared)
        feature_columns = select_feature_columns(prepared, "auto")
        return FeatureExperimentSelection(
            feature_mode=feature_mode_for_columns(feature_columns, amount_available=amount_available),
            feature_columns=feature_columns,
            dataframe=prepared,
            amount_available=amount_available,
            amount_derivation_method=None,
            regime_context_used=False,
            model_input_compatible=True,
            notes=["auto selected available OHLC columns without deriving amount"],
        )

    if mode == "OHLC":
        feature_columns = ["open", "high", "low", "close"]
    elif mode in {"OHLCV_ONLY", "OHLCV_WITH_REGIME_CONTEXT", "MULTI_TIMEFRAME_VALIDATION_ONLY"}:
        feature_columns = ["open", "high", "low", "close", "volume"]
        if mode == "OHLCV_WITH_REGIME_CONTEXT":
            regime_context_used = True
            notes.append("regime context is recorded for analysis; Kronos input remains OHLCV-compatible")
        if mode == "MULTI_TIMEFRAME_VALIDATION_ONLY":
            model_input_compatible = True
            notes.append("multi-timeframe context is validation-only; Kronos input remains OHLCV")
    elif mode == "OHLCVA_DERIVED_AMOUNT":
        if not _volume_is_available(prepared):
            raise ValueError("OHLCVA_DERIVED_AMOUNT requires meaningful non-null volume")
        close = pd.to_numeric(prepared["close"], errors="coerce")
        volume = pd.to_numeric(prepared["volume"], errors="coerce")
        derived_amount = close * volume
        if derived_amount.notna().sum() == 0 or not bool((derived_amount.fillna(0).abs() > 1e-12).any()):
            raise ValueError("OHLCVA_DERIVED_AMOUNT would produce all-zero/unavailable amount")
        prepared["amount"] = derived_amount
        feature_columns = ["open", "high", "low", "close", "volume", "amount"]
        amount_derivation_method = "close_x_volume"
        notes.append("amount derived as close * volume using current candle fields only")
    else:
        raise ValueError(f"Unsupported feature mode: {mode}")

    amount_available = _amount_is_available(prepared)
    return FeatureExperimentSelection(
        feature_mode=mode,
        feature_columns=feature_columns,
        dataframe=prepared,
        amount_available=amount_available,
        amount_derivation_method=amount_derivation_method,
        regime_context_used=regime_context_used,
        model_input_compatible=model_input_compatible,
        notes=notes,
    )


def select_feature_columns(df: pd.DataFrame, feature_set: str) -> list[str]:
    normalized = _normalise_feature_mode(feature_set)
    if normalized == "OHLC":
        return ["open", "high", "low", "close"]
    if normalized in {"OHLCV_ONLY", "OHLCV_WITH_REGIME_CONTEXT", "MULTI_TIMEFRAME_VALIDATION_ONLY"}:
        return ["open", "high", "low", "close", "volume"]
    if normalized == "OHLCVA_DERIVED_AMOUNT":
        return ["open", "high", "low", "close", "volume", "amount"]
    if feature_set == "ohlc":
        return ["open", "high", "low", "close"]
    if feature_set == "ohlcv":
        return ["open", "high", "low", "close", "volume"]
    if feature_set == "ohlcva":
        return ["open", "high", "low", "close", "volume", "amount"]
    amount_col = pd.to_numeric(df["amount"], errors="coerce") if "amount" in df.columns else pd.Series(dtype=float)
    volume_col = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else pd.Series(dtype=float)
    amount_is_unavailable = bool(amount_col.empty or amount_col.isna().all() or (amount_col.fillna(0).abs() < 1e-12).all())
    volume_is_available = bool(not volume_col.empty and volume_col.notna().any() and (volume_col.fillna(0).abs() > 1e-12).any())
    if amount_is_unavailable and volume_is_available:
        return ["open", "high", "low", "close", "volume"]
    if amount_is_unavailable:
        return ["open", "high", "low", "close"]
    return ["open", "high", "low", "close", "volume", "amount"]
