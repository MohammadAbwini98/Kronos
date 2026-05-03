from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from config import configure_logging
from db import connect
from prediction_store import refresh_shadow_prediction_statuses
from service_runtime import write_heartbeat

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate completed prediction runs against actual Capital.com candles.")
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("VALIDATION_BATCH_SIZE", "5")))
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _due_runs(dsn: str | None, limit: int = 5) -> list[dict]:
    with connect(dsn) as conn:
        return conn.execute(
            """
            SELECT run_id, metadata_path, forecast_csv_path, epic, resolution, price_side, forecast_end_timestamp_utc
            FROM prediction_runs
            WHERE run_status IN ('PENDING', 'PARTIAL')
              AND EXISTS (
                  SELECT 1
                  FROM prediction_outcomes o
                  WHERE o.run_id = prediction_runs.run_id
                    AND o.status = 'PENDING'
                    AND o.forecast_timestamp_utc + CASE prediction_runs.resolution
                          WHEN 'MINUTE'    THEN INTERVAL '1 minute'
                          WHEN 'MINUTE_5'  THEN INTERVAL '5 minutes'
                          WHEN 'MINUTE_15' THEN INTERVAL '15 minutes'
                          WHEN 'MINUTE_30' THEN INTERVAL '30 minutes'
                          WHEN 'HOUR'      THEN INTERVAL '1 hour'
                          WHEN 'HOUR_4'    THEN INTERVAL '4 hours'
                          WHEN 'DAY'       THEN INTERVAL '1 day'
                          WHEN 'WEEK'      THEN INTERVAL '7 days'
                          ELSE             INTERVAL '5 minutes'
                        END <= now()
              )
            ORDER BY updated_at ASC, forecast_end_timestamp_utc ASC
            LIMIT %s
            """,
            (max(1, int(limit)),),
        ).fetchall()


def _heartbeat(status: str, details: dict, dsn: str | None) -> None:
    try:
        write_heartbeat("validation_worker", status, details, dsn)
    except Exception:  # noqa: BLE001
        LOGGER.debug("Unable to write validation heartbeat", exc_info=True)


def _stamp_from_run_id(run_id: str, resolution: str) -> str:
    return run_id.split(f"_{resolution}_")[-1]


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout and stderr:
        return f"{stdout}\n{stderr}".strip()
    return (stdout or stderr).strip()


def _looks_like_rate_limit(output: str) -> bool:
    text = (output or "").lower()
    return "error.too-many.requests" in text or "http 429" in text or "too many requests" in text


def _run_command(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True)
    return int(result.returncode), _combined_output(result)[-2000:]


def _validate_run(run: dict, args: argparse.Namespace) -> tuple[int, str]:
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
        "--allow-partial",
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
    LOGGER.info("Validation worker fetching actuals for run %s", run["run_id"])
    first_code, first_output = _run_command(fetch_cmd)
    if first_code != 0:
        return first_code, first_output
    LOGGER.info("Validation worker validating forecast quality for run %s", run["run_id"])
    return _run_command(validate_cmd)


def _run_validation_cycle(args: argparse.Namespace) -> dict:
    errors = 0
    last_error = None
    rate_limited = False
    due = _due_runs(args.postgres_dsn, limit=args.batch_size)
    for run in due:
        returncode, output_tail = _validate_run(run, args)
        if returncode == 0:
            continue
        errors += 1
        last_error = f"{run['run_id']} failed with exit code {returncode}"
        if output_tail:
            last_error = f"{last_error}: {output_tail}"
            LOGGER.warning("Validation child failed for %s: %s", run["run_id"], output_tail)
        if _looks_like_rate_limit(output_tail):
            rate_limited = True
            LOGGER.warning("Validation cycle hit Capital.com rate limit; stopping this cycle early.")
            break
    shadow_status = refresh_shadow_prediction_statuses(dsn=args.postgres_dsn, limit=max(10, int(args.batch_size) * 10))
    if shadow_status["errors"]:
        errors += int(shadow_status["errors"])
        last_error = f"shadow status refresh errors: {shadow_status['errors']}"
    return {
        "due_runs": len(due),
        "errors": errors,
        "last_error": last_error,
        "rate_limited": rate_limited,
        "shadow_status": shadow_status,
    }


def main() -> None:
    configure_logging(service_name="validation_worker")
    args = parse_args()
    while True:
        details = {
            "due_runs": 0,
            "errors": 0,
            "last_error": None,
            "rate_limited": False,
            "shadow_status": {"checked": 0, "updated": 0, "pending": 0, "errors": 0},
        }
        try:
            details = _run_validation_cycle(args)
            LOGGER.info("Validation worker cycle complete: due_runs=%s errors=%s", details["due_runs"], details["errors"])
        except Exception as exc:  # noqa: BLE001
            details["errors"] = int(details.get("errors") or 0) + 1
            details["last_error"] = str(exc)
            LOGGER.exception("Validation worker cycle crashed")
        heartbeat_status = "OK" if details["errors"] == 0 else ("COOLDOWN" if details.get("rate_limited") else "ERROR")
        _heartbeat(
            heartbeat_status,
            {
                "due_runs": details["due_runs"],
                "errors": details["errors"],
                "last_error": details["last_error"],
                "rate_limited": details["rate_limited"],
                "state": "cooldown" if heartbeat_status == "COOLDOWN" else "running",
                "shadow_status": details["shadow_status"],
                "batch_size": max(1, int(args.batch_size)),
                "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
            },
            args.postgres_dsn,
        )
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
