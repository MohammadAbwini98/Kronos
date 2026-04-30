from __future__ import annotations

from typing import Any

from db import connect, healthcheck
from prediction_store import prediction_summary


def postgres_dashboard_snapshot(*, symbol: str = "ETHUSD", resolution: str = "MINUTE_5", dsn: str | None = None) -> dict[str, Any]:
    health = healthcheck(dsn)
    if not health["ok"]:
        return {"postgres": health}
    with connect(dsn) as conn:
        candles = conn.execute(
            """
            SELECT timestamp_utc, open, high, low, close, volume
            FROM ohlcv_candles
            WHERE symbol = %s AND resolution = %s
            ORDER BY timestamp_utc DESC
            LIMIT 120
            """,
            (symbol, resolution),
        ).fetchall()
        signals = conn.execute(
            """
            SELECT s.*, r.forecast_start_timestamp_utc, r.forecast_end_timestamp_utc, r.run_status
            FROM signals s
            JOIN prediction_runs r ON r.run_id = s.run_id
            WHERE s.symbol = %s AND s.resolution = %s
            ORDER BY s.timestamp_utc DESC
            LIMIT 20
            """,
            (symbol, resolution),
        ).fetchall()
        outcomes = conn.execute(
            """
            SELECT o.status, count(*)::int AS count
            FROM prediction_outcomes o
            JOIN prediction_runs r ON r.run_id = o.run_id
            WHERE r.symbol = %s AND r.resolution = %s
            GROUP BY o.status
            """,
            (symbol, resolution),
        ).fetchall()
        heartbeats = conn.execute(
            "SELECT service_name, status, details, updated_at FROM service_heartbeats ORDER BY service_name"
        ).fetchall()
    return {
        "postgres": health,
        "candles": [dict(row) for row in reversed(candles)],
        "signals": [dict(row) for row in signals],
        "outcomes": [dict(row) for row in outcomes],
        "heartbeats": [dict(row) for row in heartbeats],
        "prediction_db": prediction_summary(dsn, limit=20),
    }
