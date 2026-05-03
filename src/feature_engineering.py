from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb

from db import connect


DEFAULT_FEATURE_SET_ID = "raw-ohlcv-v1"
DEFAULT_ENABLED_FEATURES = [
    "log_return",
    "body_pct",
    "range_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "rolling_volatility_12",
    "rolling_volatility_48",
    "rolling_volume_zscore_48",
    "trend_slope_12",
    "atr_pct_14",
    "hour_utc",
    "day_of_week",
    "session_label",
    "source_quality_score",
    "gap_from_previous_minutes",
]


def ensure_feature_set(*, dsn: str | None = None, feature_set_id: str = DEFAULT_FEATURE_SET_ID) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO market_feature_sets(feature_set_id, name, version, parameters, enabled_features)
            VALUES (%s, 'raw-ohlcv', 'v1', '{}'::jsonb, %s)
            ON CONFLICT(feature_set_id) DO NOTHING
            """,
            (feature_set_id, Jsonb(DEFAULT_ENABLED_FEATURES)),
        )


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.replace(0, np.nan)
    return numerator / denom


def _trend_slope(values: pd.Series) -> float:
    if values.isna().any() or len(values) < 2:
        return np.nan
    x = np.arange(len(values), dtype=float)
    y = values.to_numpy(dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _session_label(hour: int) -> str:
    if 0 <= hour < 8:
        return "ASIA"
    if 8 <= hour < 13:
        return "EUROPE"
    if 13 <= hour < 21:
        return "US"
    return "LATE_US"


def generate_features(df: pd.DataFrame, *, feature_set_id: str = DEFAULT_FEATURE_SET_ID) -> pd.DataFrame:
    required = {"timestamps", "open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Feature generation missing columns: {', '.join(missing)}")
    rows = df.copy()
    rows["timestamps"] = pd.to_datetime(rows["timestamps"], utc=True)
    rows = rows.sort_values("timestamps").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in rows.columns:
            rows[col] = pd.to_numeric(rows[col], errors="coerce")
    close = rows["close"]
    high = rows["high"]
    low = rows["low"]
    open_ = rows["open"]
    prev_close = close.shift(1)
    candle_range = (high - low).replace(0, np.nan)
    true_range = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    volume = rows["volume"] if "volume" in rows.columns else pd.Series(np.nan, index=rows.index)
    volume_mean = volume.rolling(48, min_periods=48).mean()
    volume_std = volume.rolling(48, min_periods=48).std()
    features = pd.DataFrame(
        {
            "candle_id": rows["id"] if "id" in rows.columns else pd.Series([None] * len(rows)),
            "feature_set_id": feature_set_id,
            "timestamps": rows["timestamps"],
            "log_return": np.log(_safe_div(close, prev_close)),
            "body_pct": _safe_div(close - open_, open_) * 100.0,
            "range_pct": _safe_div(high - low, open_) * 100.0,
            "upper_wick_pct": _safe_div(high - pd.concat([open_, close], axis=1).max(axis=1), candle_range) * 100.0,
            "lower_wick_pct": _safe_div(pd.concat([open_, close], axis=1).min(axis=1) - low, candle_range) * 100.0,
            "rolling_volatility_12": close.pct_change().rolling(12, min_periods=12).std() * 100.0,
            "rolling_volatility_48": close.pct_change().rolling(48, min_periods=48).std() * 100.0,
            "rolling_volume_zscore_48": _safe_div(volume - volume_mean, volume_std),
            "trend_slope_12": close.rolling(12, min_periods=12).apply(_trend_slope, raw=False),
            "atr_pct_14": _safe_div(true_range.rolling(14, min_periods=14).mean(), close) * 100.0,
            "hour_utc": rows["timestamps"].dt.hour,
            "day_of_week": rows["timestamps"].dt.dayofweek,
            "session_label": rows["timestamps"].dt.hour.apply(_session_label),
            "source_quality_score": 1.0,
            "gap_from_previous_minutes": rows["timestamps"].diff().dt.total_seconds().div(60),
        }
    )
    return features.replace({np.nan: None})


def load_candles_for_features(
    *,
    symbol: str,
    resolution: str,
    price_side: str = "mid",
    start_timestamp_utc: str | None = None,
    end_timestamp_utc: str | None = None,
    dsn: str | None = None,
) -> pd.DataFrame:
    where = ["symbol = %s", "resolution = %s", "price_side = %s"]
    params: list[Any] = [symbol, resolution, price_side]
    if start_timestamp_utc:
        where.append("timestamp_utc >= %s")
        params.append(start_timestamp_utc)
    if end_timestamp_utc:
        where.append("timestamp_utc <= %s")
        params.append(end_timestamp_utc)
    with connect(dsn) as conn:
        rows = conn.execute(
            f"""
            SELECT id, timestamp_utc AS timestamps, open, high, low, close, volume, amount, source
            FROM ohlcv_candles
            WHERE {' AND '.join(where)}
            ORDER BY timestamp_utc ASC
            """,
            tuple(params),
        ).fetchall()
    return pd.DataFrame(rows)


def upsert_features(features: pd.DataFrame, *, dsn: str | None = None) -> int:
    if features.empty:
        return 0
    ensure_feature_set(dsn=dsn, feature_set_id=str(features["feature_set_id"].iloc[0]))
    rows = []
    columns = [
        "candle_id",
        "feature_set_id",
        "log_return",
        "body_pct",
        "range_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "rolling_volatility_12",
        "rolling_volatility_48",
        "rolling_volume_zscore_48",
        "trend_slope_12",
        "atr_pct_14",
        "hour_utc",
        "day_of_week",
        "session_label",
        "source_quality_score",
        "gap_from_previous_minutes",
    ]
    for _, row in features.iterrows():
        if row.get("candle_id") is None or pd.isna(row.get("candle_id")):
            continue
        rows.append(tuple(None if pd.isna(row.get(col)) else row.get(col) for col in columns))
    if not rows:
        return 0
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{col} = EXCLUDED.{col}" for col in columns[2:])
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO ohlcv_features({', '.join(columns)}, updated_at)
                VALUES ({placeholders}, now())
                ON CONFLICT(candle_id, feature_set_id) DO UPDATE SET
                    {assignments},
                    updated_at = now()
                """,
                rows,
            )
    return len(rows)


def generate_and_persist_features(
    *,
    symbol: str,
    resolution: str,
    price_side: str = "mid",
    feature_set_id: str = DEFAULT_FEATURE_SET_ID,
    start_timestamp_utc: str | None = None,
    end_timestamp_utc: str | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    candles = load_candles_for_features(
        symbol=symbol,
        resolution=resolution,
        price_side=price_side,
        start_timestamp_utc=start_timestamp_utc,
        end_timestamp_utc=end_timestamp_utc,
        dsn=dsn,
    )
    features = generate_features(candles, feature_set_id=feature_set_id)
    saved = upsert_features(features, dsn=dsn)
    return {"feature_set_id": feature_set_id, "candles": int(len(candles)), "features_saved": int(saved)}
