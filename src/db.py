from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


DEFAULT_POSTGRES_DSN = "postgresql://postgres:123@localhost:5432/capital_kronos"


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
    return override or os.getenv("POSTGRES_DSN", DEFAULT_POSTGRES_DSN)


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
    with psycopg.connect(postgres_dsn(dsn), row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        yield conn


def run_migrations(dsn: str | None = None, migrations_dir: str | Path = "migrations") -> list[str]:
    applied: list[str] = []
    directory = Path(migrations_dir)
    if not directory.exists():
        raise DatabaseError(f"Migrations directory does not exist: {directory}")
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
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (version,),
                )
                applied.append(version)
    return applied


def healthcheck(dsn: str | None = None) -> dict[str, object]:
    try:
        with connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now() AS server_time_utc")
                row = cur.fetchone()
        return {"ok": True, "server_time_utc": row["server_time_utc"].isoformat() if row else None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
