from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from db import connect


def acquire_supervisor_lease(
    *,
    supervisor_instance_id: str,
    lease_name: str = "dashboard_stack",
    process_id: int,
    command_line: str,
    ttl_seconds: int = 120,
    allow_duplicate: bool = False,
    dsn: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=max(30, int(ttl_seconds)))
    with connect(dsn) as conn:
        existing = conn.execute(
            "SELECT * FROM supervisor_leases WHERE lease_name = %s",
            (lease_name,),
        ).fetchone()
        if existing and existing["expires_at"] > now and existing["supervisor_instance_id"] != supervisor_instance_id and not allow_duplicate:
            return {"acquired": False, "existing": dict(existing)}
        row = conn.execute(
            """
            INSERT INTO supervisor_leases(
                lease_name, supervisor_instance_id, host_name, process_id, command_line,
                acquired_at, expires_at, heartbeat_at
            )
            VALUES (%s, %s, %s, %s, %s, now(), %s, now())
            ON CONFLICT(lease_name) DO UPDATE SET
                supervisor_instance_id = EXCLUDED.supervisor_instance_id,
                host_name = EXCLUDED.host_name,
                process_id = EXCLUDED.process_id,
                command_line = EXCLUDED.command_line,
                acquired_at = now(),
                expires_at = EXCLUDED.expires_at,
                heartbeat_at = now()
            RETURNING *
            """,
            (lease_name, supervisor_instance_id, socket.gethostname(), int(process_id), command_line, expires.isoformat()),
        ).fetchone()
    return {"acquired": True, "lease": dict(row)}


def heartbeat_supervisor_lease(
    *,
    supervisor_instance_id: str,
    lease_name: str = "dashboard_stack",
    ttl_seconds: int = 120,
    dsn: str | None = None,
) -> bool:
    expires = datetime.now(timezone.utc) + timedelta(seconds=max(30, int(ttl_seconds)))
    with connect(dsn) as conn:
        row = conn.execute(
            """
            UPDATE supervisor_leases
            SET expires_at = %s,
                heartbeat_at = now()
            WHERE lease_name = %s
              AND supervisor_instance_id = %s
            RETURNING lease_name
            """,
            (expires.isoformat(), lease_name, supervisor_instance_id),
        ).fetchone()
    return bool(row)


def release_supervisor_lease(
    *,
    supervisor_instance_id: str,
    lease_name: str = "dashboard_stack",
    dsn: str | None = None,
) -> bool:
    with connect(dsn) as conn:
        rows = conn.execute(
            "DELETE FROM supervisor_leases WHERE lease_name = %s AND supervisor_instance_id = %s RETURNING lease_name",
            (lease_name, supervisor_instance_id),
        ).fetchall()
    return bool(rows)


def current_supervisor_lease(*, lease_name: str = "dashboard_stack", dsn: str | None = None) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        row = conn.execute("SELECT * FROM supervisor_leases WHERE lease_name = %s", (lease_name,)).fetchone()
    return dict(row) if row else None
