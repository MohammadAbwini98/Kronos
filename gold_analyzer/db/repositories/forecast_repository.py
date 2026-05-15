from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from gold_analyzer.forecasting.ensemble import EnsemblePoint
from gold_analyzer.models.outputs import ForecastResult

from ._base import Repository


class ForecastRepository(Repository):
    def save_result(self, result: ForecastResult) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO forecast_runs(
                    model_key, model_version, epic, timeframe, input_start_ts, input_end_ts,
                    horizon_bars, status, latency_ms, error_message, raw_json
                )
                VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    result.model_key,
                    result.model_version,
                    result.epic,
                    result.timeframe,
                    len(result.points),
                    result.status,
                    int(result.latency_ms),
                    result.error_message,
                    Jsonb(result.raw or {}),
                ),
            ).fetchone()
            run_id = int(row["id"] if isinstance(row, dict) else row[0])
            for point in result.points:
                conn.execute(
                    """
                    INSERT INTO forecasts(
                        run_id, model_key, epic, timeframe, forecast_for_ts, horizon_bar,
                        predicted_close, predicted_return, predicted_direction,
                        lower_bound, upper_bound, confidence, raw_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        result.model_key,
                        result.epic,
                        result.timeframe,
                        point.forecast_for_ts,
                        int(point.horizon_bar),
                        point.predicted_close,
                        point.predicted_return,
                        point.predicted_direction,
                        point.lower_bound,
                        point.upper_bound,
                        point.confidence,
                        Jsonb(point.raw or {}),
                    ),
                )
            return run_id

    def save_ensemble(self, points: list[EnsemblePoint]) -> int:
        saved = 0
        with self.connect() as conn:
            for point in points:
                conn.execute(
                    """
                    INSERT INTO ensemble_forecasts(
                        epic, timeframe, forecast_for_ts, horizon_bar, ensemble_return,
                        ensemble_direction, agreement_score, dispersion_score, confidence, model_votes_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        point.epic,
                        point.timeframe,
                        point.forecast_for_ts,
                        int(point.horizon_bar),
                        point.ensemble_return,
                        point.ensemble_direction,
                        point.agreement_score,
                        point.dispersion_score,
                        point.confidence,
                        Jsonb(point.model_votes or {}),
                    ),
                )
                saved += 1
        return saved

    def list_forecasts(self, *, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            runs = conn.execute(
                """
                SELECT *
                FROM forecast_runs
                WHERE (%s::text IS NULL OR epic = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
            points = conn.execute(
                """
                SELECT f.*
                FROM forecasts f
                JOIN forecast_runs r ON r.id = f.run_id
                WHERE (%s::text IS NULL OR f.epic = %s)
                  AND (%s::text IS NULL OR f.timeframe = %s)
                ORDER BY f.forecast_for_ts DESC, f.created_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"runs": [dict(row) for row in runs], "forecasts": [dict(row) for row in points]}

    def list_ensemble(self, *, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ensemble_forecasts
                WHERE (%s::text IS NULL OR epic = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY forecast_for_ts DESC, created_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}
