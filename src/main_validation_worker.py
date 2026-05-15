from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

from config import DEFAULT_INSTRUMENT_SYMBOL, configure_logging
from db import connect
from logging_utils import log_event, new_correlation_id, output_tail
from prediction_store import refresh_shadow_prediction_statuses
from service_runtime import write_heartbeat
from subprocess_utils import run_logged_subprocess

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate completed prediction runs against actual Capital.com candles.")
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", os.getenv("TRADING_PROVIDER_SYMBOL", DEFAULT_INSTRUMENT_SYMBOL)))
    parser.add_argument("--all-symbols", action="store_true", help="Validate pending runs for all symbols instead of the configured symbol.")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("VALIDATION_BATCH_SIZE", "5")))
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _due_runs(dsn: str | None, limit: int = 5, symbol: str | None = None, all_symbols: bool = False) -> list[dict]:
    symbol_filter = None if all_symbols else str(symbol or "").strip() or None
    with connect(dsn) as conn:
        return conn.execute(
            """
            SELECT run_id, metadata_path, forecast_csv_path, epic, resolution, price_side, forecast_end_timestamp_utc
            FROM prediction_runs
            WHERE run_status IN ('PENDING', 'PARTIAL')
              AND (%s::text IS NULL OR symbol = %s::text OR epic = %s::text)
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
            (symbol_filter, symbol_filter, symbol_filter, max(1, int(limit))),
        ).fetchall()


def _heartbeat(status: str, details: dict, dsn: str | None) -> None:
    try:
        write_heartbeat("validation_worker", status, details, dsn)
    except Exception:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.WARNING,
            "validation.heartbeat.write.failed",
            status=status,
            details=details,
        )


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
    result = run_logged_subprocess(
        cmd,
        logger=LOGGER,
        event_prefix="validation.subprocess",
        cwd=Path.cwd(),
    )
    return int(result.returncode), output_tail(_combined_output(result))


def _validate_run(run: dict, args: argparse.Namespace, validation_cycle_id: str) -> tuple[int, str]:
    run_id = str(run["run_id"])
    log_event(
        LOGGER,
        logging.INFO,
        "validation.run.start",
        validation_cycle_id=validation_cycle_id,
        run_id=run_id,
        epic=run.get("epic"),
        resolution=run.get("resolution"),
        price_side=run.get("price_side"),
    )
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
        "--output",
        str(Path("output") / f"forecast_quality_report_{run_id}.json"),
    ]
    if args.postgres_dsn:
        fetch_cmd.extend(["--postgres-dsn", args.postgres_dsn])
        validate_cmd.extend(["--postgres-dsn", args.postgres_dsn])
    first_result = run_logged_subprocess(
        fetch_cmd,
        logger=LOGGER,
        event_prefix="validation.fetch_actual.subprocess",
        cwd=Path.cwd(),
        context={
            "validation_cycle_id": validation_cycle_id,
            "run_id": run_id,
            "epic": run.get("epic"),
            "resolution": run.get("resolution"),
            "price_side": run.get("price_side"),
        },
    )
    first_code = int(first_result.returncode)
    first_output = output_tail(_combined_output(first_result))
    if first_code != 0:
        log_event(
            LOGGER,
            logging.ERROR,
            "validation.run.error",
            validation_cycle_id=validation_cycle_id,
            run_id=run_id,
            returncode=first_code,
            output_tail=first_output,
        )
        return first_code, first_output
    validate_result = run_logged_subprocess(
        validate_cmd,
        logger=LOGGER,
        event_prefix="validation.quality.subprocess",
        cwd=Path.cwd(),
        context={
            "validation_cycle_id": validation_cycle_id,
            "run_id": run_id,
            "epic": run.get("epic"),
            "resolution": run.get("resolution"),
            "price_side": run.get("price_side"),
        },
    )
    final_code = int(validate_result.returncode)
    final_output = output_tail(_combined_output(validate_result))
    if final_code == 0:
        log_event(
            LOGGER,
            logging.INFO,
            "validation.run.completed",
            validation_cycle_id=validation_cycle_id,
            run_id=run_id,
            returncode=0,
        )
    else:
        log_event(
            LOGGER,
            logging.ERROR,
            "validation.run.error",
            validation_cycle_id=validation_cycle_id,
            run_id=run_id,
            returncode=final_code,
            output_tail=final_output,
        )
    return final_code, final_output


def _run_validation_cycle(args: argparse.Namespace, validation_cycle_id: str) -> dict:
    cycle_started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "validation.cycle.start",
        validation_cycle_id=validation_cycle_id,
        batch_size=max(1, int(args.batch_size)),
    )
    errors = 0
    last_error = None
    rate_limited = False
    due = _due_runs(
        args.postgres_dsn,
        limit=args.batch_size,
        symbol=getattr(args, "symbol", None),
        all_symbols=bool(getattr(args, "all_symbols", False)),
    )
    log_event(
        LOGGER,
        logging.INFO,
        "validation.due_runs.loaded",
        validation_cycle_id=validation_cycle_id,
        due_runs=len(due),
        batch_size=max(1, int(args.batch_size)),
    )
    for run in due:
        returncode, run_output_tail = _validate_run(run, args, validation_cycle_id)
        if returncode == 0:
            continue
        errors += 1
        last_error = f"{run['run_id']} failed with exit code {returncode}"
        if run_output_tail:
            last_error = f"{last_error}: {run_output_tail}"
            LOGGER.warning("Validation child failed for %s: %s", run["run_id"], run_output_tail)
        if _looks_like_rate_limit(run_output_tail):
            rate_limited = True
            LOGGER.warning("Validation cycle hit Capital.com rate limit; stopping this cycle early.")
            break
    shadow_started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "validation.shadow_status.start",
        validation_cycle_id=validation_cycle_id,
    )
    shadow_status = refresh_shadow_prediction_statuses(dsn=args.postgres_dsn, limit=max(10, int(args.batch_size) * 10))
    log_event(
        LOGGER,
        logging.INFO,
        "validation.shadow_status.completed",
        validation_cycle_id=validation_cycle_id,
        checked=int(shadow_status.get("checked") or 0),
        updated=int(shadow_status.get("updated") or 0),
        pending=int(shadow_status.get("pending") or 0),
        errors=int(shadow_status.get("errors") or 0),
        duration_ms=int((time.perf_counter() - shadow_started) * 1000),
    )
    if shadow_status["errors"]:
        errors += int(shadow_status["errors"])
        last_error = f"shadow status refresh errors: {shadow_status['errors']}"
    payload = {
        "due_runs": len(due),
        "errors": errors,
        "last_error": last_error,
        "rate_limited": rate_limited,
        "shadow_status": shadow_status,
        "validation_cycle_id": validation_cycle_id,
        "duration_ms": int((time.perf_counter() - cycle_started) * 1000),
    }
    log_event(
        LOGGER,
        logging.INFO if errors == 0 else logging.ERROR,
        "validation.cycle.completed",
        validation_cycle_id=validation_cycle_id,
        due_runs=len(due),
        errors=errors,
        rate_limited=rate_limited,
        duration_ms=payload["duration_ms"],
        last_error=last_error,
    )
    return payload


def main() -> None:
    configure_logging(service_name="validation_worker")
    args = parse_args()
    log_event(
        LOGGER,
        logging.INFO,
        "validation.service.start",
        poll_seconds=int(args.poll_seconds),
        batch_size=max(1, int(args.batch_size)),
        env=args.env,
        symbol=getattr(args, "symbol", None),
        all_symbols=bool(getattr(args, "all_symbols", False)),
    )
    while True:
        validation_cycle_id = new_correlation_id("val")
        details = {
            "due_runs": 0,
            "errors": 0,
            "last_error": None,
            "rate_limited": False,
            "validation_cycle_id": validation_cycle_id,
            "shadow_status": {"checked": 0, "updated": 0, "pending": 0, "errors": 0},
        }
        try:
            details = _run_validation_cycle(args, validation_cycle_id)
            LOGGER.info("Validation worker cycle complete: due_runs=%s errors=%s", details["due_runs"], details["errors"])
        except Exception as exc:  # noqa: BLE001
            details["errors"] = int(details.get("errors") or 0) + 1
            details["last_error"] = str(exc)
            details["duration_ms"] = 0
            log_event(
                LOGGER,
                logging.ERROR,
                "validation.cycle.error",
                validation_cycle_id=validation_cycle_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            LOGGER.exception("Validation worker cycle crashed")
        heartbeat_status = "OK" if details["errors"] == 0 else ("COOLDOWN" if details.get("rate_limited") else "ERROR")
        _heartbeat(
            heartbeat_status,
            {
                "state": "cooldown" if heartbeat_status == "COOLDOWN" else "running",
                "current_operation": "validation_cycle",
                "due_runs": details["due_runs"],
                "errors": details["errors"],
                "last_error": details["last_error"],
                "rate_limited": details["rate_limited"],
                "last_duration_ms": details.get("duration_ms"),
                "last_success_at_utc": pd.Timestamp.now(tz="UTC").isoformat() if details["errors"] == 0 else None,
                "validation_cycle_id": details.get("validation_cycle_id") or validation_cycle_id,
                "shadow_status": details["shadow_status"],
                "batch_size": max(1, int(args.batch_size)),
                "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
            },
            args.postgres_dsn,
        )
        if args.once:
            return
        log_event(
            LOGGER,
            logging.INFO,
            "validation.sleep.start",
            validation_cycle_id=validation_cycle_id,
            poll_seconds=int(args.poll_seconds),
        )
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
