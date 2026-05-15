from __future__ import annotations

import pandas as pd

from gold_analyzer._compat import ensure_legacy_src_path


def load_recent_candles(epic: str, timeframe: str, limit: int = 512, *, dsn: str | None = None) -> pd.DataFrame:
    """Load recent candles from the existing ``ohlcv_candles`` table."""

    ensure_legacy_src_path()
    from db import connect

    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount, source
            FROM ohlcv_candles
            WHERE (epic = %s OR symbol = %s)
              AND resolution = %s
            ORDER BY timestamp_utc DESC
            LIMIT %s
            """,
            (epic, epic, timeframe, max(1, int(limit))),
        ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        return frame
    frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True)
    return frame.sort_values("timestamps").reset_index(drop=True)
