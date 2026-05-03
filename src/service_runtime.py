from __future__ import annotations

import os
import socket
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect


def runtime_details(details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(details or {})
    payload.setdefault("supervisor_instance_id", os.getenv("SUPERVISOR_INSTANCE_ID"))
    payload.setdefault("pid", os.getpid())
    payload.setdefault("host_name", socket.gethostname())
    payload.setdefault("checked_at_utc", pd.Timestamp.now(tz="UTC").isoformat())
    return payload


def write_heartbeat(service_name: str, status: str, details: dict[str, Any] | None, dsn: str | None) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO service_heartbeats(service_name, status, details, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT(service_name) DO UPDATE
            SET status = EXCLUDED.status,
                details = EXCLUDED.details,
                updated_at = now()
            """,
            (service_name, status, Jsonb(runtime_details(details))),
        )
