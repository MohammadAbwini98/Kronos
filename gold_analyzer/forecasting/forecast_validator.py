from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = ("timestamps", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class QualityReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def validate_candles(candles: pd.DataFrame, *, min_rows: int = 32) -> QualityReport:
    errors: list[str] = []
    if candles is None or candles.empty:
        return QualityReport(ok=False, errors=["No candles available."], details={"row_count": 0})
    missing = [column for column in REQUIRED_COLUMNS if column not in candles.columns]
    if missing:
        errors.append(f"Missing columns: {', '.join(missing)}")
    frame = candles.copy()
    if "timestamps" in frame.columns:
        ts = pd.to_datetime(frame["timestamps"], utc=True, errors="coerce")
        if ts.isna().any():
            errors.append("Timestamps contain null or invalid values.")
        elif not ts.is_monotonic_increasing:
            errors.append("Timestamps must be sorted ascending.")
        if ts.duplicated().any():
            errors.append("Duplicate timestamps found.")
    numeric_cols = [col for col in ("open", "high", "low", "close", "volume") if col in frame.columns]
    for column in numeric_cols:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            errors.append(f"Column {column} contains null or non-numeric values.")
    if len(frame) < int(min_rows):
        errors.append(f"Not enough candles: {len(frame)}/{int(min_rows)}")
    return QualityReport(
        ok=not errors,
        errors=errors,
        details={"row_count": int(len(frame)), "min_rows": int(min_rows)},
    )
