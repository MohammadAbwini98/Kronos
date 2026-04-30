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
    parser = argparse.ArgumentParser(description="Run the data-only Kronos signal scheduler every N minutes.")
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--market", default=os.getenv("CAPITAL_DEFAULT_MARKET_SEARCH", "ETHUSD"))
    parser.add_argument("--resolution", default=os.getenv("SIGNAL_RESOLUTION", "MINUTE_5"))
    parser.add_argument("--interval-minutes", type=int, default=5)
    parser.add_argument("--lookback", type=int, default=int(os.getenv("SIGNAL_LOOKBACK", "512")))
    parser.add_argument("--pred-len", type=int, default=int(os.getenv("SIGNAL_PRED_LEN", "12")))
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--kronos-python", default=r"C:\AI\Kronos\.venv\Scripts\python.exe")
    parser.add_argument("--once", action="store_true", help="Run one scheduler cycle and exit.")
    return parser.parse_args()


def _heartbeat(name: str, status: str, details: dict, dsn: str | None) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO service_heartbeats(service_name, status, details, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT(service_name) DO UPDATE SET status = EXCLUDED.status, details = EXCLUDED.details, updated_at = now()
            """,
            (name, status, Jsonb(details)),
        )


def _sleep_to_next_boundary(interval_minutes: int) -> None:
    now = pd.Timestamp.now(tz="UTC")
    interval_seconds = interval_minutes * 60
    next_epoch = ((int(now.timestamp()) // interval_seconds) + 1) * interval_seconds
    time.sleep(max(0, next_epoch - int(now.timestamp())))


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
    result = subprocess.run(cmd, cwd=Path.cwd(), text=True)
    _heartbeat("prediction_scheduler", "OK" if result.returncode == 0 else "ERROR", {"returncode": result.returncode}, args.postgres_dsn)
    return result.returncode


def main() -> None:
    args = parse_args()
    while True:
        code = _run_cycle(args)
        if args.once:
            raise SystemExit(code)
        _sleep_to_next_boundary(args.interval_minutes)


if __name__ == "__main__":
    main()
