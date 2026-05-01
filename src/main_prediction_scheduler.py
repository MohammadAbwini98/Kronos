from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
from psycopg.types.json import Jsonb

from config import configure_logging
from db import connect

LOGGER = logging.getLogger(__name__)


RESOLUTION_TO_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout and stderr:
        return f"{stdout}\n{stderr}".strip()
    return (stdout or stderr).strip()


def _looks_like_rate_limit(output: str) -> bool:
    text = (output or "").lower()
    return "error.too-many.requests" in text or "http 429" in text or "too many requests" in text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the data-only Kronos signal scheduler every N minutes.")
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--market", default=os.getenv("CAPITAL_DEFAULT_MARKET_SEARCH", "ETHUSD"))
    parser.add_argument("--resolution", default=os.getenv("SIGNAL_RESOLUTION", os.getenv("CAPITAL_DEFAULT_RESOLUTION", "MINUTE_5")))
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=int(os.getenv("SIGNAL_INTERVAL_MINUTES")) if os.getenv("SIGNAL_INTERVAL_MINUTES") else None,
    )
    parser.add_argument("--lookback", type=int, default=int(os.getenv("SIGNAL_LOOKBACK", "512")))
    parser.add_argument("--pred-len", type=int, default=int(os.getenv("SIGNAL_PRED_LEN", "12")))
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--kronos-python", default=r"C:\AI\Kronos\.venv\Scripts\python.exe")
    parser.add_argument("--once", action="store_true", help="Run one scheduler cycle and exit.")
    args = parser.parse_args()
    args.resolution = str(args.resolution).upper()
    if args.interval_minutes is None:
        args.interval_minutes = RESOLUTION_TO_MINUTES.get(args.resolution, 5)
    return args


def _heartbeat(name: str, status: str, details: dict, dsn: str | None) -> None:
    try:
        with connect(dsn) as conn:
            conn.execute(
                """
                INSERT INTO service_heartbeats(service_name, status, details, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT(service_name) DO UPDATE SET status = EXCLUDED.status, details = EXCLUDED.details, updated_at = now()
                """,
                (name, status, Jsonb(details)),
            )
    except Exception:  # noqa: BLE001
        LOGGER.debug("Unable to write scheduler heartbeat", exc_info=True)


def _sleep_to_next_boundary(args: argparse.Namespace, heartbeat_interval_seconds: int = 60) -> None:
    now = pd.Timestamp.now(tz="UTC")
    interval_seconds = int(args.interval_minutes) * 60
    next_epoch = ((int(now.timestamp()) // interval_seconds) + 1) * interval_seconds
    remaining = max(0, next_epoch - int(now.timestamp()))
    while remaining > 0:
        chunk = min(max(1, int(heartbeat_interval_seconds)), remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining <= 0:
            break
        _heartbeat(
            "prediction_scheduler",
            "OK",
            {
                "state": "sleeping",
                "seconds_until_next_cycle": int(remaining),
                "symbol": args.symbol,
                "resolution": args.resolution,
                "interval_minutes": int(args.interval_minutes),
                "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
            },
            args.postgres_dsn,
        )


def _run_forecast_command(cmd: list[str], args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    while True:
        try:
            stdout, stderr = process.communicate(timeout=60)
            return subprocess.CompletedProcess(cmd, int(process.returncode or 0), stdout, stderr)
        except subprocess.TimeoutExpired:
            _heartbeat(
                "prediction_scheduler",
                "OK",
                {
                    "state": "running_forecast",
                    "pid": process.pid,
                    "symbol": args.symbol,
                    "resolution": args.resolution,
                    "interval_minutes": int(args.interval_minutes),
                    "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
                },
                args.postgres_dsn,
            )


def _run_cycle(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "src/main_forecast_latest.py",
        "--market",
        args.market,
        "--symbol",
        args.symbol,
        "--resolution",
        args.resolution,
        "--max",
        str(args.lookback),
        "--lookback",
        str(args.lookback),
        "--pred-len",
        str(args.pred_len),
        "--env",
        args.env,
        "--repair-ohlc",
        "--kronos-python",
        args.kronos_python,
    ]
    if args.postgres_dsn:
        cmd.extend(["--postgres-dsn", args.postgres_dsn])
    LOGGER.info("Starting scheduler cycle for %s %s", args.symbol, args.resolution)
    try:
        attempt = 0
        max_attempts = 2
        result: subprocess.CompletedProcess[str] | None = None
        output_tail = ""
        while attempt < max_attempts:
            attempt += 1
            result = _run_forecast_command(cmd, args)
            output = _combined_output(result)
            output_tail = output[-2000:]
            if result.returncode == 0:
                break
            if attempt < max_attempts and _looks_like_rate_limit(output):
                backoff_seconds = 10
                LOGGER.warning(
                    "Scheduler cycle hit Capital.com rate limit (attempt %s/%s). Retrying in %ss.",
                    attempt,
                    max_attempts,
                    backoff_seconds,
                )
                time.sleep(backoff_seconds)
                continue
            break

        if result is None:
            raise RuntimeError("Scheduler did not execute forecast command")

        if result.returncode != 0 and output_tail:
            LOGGER.warning("Scheduler cycle failed output tail: %s", output_tail)

        details = {
            "returncode": int(result.returncode),
            "attempts": attempt,
            "symbol": args.symbol,
            "resolution": args.resolution,
            "interval_minutes": int(args.interval_minutes),
            "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        if result.returncode != 0 and output_tail:
            details["output_tail"] = output_tail
        _heartbeat("prediction_scheduler", "OK" if result.returncode == 0 else "ERROR", details, args.postgres_dsn)
        LOGGER.info("Scheduler cycle finished with return code %s", result.returncode)
        return result.returncode
    except Exception as exc:  # noqa: BLE001
        details = {
            "error": str(exc),
            "symbol": args.symbol,
            "resolution": args.resolution,
            "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        _heartbeat("prediction_scheduler", "ERROR", details, args.postgres_dsn)
        LOGGER.exception("Scheduler cycle crashed")
        return 1


def main() -> None:
    configure_logging(service_name="prediction_scheduler")
    args = parse_args()
    while True:
        code = _run_cycle(args)
        if args.once:
            raise SystemExit(code)
        _sleep_to_next_boundary(args)


if __name__ == "__main__":
    main()
