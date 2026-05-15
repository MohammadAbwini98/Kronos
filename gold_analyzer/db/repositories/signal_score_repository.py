from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from ._base import Repository


class SignalScoreRepository(Repository):
    def save_score(self, score: dict[str, Any]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO signal_scores(
                    epic, timeframe, candidate_signal, probability_win, probability_loss,
                    expected_return, model_agreement, risk_score, scorer_model, features_json, decision
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    score["epic"],
                    score["timeframe"],
                    score["candidate_signal"],
                    score.get("probability_win"),
                    score.get("probability_loss"),
                    score.get("expected_return"),
                    score.get("model_agreement"),
                    score.get("risk_score"),
                    score.get("scorer_model"),
                    Jsonb(score.get("features") or {}),
                    score.get("decision"),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def list_scores(self, *, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM signal_scores
                WHERE (%s::text IS NULL OR epic = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY computed_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}
