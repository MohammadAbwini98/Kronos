from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from gold_analyzer.db.repositories._base import Repository
from gold_analyzer.repositories._json_safe import finite_or_none, int_or_none, sanitize_json


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_performance (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy_type TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_trades INTEGER,
    win_rate DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    expectancy DOUBLE PRECISION,
    avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    sharpe DOUBLE PRECISION,
    details_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_symbol_tf_time
    ON strategy_performance(symbol, timeframe, evaluated_at DESC);
"""


class StrategyPerformanceRepository(Repository):
    CREATE_TABLE_SQL = CREATE_TABLE_SQL

    @classmethod
    def creation_sql(cls) -> str:
        return cls.CREATE_TABLE_SQL

    def ensure_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(self.CREATE_TABLE_SQL)

    def save_summary(self, summary: dict[str, Any]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO strategy_performance(
                    symbol, timeframe, strategy_type, lookback_trades,
                    win_rate, profit_factor, expectancy, avg_win, avg_loss,
                    max_drawdown, sharpe, details_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    summary["symbol"],
                    summary["timeframe"],
                    summary.get("strategy_type"),
                    int_or_none(summary.get("lookback_trades")),
                    finite_or_none(summary.get("win_rate")),
                    finite_or_none(summary.get("profit_factor")),
                    finite_or_none(summary.get("expectancy")),
                    finite_or_none(summary.get("avg_win")),
                    finite_or_none(summary.get("avg_loss")),
                    finite_or_none(summary.get("max_drawdown")),
                    finite_or_none(summary.get("sharpe")),
                    Jsonb(sanitize_json(summary.get("details") or summary.get("details_json") or {})),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def list_latest(self, *, symbol: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_performance
                WHERE (%s::text IS NULL OR symbol = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY evaluated_at DESC, id DESC
                LIMIT %s
                """,
                (symbol, symbol, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}