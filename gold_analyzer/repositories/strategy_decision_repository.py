from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from gold_analyzer.db.repositories._base import Repository
from gold_analyzer.repositories._json_safe import finite_or_none, sanitize_json
from gold_analyzer.strategy_brain.decision import StrategyDecision


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS strategy_decisions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal TEXT NOT NULL,
    strategy_type TEXT,
    regime TEXT,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    take_profit_1 DOUBLE PRECISION,
    take_profit_2 DOUBLE PRECISION,
    position_size DOUBLE PRECISION,
    risk_reward_1 DOUBLE PRECISION,
    risk_reward_2 DOUBLE PRECISION,
    strategy_score DOUBLE PRECISION,
    ai_support_score DOUBLE PRECISION,
    risk_score DOUBLE PRECISION,
    final_score DOUBLE PRECISION,
    decision_status TEXT NOT NULL,
    reason TEXT,
    blocked_by JSONB,
    indicators_json JSONB,
    ai_json JSONB,
    risk_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_strategy_decisions_symbol_tf_time
    ON strategy_decisions(symbol, timeframe, computed_at DESC);
"""


class StrategyDecisionRepository(Repository):
    CREATE_TABLE_SQL = CREATE_TABLE_SQL

    @classmethod
    def creation_sql(cls) -> str:
        return cls.CREATE_TABLE_SQL

    def ensure_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(self.CREATE_TABLE_SQL)

    def save(self, decision: StrategyDecision) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO strategy_decisions(
                    symbol, timeframe, computed_at, signal, strategy_type, regime,
                    entry_price, stop_loss, take_profit_1, take_profit_2,
                    position_size, risk_reward_1, risk_reward_2,
                    strategy_score, ai_support_score, risk_score, final_score,
                    decision_status, reason, blocked_by, indicators_json, ai_json, risk_json
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    decision.symbol,
                    decision.timeframe,
                    decision.computed_at,
                    decision.signal,
                    decision.strategy_type,
                    decision.regime,
                    finite_or_none(decision.entry_price),
                    finite_or_none(decision.stop_loss),
                    finite_or_none(decision.take_profit_1),
                    finite_or_none(decision.take_profit_2),
                    finite_or_none(decision.position_size),
                    finite_or_none(decision.risk_reward_1),
                    finite_or_none(decision.risk_reward_2),
                    finite_or_none(decision.strategy_score),
                    finite_or_none(decision.ai_support_score),
                    finite_or_none(decision.risk_score),
                    finite_or_none(decision.final_score),
                    decision.decision_status,
                    decision.reason,
                    Jsonb(sanitize_json(decision.blocked_by or [])),
                    Jsonb(sanitize_json(decision.indicators or {})),
                    Jsonb(sanitize_json(decision.ai_details or {})),
                    Jsonb(sanitize_json(decision.risk_details or {})),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def list_latest(self, *, symbol: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_decisions
                WHERE (%s::text IS NULL OR symbol = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY computed_at DESC, id DESC
                LIMIT %s
                """,
                (symbol, symbol, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}