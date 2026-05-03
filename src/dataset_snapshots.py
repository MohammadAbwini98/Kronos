from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from data_quality import analyze_ohlcv_quality
from db import connect


VALID_DATASET_ROLES = {"train", "validation", "shadow_eval", "promotion_eval", "backtest"}


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _checksum(df: pd.DataFrame, config: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(_canonical_json(config).encode("utf-8"))
    if not df.empty:
        csv_text = df.to_csv(index=False, lineterminator="\n")
        digest.update(csv_text.encode("utf-8"))
    return digest.hexdigest()


def _dataset_id(symbol: str, resolution: str, role: str, checksum: str) -> str:
    token = uuid.uuid5(uuid.NAMESPACE_URL, f"{symbol}:{resolution}:{role}:{checksum}").hex[:16]
    return f"dataset-{token}"


def _apply_quality_filter(
    df: pd.DataFrame,
    quality_filter: dict[str, Any] | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Apply row-level quality constraints defined in *quality_filter* and return the
    filtered DataFrame together with a report of what was removed.

    Supported keys
    --------------
    drop_null_ohlc (bool, default True)
        Remove rows where any of open/high/low/close is NULL.
    drop_invalid_ohlc (bool, default True)
        Remove rows that violate basic OHLC invariants (high < max(o,c) or low > min(o,c)).
    allowed_sources (list[str] | None)
        Already applied at DB query time by *load_dataset_candles*; re-applied here
        so that programmatically constructed DataFrames are also filtered.
    min_rows (int | None)
        Raise ValueError if the filtered dataset has fewer rows than this value.
    """
    qf = quality_filter or {}
    if df.empty:
        return df, {"filter_applied": bool(qf), "rows_before": 0, "rows_after": 0, "removed": 0, "removal_reasons": {}}

    rows_before = len(df)
    mask = pd.Series(True, index=df.index)
    reasons: dict[str, int] = {}

    # --- allowed_sources re-check ---
    allowed_sources = qf.get("allowed_sources")
    if allowed_sources and "source" in df.columns:
        valid = df["source"].isin(list(allowed_sources))
        n = int((~valid).sum())
        if n:
            reasons["source_not_allowed"] = n
        mask &= valid

    # --- drop_null_ohlc (default True) ---
    if qf.get("drop_null_ohlc", True):
        ohlc_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        if ohlc_cols:
            null_rows = df[ohlc_cols].isna().any(axis=1)
            n = int(null_rows.sum())
            if n:
                reasons["null_ohlc"] = n
            mask &= ~null_rows

    # --- drop_invalid_ohlc (default True) ---
    if qf.get("drop_invalid_ohlc", True):
        required = {"open", "high", "low", "close"}
        if required.issubset(df.columns):
            prices = df[list(required)].apply(pd.to_numeric, errors="coerce")
            invalid = (
                prices["high"] < prices[["open", "low", "close"]].max(axis=1)
            ) | (
                prices["low"] > prices[["open", "high", "close"]].min(axis=1)
            )
            n = int(invalid.sum())
            if n:
                reasons["invalid_ohlc"] = n
            mask &= ~invalid

    filtered = df[mask].reset_index(drop=True)
    rows_after = len(filtered)

    min_rows = qf.get("min_rows")
    if min_rows is not None and rows_after < int(min_rows):
        raise ValueError(
            f"Quality filter reduced dataset from {rows_before} to {rows_after} rows, "
            f"below the configured minimum of {min_rows}."
        )

    return filtered, {
        "filter_applied": bool(qf),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "removed": rows_before - rows_after,
        "removal_reasons": reasons,
    }


def load_dataset_candles(
    *,
    symbol: str,
    resolution: str,
    price_side: str,
    start_timestamp_utc: str,
    end_timestamp_utc: str,
    source_filter: dict[str, Any] | None = None,
    dsn: str | None = None,
) -> pd.DataFrame:
    where = [
        "symbol = %s",
        "resolution = %s",
        "price_side = %s",
        "timestamp_utc >= %s",
        "timestamp_utc <= %s",
    ]
    params: list[Any] = [symbol, resolution, price_side, start_timestamp_utc, end_timestamp_utc]
    allowed_sources = (source_filter or {}).get("allowed_sources")
    if allowed_sources:
        where.append("source = ANY(%s)")
        params.append(list(allowed_sources))
    with connect(dsn) as conn:
        rows = conn.execute(
            f"""
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount, source
            FROM ohlcv_candles
            WHERE {' AND '.join(where)}
            ORDER BY timestamp_utc ASC
            """,
            tuple(params),
        ).fetchall()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    return df


def create_dataset_snapshot(
    *,
    dataset_role: str,
    symbol: str,
    resolution: str,
    price_side: str = "mid",
    start_timestamp_utc: str,
    end_timestamp_utc: str,
    feature_set_id: str | None = "raw-ohlcv-v1",
    source_filter: dict[str, Any] | None = None,
    quality_filter: dict[str, Any] | None = None,
    output_dir: str | Path = "output/datasets",
    dsn: str | None = None,
) -> dict[str, Any]:
    role = str(dataset_role).strip()
    if role not in VALID_DATASET_ROLES:
        raise ValueError(f"Unsupported dataset_role: {dataset_role}")
    df = load_dataset_candles(
        symbol=symbol,
        resolution=resolution,
        price_side=price_side,
        start_timestamp_utc=start_timestamp_utc,
        end_timestamp_utc=end_timestamp_utc,
        source_filter=source_filter,
        dsn=dsn,
    )
    df, filter_result = _apply_quality_filter(df, quality_filter)
    quality = analyze_ohlcv_quality(df, resolution=resolution, expected_rows=max(1, len(df)))
    missing = int(quality.missing_candle_count)
    config = {
        "dataset_role": role,
        "symbol": symbol,
        "resolution": resolution,
        "price_side": price_side,
        "start_timestamp_utc": pd.to_datetime(start_timestamp_utc, utc=True).isoformat(),
        "end_timestamp_utc": pd.to_datetime(end_timestamp_utc, utc=True).isoformat(),
        "feature_set_id": feature_set_id,
        "source_filter": source_filter or {},
        "quality_filter": quality_filter or {},
    }
    checksum = _checksum(df, config)
    dataset_id = _dataset_id(symbol, resolution, role, checksum)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / f"{dataset_id}.csv"
    df.to_csv(artifact_path, index=False)
    metadata = {"quality": quality.to_dict(), "config": config, "filter_result": filter_result}
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO dataset_snapshots(
                dataset_id, dataset_role, symbol, resolution, price_side, feature_set_id,
                start_timestamp_utc, end_timestamp_utc, row_count, missing_candle_count,
                source_filter, quality_filter, checksum, artifact_path, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(symbol, resolution, price_side, dataset_role, start_timestamp_utc, end_timestamp_utc, checksum)
            DO UPDATE SET artifact_path = EXCLUDED.artifact_path,
                          metadata = EXCLUDED.metadata
            """,
            (
                dataset_id,
                role,
                symbol,
                resolution,
                price_side,
                feature_set_id,
                config["start_timestamp_utc"],
                config["end_timestamp_utc"],
                int(len(df)),
                missing,
                Jsonb(source_filter or {}),
                Jsonb(quality_filter or {}),
                checksum,
                str(artifact_path),
                Jsonb(metadata),
            ),
        )
    return {
        "dataset_id": dataset_id,
        "row_count": int(len(df)),
        "checksum": checksum,
        "artifact_path": str(artifact_path),
        "missing_candle_count": missing,
        "quality": quality.to_dict(),
    }


def dataset_windows_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_start = pd.to_datetime(a["start_timestamp_utc"], utc=True)
    a_end = pd.to_datetime(a["end_timestamp_utc"], utc=True)
    b_start = pd.to_datetime(b["start_timestamp_utc"], utc=True)
    b_end = pd.to_datetime(b["end_timestamp_utc"], utc=True)
    return a_start <= b_end and b_start <= a_end


def load_dataset_snapshot(dataset_id: str, *, dsn: str | None = None) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        row = conn.execute("SELECT * FROM dataset_snapshots WHERE dataset_id = %s", (dataset_id,)).fetchone()
    return dict(row) if row else None
