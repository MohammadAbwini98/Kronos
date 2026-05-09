from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from db import connect


REQUIRED_CANDLE_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]

RESOLUTION_TO_DELTA = {
    "MINUTE": pd.Timedelta(minutes=1),
    "MINUTE_5": pd.Timedelta(minutes=5),
    "MINUTE_15": pd.Timedelta(minutes=15),
    "MINUTE_30": pd.Timedelta(minutes=30),
    "HOUR": pd.Timedelta(hours=1),
    "HOUR_4": pd.Timedelta(hours=4),
    "DAY": pd.Timedelta(days=1),
    "WEEK": pd.Timedelta(weeks=1),
}


def resolution_to_timedelta(resolution: str) -> pd.Timedelta:
    key = str(resolution or "").strip().upper()
    if key not in RESOLUTION_TO_DELTA:
        raise ValueError(f"Unsupported resolution: {resolution}")
    return RESOLUTION_TO_DELTA[key]


def load_recent_candles(
    symbol: str,
    resolution: str,
    price_side: str = "mid",
    limit: int = 512,
    dsn: str | None = None,
) -> pd.DataFrame:
    rows_limit = max(1, int(limit))
    res = str(resolution).strip().upper()
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT
                timestamp_utc AS timestamps,
                open,
                high,
                low,
                close,
                volume,
                amount
            FROM ohlcv_candles
            WHERE symbol = %s
              AND resolution = %s
              AND price_side = %s
            ORDER BY timestamp_utc DESC
            LIMIT %s
            """,
            (symbol, res, price_side, rows_limit),
        ).fetchall()

    frame = pd.DataFrame(rows, columns=REQUIRED_CANDLE_COLUMNS)
    if frame.empty:
        return frame

    frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True, errors="coerce")
    for column in REQUIRED_CANDLE_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["timestamps"]).sort_values("timestamps")
    frame = frame.drop_duplicates(subset=["timestamps"], keep="last").reset_index(drop=True)
    return frame


def _finite_mask(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    array = np.isfinite(df[columns].to_numpy(dtype=float))
    return pd.Series(array.all(axis=1), index=df.index)


def validate_candle_frame(df: pd.DataFrame, resolution: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "resolution": str(resolution).upper(),
        "row_count": int(len(df.index)) if isinstance(df, pd.DataFrame) else 0,
        "errors": [],
        "warnings": [],
        "cadence_ok": True,
        "cadence_mismatch_count": 0,
    }

    if not isinstance(df, pd.DataFrame):
        result["ok"] = False
        result["errors"].append("Input is not a pandas DataFrame.")
        return result

    missing = [column for column in REQUIRED_CANDLE_COLUMNS if column not in df.columns]
    if missing:
        result["ok"] = False
        result["errors"].append(f"Missing required columns: {', '.join(missing)}")
        return result

    if df.empty:
        result["ok"] = False
        result["errors"].append("No candles available.")
        return result

    check = df.copy()
    check["timestamps"] = pd.to_datetime(check["timestamps"], utc=True, errors="coerce")
    if check["timestamps"].isna().any():
        result["ok"] = False
        result["errors"].append("One or more timestamps are invalid or non-UTC parseable.")

    ts_dtype = check["timestamps"].dtype
    is_utc_tz = isinstance(ts_dtype, pd.DatetimeTZDtype) and str(ts_dtype.tz) == "UTC"
    if not is_utc_tz:
        result["ok"] = False
        result["errors"].append("timestamps column is not timezone-aware UTC.")

    if check["timestamps"].duplicated().any():
        result["ok"] = False
        dup_count = int(check["timestamps"].duplicated().sum())
        result["errors"].append(f"Duplicate timestamps found: {dup_count}")

    if not check["timestamps"].is_monotonic_increasing:
        result["ok"] = False
        result["errors"].append("timestamps are not sorted ascending.")

    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for column in numeric_cols:
        check[column] = pd.to_numeric(check[column], errors="coerce")

    if check[numeric_cols].isna().any().any():
        result["ok"] = False
        result["errors"].append("Numeric candle columns contain null values.")

    finite_rows = _finite_mask(check, numeric_cols)
    if not finite_rows.all():
        result["ok"] = False
        bad_count = int((~finite_rows).sum())
        result["errors"].append(f"Numeric candle columns contain non-finite values in {bad_count} row(s).")

    ohlc_bad = (
        (check["high"] < check[["open", "close", "low"]].max(axis=1))
        | (check["low"] > check[["open", "close", "high"]].min(axis=1))
    )
    if ohlc_bad.any():
        result["ok"] = False
        result["errors"].append(f"OHLC invariant violated in {int(ohlc_bad.sum())} row(s).")

    if (check["volume"] < 0).any():
        result["ok"] = False
        result["errors"].append("Negative volume values found.")

    if (check["amount"] < 0).any():
        result["ok"] = False
        result["errors"].append("Negative amount values found.")

    try:
        cadence = resolution_to_timedelta(str(resolution).upper())
        deltas = check["timestamps"].diff().dropna()
        if not deltas.empty:
            mismatch = int((deltas != cadence).sum())
            result["cadence_mismatch_count"] = mismatch
            # Large lookback windows can contain a couple of upstream gaps without invalidating the run.
            allowed_mismatch = 2 if len(deltas.index) >= 120 else 0
            if mismatch > allowed_mismatch:
                result["ok"] = False
                result["cadence_ok"] = False
                result["errors"].append(
                    f"Cadence mismatch for {mismatch} interval(s), expected {cadence}."
                )
            elif mismatch > 0:
                result["warnings"].append(
                    f"Cadence mismatch for {mismatch} interval(s), tolerated for long-window context."
                )
    except ValueError:
        result["ok"] = False
        result["cadence_ok"] = False
        result["errors"].append(f"Unsupported resolution for cadence validation: {resolution}")

    return result
