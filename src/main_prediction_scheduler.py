from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from config import configure_logging
from db import connect
from logging_utils import log_event, new_correlation_id, output_tail as sanitize_output_tail, safe_command_for_log
from service_runtime import write_heartbeat

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

DEFAULT_WEBSOCKET_STALE_SECONDS = max(30, int(os.getenv("SIGNAL_WEBSOCKET_STALE_SECONDS", "90")))
WEBSOCKET_STREAM_PAUSE_STATUSES = {"RECONNECTING", "COOLDOWN", "ERROR", "MISSING"}
_LAST_PROCESSED_WEBSOCKET_CANDLE: dict[tuple[str, str], pd.Timestamp] = {}


@dataclass
class WebSocketPredictionGate:
    allow: bool
    reason: str
    details: dict[str, Any]
    latest_candle_timestamp_utc: str | None = None


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
    parser.add_argument(
        "--websocket-stale-seconds",
        type=int,
        default=DEFAULT_WEBSOCKET_STALE_SECONDS,
        help="Pause prediction runs when websocket updates are older than this threshold.",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduler cycle and exit.")
    args = parser.parse_args()
    args.resolution = str(args.resolution).upper()
    args.websocket_stale_seconds = max(30, int(args.websocket_stale_seconds))
    if args.interval_minutes is None:
        args.interval_minutes = RESOLUTION_TO_MINUTES.get(args.resolution, 5)
    return args


def _to_utc_timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if ts is pd.NaT:
        return None
    return ts


def _seconds_since(value: pd.Timestamp | None, *, now: pd.Timestamp) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def _iso(value: pd.Timestamp | None) -> str | None:
    return None if value is None else value.isoformat()


def _websocket_key(args: argparse.Namespace) -> tuple[str, str]:
    return (str(args.symbol).upper(), str(args.resolution).upper())


def _websocket_prediction_gate(args: argparse.Namespace) -> WebSocketPredictionGate:
    now_utc = pd.Timestamp.now(tz="UTC")
    symbol = str(args.symbol).strip()
    resolution = str(args.resolution).strip().upper()
    stale_threshold = int(args.websocket_stale_seconds)
    key = _websocket_key(args)
    last_processed = _LAST_PROCESSED_WEBSOCKET_CANDLE.get(key)
    details: dict[str, Any] = {
        "state": "websocket_gate",
        "gate_checked_at": now_utc.isoformat(),
        "symbol": symbol,
        "resolution": resolution,
        "websocket_stale_threshold_seconds": stale_threshold,
        "last_processed_websocket_candle_timestamp_utc": _iso(last_processed),
    }
    try:
        with connect(args.postgres_dsn) as conn:
            latest_quote = conn.execute(
                """
                SELECT updated_at, timestamp_utc, source
                FROM live_quotes
                WHERE symbol = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            latest_websocket_candle = conn.execute(
                """
                SELECT timestamp_utc, updated_at
                FROM ohlcv_candles
                WHERE symbol = %s AND resolution = %s AND source = 'websocket_ohlc'
                ORDER BY timestamp_utc DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol, resolution),
            ).fetchone()
            websocket_state = conn.execute(
                """
                SELECT status, updated_at
                FROM service_heartbeats
                WHERE service_name = 'websocket_stream'
                """
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        details.update({"state": "paused_websocket_gate", "gate_reason": "websocket_health_unavailable", "error": str(exc)})
        return WebSocketPredictionGate(
            allow=False,
            reason="websocket_health_unavailable",
            details=details,
        )

    quote_updated_at = _to_utc_timestamp((latest_quote or {}).get("updated_at"))
    quote_timestamp_utc = _to_utc_timestamp((latest_quote or {}).get("timestamp_utc"))
    quote_ref = quote_updated_at or quote_timestamp_utc
    websocket_candle_timestamp = _to_utc_timestamp((latest_websocket_candle or {}).get("timestamp_utc"))
    websocket_candle_updated_at = _to_utc_timestamp((latest_websocket_candle or {}).get("updated_at"))
    websocket_candidates = [v for v in [quote_ref, websocket_candle_updated_at, websocket_candle_timestamp] if v is not None]
    websocket_ref = max(websocket_candidates) if websocket_candidates else None
    websocket_stale_seconds = _seconds_since(websocket_ref, now=now_utc)

    websocket_stream_status = str((websocket_state or {}).get("status") or "MISSING").upper()
    websocket_stream_updated_at = _to_utc_timestamp((websocket_state or {}).get("updated_at"))

    details.update(
        {
            "websocket_stream_status": websocket_stream_status,
            "websocket_stream_updated_at": _iso(websocket_stream_updated_at),
            "websocket_quote_updated_at": _iso(quote_updated_at),
            "websocket_quote_timestamp_utc": _iso(quote_timestamp_utc),
            "latest_websocket_candle_timestamp_utc": _iso(websocket_candle_timestamp),
            "latest_websocket_candle_updated_at": _iso(websocket_candle_updated_at),
            "websocket_last_update_utc": _iso(websocket_ref),
            "websocket_stale_seconds": websocket_stale_seconds,
        }
    )

    if websocket_stream_status in WEBSOCKET_STREAM_PAUSE_STATUSES:
        details.update({"state": "paused_websocket_gate", "gate_reason": "websocket_stream_not_ready"})
        return WebSocketPredictionGate(
            allow=False,
            reason="websocket_stream_not_ready",
            details=details,
            latest_candle_timestamp_utc=_iso(websocket_candle_timestamp),
        )
    if websocket_candle_timestamp is None:
        details.update({"state": "paused_websocket_gate", "gate_reason": "websocket_candle_missing"})
        return WebSocketPredictionGate(
            allow=False,
            reason="websocket_candle_missing",
            details=details,
        )
    if websocket_stale_seconds is None or websocket_stale_seconds > stale_threshold:
        details.update({"state": "paused_websocket_gate", "gate_reason": "websocket_stale"})
        return WebSocketPredictionGate(
            allow=False,
            reason="websocket_stale",
            details=details,
            latest_candle_timestamp_utc=_iso(websocket_candle_timestamp),
        )
    if last_processed is not None and websocket_candle_timestamp <= last_processed:
        details.update({"state": "paused_websocket_gate", "gate_reason": "no_new_websocket_candle"})
        return WebSocketPredictionGate(
            allow=False,
            reason="no_new_websocket_candle",
            details=details,
            latest_candle_timestamp_utc=_iso(websocket_candle_timestamp),
        )

    details.update({"state": "websocket_gate_passed", "gate_reason": "ok"})
    return WebSocketPredictionGate(
        allow=True,
        reason="ok",
        details=details,
        latest_candle_timestamp_utc=_iso(websocket_candle_timestamp),
    )


def _heartbeat(name: str, status: str, details: dict, dsn: str | None) -> None:
    try:
        write_heartbeat(name, status, details, dsn)
    except Exception:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.WARNING,
            "scheduler.heartbeat.write.failed",
            status=status,
            details=details,
        )


def _sleep_to_next_boundary(args: argparse.Namespace, heartbeat_interval_seconds: int = 60) -> None:
    scheduler_cycle_id = new_correlation_id("sched")
    now = pd.Timestamp.now(tz="UTC")
    interval_seconds = int(args.interval_minutes) * 60
    next_epoch = ((int(now.timestamp()) // interval_seconds) + 1) * interval_seconds
    remaining = max(0, next_epoch - int(now.timestamp()))
    log_event(
        LOGGER,
        logging.INFO,
        "scheduler.sleep.start",
        scheduler_cycle_id=scheduler_cycle_id,
        symbol=args.symbol,
        resolution=args.resolution,
        interval_minutes=int(args.interval_minutes),
        seconds_until_next_cycle=int(remaining),
    )
    while remaining > 0:
        chunk = min(max(1, int(heartbeat_interval_seconds)), remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining <= 0:
            break
        log_event(
            LOGGER,
            logging.DEBUG,
            "scheduler.sleep.heartbeat",
            scheduler_cycle_id=scheduler_cycle_id,
            symbol=args.symbol,
            resolution=args.resolution,
            seconds_until_next_cycle=int(remaining),
        )
        _heartbeat(
            "prediction_scheduler",
            "OK",
            {
                "state": "sleeping",
                "current_operation": "sleep",
                "seconds_until_next_cycle": int(remaining),
                "symbol": args.symbol,
                "resolution": args.resolution,
                "interval_minutes": int(args.interval_minutes),
                "scheduler_cycle_id": scheduler_cycle_id,
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
    scheduler_cycle_id = new_correlation_id("sched")
    cycle_started = time.perf_counter()
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
    log_event(
        LOGGER,
        logging.INFO,
        "scheduler.cycle.start",
        scheduler_cycle_id=scheduler_cycle_id,
        symbol=args.symbol,
        market=args.market,
        resolution=args.resolution,
        interval_minutes=int(args.interval_minutes),
        lookback=args.lookback,
        pred_len=args.pred_len,
        env=args.env,
    )
    log_event(
        LOGGER,
        logging.INFO,
        "scheduler.websocket_gate.start",
        scheduler_cycle_id=scheduler_cycle_id,
        symbol=args.symbol,
        resolution=args.resolution,
    )
    gate = _websocket_prediction_gate(args)
    if not gate.allow:
        log_event(
            LOGGER,
            logging.WARNING,
            "scheduler.websocket_gate.pause",
            scheduler_cycle_id=scheduler_cycle_id,
            symbol=args.symbol,
            resolution=args.resolution,
            websocket_gate_reason=gate.reason,
            latest_websocket_candle_timestamp_utc=gate.latest_candle_timestamp_utc,
        )
        details = {
            "returncode": 0,
            "attempts": 0,
            "symbol": args.symbol,
            "resolution": args.resolution,
            "interval_minutes": int(args.interval_minutes),
            "scheduler_cycle_id": scheduler_cycle_id,
            "current_operation": "paused",
            "last_success_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
            **gate.details,
        }
        _heartbeat("prediction_scheduler", "PAUSED", details, args.postgres_dsn)
        LOGGER.warning("Scheduler cycle paused: %s", gate.reason)
        return 0
    log_event(
        LOGGER,
        logging.INFO,
        "scheduler.websocket_gate.pass",
        scheduler_cycle_id=scheduler_cycle_id,
        symbol=args.symbol,
        resolution=args.resolution,
        websocket_gate_reason=gate.reason,
        latest_websocket_candle_timestamp_utc=gate.latest_candle_timestamp_utc,
    )
    try:
        attempt = 0
        max_attempts = 2
        result: subprocess.CompletedProcess[str] | None = None
        output_tail_text = ""
        while attempt < max_attempts:
            attempt += 1
            log_event(
                LOGGER,
                logging.INFO,
                "scheduler.forecast.subprocess.start",
                scheduler_cycle_id=scheduler_cycle_id,
                attempts=attempt,
                command=safe_command_for_log(cmd),
                symbol=args.symbol,
                resolution=args.resolution,
            )
            result = _run_forecast_command(cmd, args)
            output = _combined_output(result)
            output_tail_text = sanitize_output_tail(output)
            log_event(
                LOGGER,
                logging.INFO if result.returncode == 0 else logging.WARNING,
                "scheduler.forecast.subprocess.completed",
                scheduler_cycle_id=scheduler_cycle_id,
                attempts=attempt,
                returncode=int(result.returncode),
                output_tail=output_tail_text if result.returncode != 0 else None,
                symbol=args.symbol,
                resolution=args.resolution,
            )
            if result.returncode == 0:
                break
            if attempt < max_attempts and _looks_like_rate_limit(output):
                backoff_seconds = 10
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "scheduler.forecast.rate_limit_retry",
                    scheduler_cycle_id=scheduler_cycle_id,
                    attempts=attempt,
                    retry_in_seconds=backoff_seconds,
                    symbol=args.symbol,
                    resolution=args.resolution,
                )
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

        if result.returncode != 0 and output_tail_text:
            LOGGER.warning("Scheduler cycle failed output tail: %s", output_tail_text)

        details = {
            "returncode": int(result.returncode),
            "attempts": attempt,
            "symbol": args.symbol,
            "resolution": args.resolution,
            "interval_minutes": int(args.interval_minutes),
            "scheduler_cycle_id": scheduler_cycle_id,
            "current_operation": "cycle",
            "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
            **gate.details,
        }
        if result.returncode != 0 and output_tail_text:
            details["output_tail"] = output_tail_text
        heartbeat_status = "OK" if result.returncode == 0 else ("COOLDOWN" if _looks_like_rate_limit(output_tail_text) else "ERROR")
        if heartbeat_status == "COOLDOWN":
            details["state"] = "cooldown"
        details["last_duration_ms"] = int((time.perf_counter() - cycle_started) * 1000)
        if result.returncode == 0:
            details["last_success_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
            details["last_error"] = None
        else:
            details["last_error"] = output_tail_text if output_tail_text else f"returncode={result.returncode}"
        _heartbeat("prediction_scheduler", heartbeat_status, details, args.postgres_dsn)
        if result.returncode == 0 and gate.latest_candle_timestamp_utc:
            key = _websocket_key(args)
            parsed = _to_utc_timestamp(gate.latest_candle_timestamp_utc)
            if parsed is not None:
                _LAST_PROCESSED_WEBSOCKET_CANDLE[key] = parsed
        log_event(
            LOGGER,
            logging.INFO if result.returncode == 0 else logging.ERROR,
            "scheduler.cycle.completed",
            scheduler_cycle_id=scheduler_cycle_id,
            symbol=args.symbol,
            resolution=args.resolution,
            attempts=attempt,
            returncode=int(result.returncode),
            duration_ms=int((time.perf_counter() - cycle_started) * 1000),
            output_tail=output_tail_text if result.returncode != 0 else None,
        )
        LOGGER.info("Scheduler cycle finished with return code %s", result.returncode)
        return result.returncode
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "scheduler.cycle.error",
            scheduler_cycle_id=scheduler_cycle_id,
            symbol=args.symbol,
            resolution=args.resolution,
            duration_ms=int((time.perf_counter() - cycle_started) * 1000),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        details = {
            "error": str(exc),
            "symbol": args.symbol,
            "resolution": args.resolution,
            "scheduler_cycle_id": scheduler_cycle_id,
            "current_operation": "cycle_error",
            "last_error": str(exc),
            "last_duration_ms": int((time.perf_counter() - cycle_started) * 1000),
            "checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        _heartbeat("prediction_scheduler", "ERROR", details, args.postgres_dsn)
        LOGGER.exception("Scheduler cycle crashed")
        return 1


def main() -> None:
    configure_logging(service_name="prediction_scheduler")
    args = parse_args()
    log_event(
        LOGGER,
        logging.INFO,
        "scheduler.service.start",
        symbol=args.symbol,
        market=args.market,
        resolution=args.resolution,
        interval_minutes=int(args.interval_minutes),
        lookback=args.lookback,
        pred_len=args.pred_len,
        env=args.env,
    )
    while True:
        code = _run_cycle(args)
        if args.once:
            raise SystemExit(code)
        _sleep_to_next_boundary(args)


if __name__ == "__main__":
    main()
