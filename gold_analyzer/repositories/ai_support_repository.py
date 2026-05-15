from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from gold_analyzer.ai_support.models import AISupportResult
from gold_analyzer.db.repositories._base import Repository
from gold_analyzer.repositories._json_safe import finite_or_none, int_or_none, sanitize_json


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ai_support_evaluations (
    id BIGSERIAL PRIMARY KEY,
    strategy_decision_id BIGINT REFERENCES strategy_decisions(id),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    model_key TEXT NOT NULL,
    model_status TEXT NOT NULL,
    candidate_signal TEXT NOT NULL,
    predicted_return DOUBLE PRECISION,
    predicted_direction TEXT,
    support_value DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    latency_ms INTEGER,
    raw_json JSONB,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_support_eval_decision_time
    ON ai_support_evaluations(strategy_decision_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_support_eval_symbol_tf_time
    ON ai_support_evaluations(symbol, timeframe, computed_at DESC);
"""


class AISupportRepository(Repository):
    CREATE_TABLE_SQL = CREATE_TABLE_SQL

    @classmethod
    def creation_sql(cls) -> str:
        return cls.CREATE_TABLE_SQL

    def ensure_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(self.CREATE_TABLE_SQL)

    def save_result(
        self,
        *,
        decision_id: int | None,
        symbol: str,
        timeframe: str,
        result: AISupportResult,
    ) -> int:
        evaluations = list(result.evaluations or [])
        if not evaluations:
            evaluations = [
                {
                    "model_key": "round1_placeholder",
                    "model_status": result.status,
                    "candidate_signal": result.candidate_signal or "NO_CANDIDATE",
                    "predicted_return": None,
                    "predicted_direction": result.candidate_signal,
                    "support_value": result.support_value,
                    "confidence": result.confidence,
                    "latency_ms": None,
                    "raw_json": dict(result.details or {}),
                    "error_message": result.reason,
                }
            ]

        saved = 0
        with self.connect() as conn:
            for evaluation in evaluations:
                conn.execute(
                    """
                    INSERT INTO ai_support_evaluations(
                        strategy_decision_id, symbol, timeframe, model_key, model_status,
                        candidate_signal, predicted_return, predicted_direction, support_value,
                        confidence, latency_ms, raw_json, error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        decision_id,
                        symbol,
                        timeframe,
                        evaluation.get("model_key") or "round1_placeholder",
                        evaluation.get("model_status") or result.status,
                        evaluation.get("candidate_signal") or result.candidate_signal or "NO_CANDIDATE",
                        finite_or_none(evaluation.get("predicted_return")),
                        evaluation.get("predicted_direction"),
                        finite_or_none(evaluation.get("support_value", result.support_value)),
                        finite_or_none(evaluation.get("confidence", result.confidence)),
                        int_or_none(evaluation.get("latency_ms")),
                        Jsonb(sanitize_json(evaluation.get("raw_json") or evaluation.get("raw") or {})),
                        evaluation.get("error_message") or result.reason,
                    ),
                )
                saved += 1
        return saved

    def list_for_decision(self, decision_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_support_evaluations
                WHERE strategy_decision_id = %s
                ORDER BY computed_at DESC, id DESC
                """,
                (int(decision_id),),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}