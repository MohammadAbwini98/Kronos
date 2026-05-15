from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from ._base import Repository


class ModelRegistryRepository(Repository):
    def upsert_model(
        self,
        *,
        model_key: str,
        model_family: str,
        version: str,
        artifact_path: str | None = None,
        config: dict[str, Any] | None = None,
        is_enabled: bool = True,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_registry(model_key, model_family, version, artifact_path, config_json, is_enabled, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT(model_key, version) DO UPDATE SET
                    model_family = EXCLUDED.model_family,
                    artifact_path = EXCLUDED.artifact_path,
                    config_json = EXCLUDED.config_json,
                    is_enabled = EXCLUDED.is_enabled,
                    updated_at = now()
                """,
                (model_key, model_family, version, artifact_path, Jsonb(config or {}), bool(is_enabled)),
            )

    def list_enabled(self, *, model_family: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM model_registry
                WHERE is_enabled = true
                  AND (%s::text IS NULL OR model_family = %s)
                ORDER BY model_key, version
                """,
                (model_family, model_family),
            ).fetchall()
        return {"rows": [dict(row) for row in rows]}
