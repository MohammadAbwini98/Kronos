from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from ._base import Repository


class ValidationRepository(Repository):
    def save_regime(self, payload: dict[str, Any]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO regime_snapshots(
                    epic, timeframe, regime, trend_strength, realized_volatility,
                    garch_volatility, spread, liquidity_score, risk_state, features_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload["epic"],
                    payload["timeframe"],
                    payload.get("regime"),
                    payload.get("trend_strength"),
                    payload.get("realized_volatility"),
                    payload.get("garch_volatility"),
                    payload.get("spread"),
                    payload.get("liquidity_score"),
                    payload.get("risk_state"),
                    Jsonb(payload.get("features") or {}),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def save_forecast_validation(self, payload: dict[str, Any]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO forecast_validation(
                    model_key, epic, timeframe, horizon_bar, n_samples, direction_accuracy,
                    mae, rmse, hit_rate_after_spread, profit_factor, avg_return_after_cost,
                    max_drawdown, details_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload["model_key"],
                    payload["epic"],
                    payload["timeframe"],
                    int(payload["horizon_bar"]),
                    payload.get("n_samples"),
                    payload.get("direction_accuracy"),
                    payload.get("mae"),
                    payload.get("rmse"),
                    payload.get("hit_rate_after_spread"),
                    payload.get("profit_factor"),
                    payload.get("avg_return_after_cost"),
                    payload.get("max_drawdown"),
                    Jsonb(payload.get("details") or {}),
                ),
            ).fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])

    def list_validation(self, *, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM forecast_validation
                WHERE (%s::text IS NULL OR epic = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY evaluated_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}

    def list_regime(self, *, epic: str | None = None, timeframe: str | None = None, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM regime_snapshots
                WHERE (%s::text IS NULL OR epic = %s)
                  AND (%s::text IS NULL OR timeframe = %s)
                ORDER BY computed_at DESC
                LIMIT %s
                """,
                (epic, epic, timeframe, timeframe, max(1, int(limit))),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}
