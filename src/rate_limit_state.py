from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from db import connect


class RateLimitCooldownError(RuntimeError):
    """Raised when an endpoint class is locally cooling down."""


def endpoint_class_for_path(path: str) -> str:
    text = str(path)
    if text.startswith("/prices/"):
        return "prices"
    if text.startswith("/markets"):
        return "markets"
    if text.startswith("/session"):
        return "auth"
    if text.startswith("/clientsentiment"):
        return "sentiment"
    return "general"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cooldown_state(endpoint_class: str, *, dsn: str | None = None) -> dict[str, Any] | None:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                "SELECT endpoint_class, status, last_error, last_status_code, retry_after_utc, consecutive_failures, updated_at FROM api_rate_limit_state WHERE endpoint_class = %s",
                (endpoint_class,),
            ).fetchone()
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def ensure_not_cooling_down(endpoint_class: str, *, dsn: str | None = None) -> None:
    state = cooldown_state(endpoint_class, dsn=dsn)
    if not state or state.get("status") != "COOLDOWN":
        return
    retry_after = state.get("retry_after_utc")
    if retry_after is not None:
        if isinstance(retry_after, str):
            retry_after = datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
        if retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        if retry_after <= _utcnow():
            clear_cooldown(endpoint_class, dsn=dsn)
            return
    raise RateLimitCooldownError(f"Capital.com endpoint class {endpoint_class} is in COOLDOWN until {retry_after}")


def record_rate_limit(
    endpoint_class: str,
    *,
    error: str,
    status_code: int = 429,
    retry_after_seconds: int = 60,
    dsn: str | None = None,
) -> dict[str, Any]:
    retry_after = _utcnow() + timedelta(seconds=max(1, int(retry_after_seconds)))
    with connect(dsn) as conn:
        row = conn.execute(
            """
            INSERT INTO api_rate_limit_state(
                endpoint_class, status, last_error, last_status_code, retry_after_utc,
                consecutive_failures, updated_at
            )
            VALUES (%s, 'COOLDOWN', %s, %s, %s, 1, now())
            ON CONFLICT(endpoint_class) DO UPDATE SET
                status = 'COOLDOWN',
                last_error = EXCLUDED.last_error,
                last_status_code = EXCLUDED.last_status_code,
                retry_after_utc = EXCLUDED.retry_after_utc,
                consecutive_failures = api_rate_limit_state.consecutive_failures + 1,
                updated_at = now()
            RETURNING endpoint_class, status, last_error, last_status_code, retry_after_utc, consecutive_failures, updated_at
            """,
            (endpoint_class, error[-1000:], int(status_code), retry_after.isoformat()),
        ).fetchone()
    return dict(row)


def clear_cooldown(endpoint_class: str, *, dsn: str | None = None) -> None:
    try:
        with connect(dsn) as conn:
            conn.execute(
                """
                INSERT INTO api_rate_limit_state(endpoint_class, status, consecutive_failures, updated_at)
                VALUES (%s, 'OK', 0, now())
                ON CONFLICT(endpoint_class) DO UPDATE SET
                    status = 'OK',
                    consecutive_failures = 0,
                    retry_after_utc = NULL,
                    updated_at = now()
                """,
                (endpoint_class,),
            )
    except Exception:  # noqa: BLE001
        return


def list_rate_limit_states(*, dsn: str | None = None) -> list[dict[str, Any]]:
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
                "SELECT endpoint_class, status, last_error, last_status_code, retry_after_utc, consecutive_failures, updated_at FROM api_rate_limit_state ORDER BY endpoint_class"
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:  # noqa: BLE001
        return []
