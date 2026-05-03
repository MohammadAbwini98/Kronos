from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect


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

GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


@dataclass(frozen=True)
class DataQualityReport:
    quality_grade: str
    quality_score: float
    lookback_rows_expected: int
    lookback_rows_actual: int
    missing_candle_count: int
    duplicate_timestamp_count: int
    largest_gap_minutes: int
    stale_live_price_seconds: int | None
    ohlc_repair_count: int
    volume_available: bool
    amount_available: bool
    source_counts: dict[str, int]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_grade": self.quality_grade,
            "quality_score": self.quality_score,
            "lookback_rows_expected": self.lookback_rows_expected,
            "lookback_rows_actual": self.lookback_rows_actual,
            "missing_candle_count": self.missing_candle_count,
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "largest_gap_minutes": self.largest_gap_minutes,
            "stale_live_price_seconds": self.stale_live_price_seconds,
            "ohlc_repair_count": self.ohlc_repair_count,
            "volume_available": self.volume_available,
            "amount_available": self.amount_available,
            "source_counts": self.source_counts,
            "warnings": self.warnings,
        }


def grade_meets_minimum(grade: str | None, minimum_grade: str | None) -> bool:
    if not minimum_grade:
        return True
    return GRADE_ORDER.get(str(grade or "F").upper(), 0) >= GRADE_ORDER.get(str(minimum_grade).upper(), 0)


def analyze_ohlcv_quality(
    df: pd.DataFrame,
    *,
    resolution: str,
    expected_rows: int,
    stale_live_price_seconds: int | None = None,
    ohlc_repair_count: int = 0,
) -> DataQualityReport:
    clean = df.copy()
    warnings: list[str] = []
    if clean.empty:
        return DataQualityReport(
            quality_grade="F",
            quality_score=0.0,
            lookback_rows_expected=max(0, int(expected_rows)),
            lookback_rows_actual=0,
            missing_candle_count=max(0, int(expected_rows)),
            duplicate_timestamp_count=0,
            largest_gap_minutes=0,
            stale_live_price_seconds=stale_live_price_seconds,
            ohlc_repair_count=int(ohlc_repair_count),
            volume_available=False,
            amount_available=False,
            source_counts={},
            warnings=["empty_lookback_window"],
        )
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    clean = clean.sort_values("timestamps").reset_index(drop=True)
    duplicate_count = int(clean["timestamps"].duplicated().sum())
    unique = clean.drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    actual_rows = int(len(unique))
    resolution_minutes = RESOLUTION_MINUTES.get(str(resolution).upper(), 5)
    diffs = unique["timestamps"].diff().dropna().dt.total_seconds().div(60)
    largest_gap_minutes = int(diffs.max()) if not diffs.empty else 0
    gap_missing = int(sum(max(0, round(float(value) / resolution_minutes) - 1) for value in diffs))
    missing_count = max(0, max(int(expected_rows) - actual_rows, gap_missing))
    source_counts: dict[str, int] = {}
    if "source" in unique.columns:
        source_counts = {str(key): int(value) for key, value in unique["source"].fillna("unknown").value_counts().to_dict().items()}
    volume_available = bool("volume" in unique.columns and unique["volume"].fillna(0).astype(float).abs().sum() > 0)
    amount_available = bool("amount" in unique.columns and unique["amount"].fillna(0).astype(float).abs().sum() > 0)
    ohlc_invalid = 0
    if {"open", "high", "low", "close"}.issubset(unique.columns):
        prices = unique[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        invalid = (
            prices.isna().any(axis=1)
            | (prices["high"] < prices[["open", "low", "close"]].max(axis=1))
            | (prices["low"] > prices[["open", "high", "close"]].min(axis=1))
        )
        ohlc_invalid = int(invalid.sum())
    if duplicate_count:
        warnings.append(f"duplicate_timestamps:{duplicate_count}")
    if missing_count:
        warnings.append(f"missing_candles:{missing_count}")
    if largest_gap_minutes > resolution_minutes:
        warnings.append(f"largest_gap_minutes:{largest_gap_minutes}")
    if ohlc_invalid:
        warnings.append(f"ohlc_invalid:{ohlc_invalid}")
    if stale_live_price_seconds is not None and stale_live_price_seconds > resolution_minutes * 60 * 2:
        warnings.append(f"stale_live_price_seconds:{stale_live_price_seconds}")

    denominator = max(1, int(expected_rows))
    missing_penalty = min(45.0, (missing_count / denominator) * 100.0)
    duplicate_penalty = min(20.0, (duplicate_count / denominator) * 100.0)
    ohlc_penalty = min(25.0, ((ohlc_invalid + int(ohlc_repair_count)) / denominator) * 100.0)
    stale_penalty = 0.0 if stale_live_price_seconds is None else min(10.0, stale_live_price_seconds / max(60, resolution_minutes * 60))
    score = max(0.0, 100.0 - missing_penalty - duplicate_penalty - ohlc_penalty - stale_penalty)
    if score >= 95:
        grade = "A"
    elif score >= 85:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 50:
        grade = "D"
    else:
        grade = "F"
    return DataQualityReport(
        quality_grade=grade,
        quality_score=round(score / 100.0, 8),
        lookback_rows_expected=max(0, int(expected_rows)),
        lookback_rows_actual=actual_rows,
        missing_candle_count=missing_count,
        duplicate_timestamp_count=duplicate_count,
        largest_gap_minutes=largest_gap_minutes,
        stale_live_price_seconds=stale_live_price_seconds,
        ohlc_repair_count=int(ohlc_repair_count),
        volume_available=volume_available,
        amount_available=amount_available,
        source_counts=source_counts,
        warnings=warnings,
    )


def persist_prediction_run_quality(run_id: str, report: DataQualityReport | dict[str, Any], *, dsn: str | None = None) -> None:
    data = report.to_dict() if isinstance(report, DataQualityReport) else dict(report)
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO prediction_run_quality(
                run_id, quality_grade, quality_score, lookback_rows_expected, lookback_rows_actual,
                missing_candle_count, duplicate_timestamp_count, largest_gap_minutes, stale_live_price_seconds,
                ohlc_repair_count, volume_available, amount_available, source_counts, warnings, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT(run_id) DO UPDATE SET
                quality_grade = EXCLUDED.quality_grade,
                quality_score = EXCLUDED.quality_score,
                lookback_rows_expected = EXCLUDED.lookback_rows_expected,
                lookback_rows_actual = EXCLUDED.lookback_rows_actual,
                missing_candle_count = EXCLUDED.missing_candle_count,
                duplicate_timestamp_count = EXCLUDED.duplicate_timestamp_count,
                largest_gap_minutes = EXCLUDED.largest_gap_minutes,
                stale_live_price_seconds = EXCLUDED.stale_live_price_seconds,
                ohlc_repair_count = EXCLUDED.ohlc_repair_count,
                volume_available = EXCLUDED.volume_available,
                amount_available = EXCLUDED.amount_available,
                source_counts = EXCLUDED.source_counts,
                warnings = EXCLUDED.warnings,
                updated_at = now()
            """,
            (
                run_id,
                data["quality_grade"],
                float(data["quality_score"]),
                int(data["lookback_rows_expected"]),
                int(data["lookback_rows_actual"]),
                int(data.get("missing_candle_count") or 0),
                int(data.get("duplicate_timestamp_count") or 0),
                int(data.get("largest_gap_minutes") or 0),
                data.get("stale_live_price_seconds"),
                int(data.get("ohlc_repair_count") or 0),
                bool(data.get("volume_available")),
                bool(data.get("amount_available")),
                Jsonb(data.get("source_counts") or {}),
                Jsonb(data.get("warnings") or []),
            ),
        )
        conn.execute(
            "UPDATE prediction_runs SET data_quality_grade = %s, updated_at = now() WHERE run_id = %s",
            (data["quality_grade"], run_id),
        )
        conn.execute(
            "UPDATE signals SET quality_grade = %s, updated_at = now() WHERE run_id = %s",
            (data["quality_grade"], run_id),
        )
