from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate completed prediction runs against actual Capital.com candles.")
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _due_runs(dsn: str | None) -> list[dict]:
    with connect(dsn) as conn:
        return conn.execute(
            """
            SELECT run_id, metadata_path, forecast_csv_path, epic, resolution, price_side, forecast_end_timestamp_utc
            FROM prediction_runs
            WHERE run_status IN ('PENDING', 'PARTIAL') AND forecast_end_timestamp_utc <= now()
            ORDER BY forecast_end_timestamp_utc
            LIMIT 20
            """
        ).fetchall()


def _heartbeat(status: str, details: dict, dsn: str | None) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO service_heartbeats(service_name, status, details, updated_at)
            VALUES ('validation_worker', %s, %s, now())
            ON CONFLICT(service_name) DO UPDATE SET status = EXCLUDED.status, details = EXCLUDED.details, updated_at = now()
            """,
            (status, Jsonb(details)),
        )


def _stamp_from_run_id(run_id: str, resolution: str) -> str:
    return run_id.split(f"_{resolution}_")[-1]


def _validate_run(run: dict, args: argparse.Namespace) -> int:
    stamp = _stamp_from_run_id(run["run_id"], run["resolution"])
    actual = Path("output") / f"actual_for_forecast_{run['epic']}_{run['resolution']}_{stamp}.csv"
    fetch_cmd = [
        sys.executable,
        "src/main_fetch_actual_for_forecast.py",
        "--metadata",
        run["metadata_path"],
        "--price-side",
        run["price_side"],
        "--env",
        args.env,
        "--output",
        str(actual),
    ]
    validate_cmd = [
        sys.executable,
        "src/main_validate_forecast_quality.py",
        "--forecast",
        run["forecast_csv_path"],
        "--actual",
        str(actual),
        "--metadata",
        run["metadata_path"],
        "--resolution",
        run["resolution"],
        "--price-side",
        run["price_side"],
        "--epic",
        run["epic"],
        "--run-id",
        run["run_id"],
    ]
    if args.postgres_dsn:
        fetch_cmd.extend(["--postgres-dsn", args.postgres_dsn])
        validate_cmd.extend(["--postgres-dsn", args.postgres_dsn])
    first = subprocess.run(fetch_cmd, cwd=Path.cwd(), text=True)
    if first.returncode != 0:
        return first.returncode
    second = subprocess.run(validate_cmd, cwd=Path.cwd(), text=True)
    return second.returncode


def main() -> None:
    args = parse_args()
    while True:
        due = _due_runs(args.postgres_dsn)
        errors = 0
        for run in due:
            errors += 1 if _validate_run(run, args) != 0 else 0
        _heartbeat("OK" if errors == 0 else "ERROR", {"due_runs": len(due), "errors": errors, "checked_at": pd.Timestamp.now(tz="UTC").isoformat()}, args.postgres_dsn)
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
