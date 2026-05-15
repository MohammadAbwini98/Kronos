from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

from logging_utils import get_logger, log_event, mask_dsn, new_correlation_id


LOGGER = get_logger(__name__)


DEFAULT_POSTGRES_DSN = "postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos"
DEFAULT_POSTGRES_SCHEMA = "gold_manual"


class DatabaseError(RuntimeError):
    """Raised when PostgreSQL is not reachable or migrations fail."""


def load_dotenv_if_present(path: str | Path = ".env") -> None:
    source = Path(path)
    if not source.exists():
        return
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def postgres_dsn(override: str | None = None) -> str:
    load_dotenv_if_present()
    if override:
        return override
    configured = os.getenv("POSTGRES_DSN", "").strip()
    if configured:
        return configured
    component_dsn = _postgres_dsn_from_components()
    return component_dsn or DEFAULT_POSTGRES_DSN


def _postgres_dsn_from_components() -> str | None:
    name = os.getenv("DB_NAME", "").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "").strip()
    host = os.getenv("DB_HOST", "localhost").strip() or "localhost"
    port = os.getenv("DB_PORT", "5432").strip() or "5432"
    if not name or not user:
        return None
    credentials = quote(user, safe="")
    if password:
        credentials = f"{credentials}:{quote(password, safe='')}"
    return f"postgresql://{credentials}@{host}:{port}/{quote(name, safe='')}"


def postgres_schema() -> str:
    load_dotenv_if_present()
    schema = os.getenv("TRADING_DATABASE_SCHEMA", os.getenv("POSTGRES_SCHEMA", DEFAULT_POSTGRES_SCHEMA)).strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise DatabaseError(f"Invalid PostgreSQL schema name: {schema!r}")
    return schema


def masked_postgres_dsn(override: str | None = None) -> str:
    value = postgres_dsn(override)
    try:
        parsed = urlsplit(value)
        if "@" not in parsed.netloc:
            return value
        userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
        username = userinfo.split(":", 1)[0]
        return urlunsplit((parsed.scheme, f"{username}:***@{hostinfo}", parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "***"


@contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    resolved_dsn = postgres_dsn(dsn)
    schema = postgres_schema()
    dsn_masked = mask_dsn(resolved_dsn)
    started = time.perf_counter()
    log_event(LOGGER, 20, "db.connect.start", dsn_masked=dsn_masked, database_schema=schema)
    try:
        with psycopg.connect(resolved_dsn, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute("SET TIME ZONE 'UTC'")
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}", public')
            log_event(
                LOGGER,
                20,
                "db.connect.success",
                dsn_masked=dsn_masked,
                database_schema=schema,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            yield conn
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            40,
            "db.connect.error",
            dsn_masked=dsn_masked,
            database_schema=schema,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def run_migrations(dsn: str | None = None, migrations_dir: str | Path = "migrations") -> list[str]:
    applied: list[str] = []
    directory = Path(migrations_dir)
    if not directory.exists():
        raise DatabaseError(f"Migrations directory does not exist: {directory}")
    migration_run_id = new_correlation_id("migration")
    dsn_masked = mask_dsn(postgres_dsn(dsn))
    schema = postgres_schema()
    started = time.perf_counter()
    log_event(
        LOGGER,
        20,
        "db.migration.start",
        migration_run_id=migration_run_id,
        dsn_masked=dsn_masked,
        database_schema=schema,
        migrations_dir=str(directory),
    )
    try:
        with connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                for path in sorted(directory.glob("*.sql")):
                    version = path.stem
                    cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                    if cur.fetchone():
                        log_event(
                            LOGGER,
                            20,
                            "db.migration.skipped",
                            migration_run_id=migration_run_id,
                            migration_version=version,
                        )
                        continue
                    cur.execute(path.read_text(encoding="utf-8"))
                    cur.execute(
                        "INSERT INTO schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING",
                        (version,),
                    )
                    applied.append(version)
                    log_event(
                        LOGGER,
                        20,
                        "db.migration.applied",
                        migration_run_id=migration_run_id,
                        migration_version=version,
                    )
        log_event(
            LOGGER,
            20,
            "db.migration.completed",
            migration_run_id=migration_run_id,
            dsn_masked=dsn_masked,
            database_schema=schema,
            applied_count=len(applied),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            40,
            "db.migration.error",
            migration_run_id=migration_run_id,
            dsn_masked=dsn_masked,
            database_schema=schema,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    return applied


def healthcheck(dsn: str | None = None) -> dict[str, object]:
    started = time.perf_counter()
    dsn_masked = mask_dsn(postgres_dsn(dsn))
    schema = postgres_schema()
    log_event(LOGGER, 20, "db.healthcheck.start", dsn_masked=dsn_masked, database_schema=schema)
    try:
        with connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now() AS server_time_utc")
                row = cur.fetchone()
        payload = {"ok": True, "server_time_utc": row["server_time_utc"].isoformat() if row else None, "schema": schema}
        log_event(
            LOGGER,
            20,
            "db.healthcheck.completed",
            dsn_masked=dsn_masked,
            database_schema=schema,
            duration_ms=int((time.perf_counter() - started) * 1000),
            ok=True,
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            40,
            "db.healthcheck.completed",
            dsn_masked=dsn_masked,
            database_schema=schema,
            duration_ms=int((time.perf_counter() - started) * 1000),
            ok=False,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {"ok": False, "error": str(exc)}
