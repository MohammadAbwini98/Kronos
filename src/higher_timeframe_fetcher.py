from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from capital_rest_client import CapitalRestClient
from candle_context import resolution_to_timedelta
from config import ConfigError, load_settings
from db import connect
from logging_utils import log_event
from prediction_store import upsert_ohlcv_df
from service_runtime import write_heartbeat


LOGGER = logging.getLogger(__name__)

DEFAULT_HIGHER_TIMEFRAMES = ["MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4"]


def _timeframe_snapshot(
    *,
    symbol: str,
    resolution: str,
    price_side: str,
    dsn: str | None,
    now_utc: pd.Timestamp,
) -> dict[str, Any]:
    delta = resolution_to_timedelta(resolution)
    cutoff = now_utc - delta
    expected_latest_closed = now_utc.floor(delta) - delta

    with connect(dsn) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)::int AS total_rows,
                COUNT(*) FILTER (WHERE timestamp_utc <= %s)::int AS closed_rows,
                MAX(timestamp_utc) AS latest_timestamp_utc,
                MAX(timestamp_utc) FILTER (WHERE timestamp_utc <= %s) AS latest_closed_timestamp_utc
            FROM ohlcv_candles
            WHERE symbol = %s
              AND resolution = %s
              AND price_side = %s
            """,
            (cutoff, cutoff, symbol, resolution, price_side),
        ).fetchone()

    total_rows = int((row or {}).get("total_rows") or 0)
    closed_rows = int((row or {}).get("closed_rows") or 0)
    latest_ts = (row or {}).get("latest_timestamp_utc")
    latest_ts = pd.to_datetime(latest_ts, utc=True, errors="coerce") if latest_ts is not None else None
    latest_closed_ts = (row or {}).get("latest_closed_timestamp_utc")
    latest_closed_ts = pd.to_datetime(latest_closed_ts, utc=True, errors="coerce") if latest_closed_ts is not None else None

    has_closed_latest = bool(latest_closed_ts is not None and latest_closed_ts >= expected_latest_closed)
    stale_seconds = None
    if latest_closed_ts is not None:
        stale_seconds = max(0, int((now_utc - latest_closed_ts).total_seconds()))

    return {
        "total_rows": total_rows,
        "closed_rows": closed_rows,
        "latest_timestamp_utc": None if latest_ts is None else latest_ts.isoformat(),
        "latest_closed_timestamp_utc": None if latest_closed_ts is None else latest_closed_ts.isoformat(),
        "expected_latest_closed_timestamp_utc": expected_latest_closed.isoformat(),
        "has_closed_latest": has_closed_latest,
        "stale_seconds": stale_seconds,
        "resolution_delta_minutes": int(delta.total_seconds() / 60),
    }


def _credentials_available(env_name: str | None) -> tuple[bool, str | None, CapitalRestClient | None]:
    try:
        settings = load_settings(env_name)
        settings.ensure_credentials()
        client = CapitalRestClient(settings)
        client.authenticate()
        return True, None, client
    except ConfigError as exc:
        return False, str(exc), None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), None


def _write_fetcher_heartbeat(status: str, details: dict[str, Any], dsn: str | None) -> None:
    try:
        write_heartbeat("higher_timeframe_fetcher", status, details, dsn)
    except Exception:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.WARNING,
            "higher_timeframe_fetcher.heartbeat.failed",
            status=status,
            details=details,
        )


def ensure_higher_timeframe_candles(
    *,
    symbol: str,
    price_side: str = "mid",
    epic: str | None = None,
    required_timeframes: list[str] | None = None,
    min_rows_per_timeframe: int = 120,
    env_name: str | None = None,
    dsn: str | None = None,
    now_utc: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """
    Ensure higher-timeframe context exists in PostgreSQL for external validation.

    Returns a structured payload with availability and missing-context reasons.
    """
    started_at = pd.Timestamp.now(tz="UTC")
    current_time = now_utc or started_at
    raw_timeframes = [tf.strip().upper() for tf in (required_timeframes or DEFAULT_HIGHER_TIMEFRAMES)]
    timeframes = [tf for tf in raw_timeframes if tf in DEFAULT_HIGHER_TIMEFRAMES]
    if required_timeframes is None and not timeframes:
        timeframes = list(DEFAULT_HIGHER_TIMEFRAMES)

    result: dict[str, Any] = {
        "ok": True,
        "symbol": symbol,
        "epic": epic,
        "price_side": price_side,
        "required_timeframes": timeframes,
        "timeframes": {},
        "missing_timeframes": [],
        "reason_details": [],
        "fetched_rows": {},
        "credentials_available": False,
    }
    required_closed_rows = max(1, int(min_rows_per_timeframe) - 1)

    try:
        for timeframe in timeframes:
            snapshot = _timeframe_snapshot(
                symbol=symbol,
                resolution=timeframe,
                price_side=price_side,
                dsn=dsn,
                now_utc=current_time,
            )
            enough_rows = snapshot["closed_rows"] >= required_closed_rows
            fresh_closed = bool(snapshot["has_closed_latest"])
            snapshot["enough_rows"] = enough_rows
            snapshot["fresh_closed"] = fresh_closed
            snapshot["required_closed_rows"] = required_closed_rows
            snapshot["needs_fetch"] = not (enough_rows and fresh_closed)
            result["timeframes"][timeframe] = snapshot
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["missing_timeframes"] = list(timeframes)
        result["reason_details"].append(f"Database unavailable while checking context: {exc}")
        _write_fetcher_heartbeat("ERROR", result, dsn)
        return result

    needs_fetch = [tf for tf in timeframes if result["timeframes"][tf]["needs_fetch"]]
    if not needs_fetch:
        _write_fetcher_heartbeat("OK", result, dsn)
        return result

    has_credentials, credentials_error, client = _credentials_available(env_name)
    result["credentials_available"] = has_credentials
    if not has_credentials:
        result["ok"] = False
        result["missing_timeframes"] = list(needs_fetch)
        result["reason_details"].append(
            "Capital.com credentials unavailable; cannot fetch missing higher-timeframe context."
        )
        if credentials_error:
            result["reason_details"].append(credentials_error)
        _write_fetcher_heartbeat("ERROR", result, dsn)
        return result

    try:
        selected = client.resolve_market(symbol, epic, streaming=False)
        resolved_epic = selected["epic"]
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["missing_timeframes"] = list(needs_fetch)
        result["reason_details"].append(f"Unable to resolve market for higher-timeframe fetch: {exc}")
        _write_fetcher_heartbeat("ERROR", result, dsn)
        return result

    result["epic"] = resolved_epic

    for timeframe in needs_fetch:
        try:
            fetch_limit = max(int(min_rows_per_timeframe) + 2, 180)
            df = client.get_historical_prices(
                epic=resolved_epic,
                resolution=timeframe,
                max_points=fetch_limit,
                price_side=price_side,
                save_outputs=False,
                min_rows=1,
            )
            stored_rows = upsert_ohlcv_df(
                df,
                symbol=symbol,
                epic=resolved_epic,
                resolution=timeframe,
                price_side=price_side,
                source="latest_fetch",
                dsn=dsn,
            )
            result["fetched_rows"][timeframe] = int(stored_rows)
            snapshot = _timeframe_snapshot(
                symbol=symbol,
                resolution=timeframe,
                price_side=price_side,
                dsn=dsn,
                now_utc=current_time,
            )
            snapshot["enough_rows"] = snapshot["closed_rows"] >= required_closed_rows
            snapshot["fresh_closed"] = bool(snapshot["has_closed_latest"])
            snapshot["required_closed_rows"] = required_closed_rows
            snapshot["needs_fetch"] = not (snapshot["enough_rows"] and snapshot["fresh_closed"])
            result["timeframes"][timeframe] = snapshot
            if snapshot["needs_fetch"]:
                result["ok"] = False
                result["missing_timeframes"].append(timeframe)
                result["reason_details"].append(
                    f"Fetched {timeframe} candles but context is still insufficient."
                )
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["missing_timeframes"].append(timeframe)
            result["reason_details"].append(f"Failed to fetch {timeframe} candles: {exc}")

    status = "OK" if result["ok"] else "ERROR"
    _write_fetcher_heartbeat(status, result, dsn)

    log_event(
        LOGGER,
        logging.INFO if result["ok"] else logging.WARNING,
        "higher_timeframe_fetcher.completed",
        symbol=symbol,
        epic=result.get("epic"),
        price_side=price_side,
        required_timeframes=timeframes,
        missing_timeframes=result.get("missing_timeframes"),
        fetched_rows=result.get("fetched_rows"),
        duration_ms=int((pd.Timestamp.now(tz="UTC") - started_at).total_seconds() * 1000),
    )
    return result
