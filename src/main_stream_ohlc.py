from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import time

import websockets

from capital_auth import CapitalAuthenticator
from capital_rest_client import CapitalRestClient
from capital_ws_ohlc_client import CapitalOhlcWebSocketClient, CapitalWebSocketError
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from logging_utils import log_event, new_correlation_id
from rate_limit_state import RateLimitCooldownError
from service_runtime import write_heartbeat

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream Capital.com OHLC candles into a Kronos-ready rolling CSV.")
    parser.add_argument("--market", default=None, help="Search term such as ETHUSD, ETH/USD, or Ethereum.")
    parser.add_argument("--epic", default=None, help="Explicit Capital.com epic. Skips market search.")
    parser.add_argument("--resolution", default=None, help="MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY, WEEK.")
    parser.add_argument("--price-side", default=None, choices=["bid", "ask", "mid"], help="Accepted for CLI symmetry; stream payload is used as delivered.")
    parser.add_argument("--env", default=None, choices=["demo", "live"], help="Capital.com environment override.")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market or epic.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--retry-seconds", type=int, default=int(os.getenv("STREAM_RETRY_SECONDS", "15")))
    parser.add_argument("--max-retry-seconds", type=int, default=int(os.getenv("STREAM_MAX_RETRY_SECONDS", "300")))
    return parser.parse_args()


def _heartbeat(status: str, details: dict, dsn: str | None) -> None:
    try:
        write_heartbeat("websocket_stream", status, details, dsn)
    except Exception:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.WARNING,
            "websocket.heartbeat.write.failed",
            status=status,
            details=details,
        )


def _is_transient_websocket_error(exc: BaseException) -> bool:
    return isinstance(exc, (websockets.exceptions.ConnectionClosed, TimeoutError, OSError, CapitalWebSocketError))


async def _sleep_with_heartbeat(
    *,
    total_seconds: int,
    status: str,
    details: dict,
    dsn: str | None,
    heartbeat_interval_seconds: int = 60,
) -> None:
    remaining = max(0, int(total_seconds))
    interval = max(1, int(heartbeat_interval_seconds))
    while remaining > 0:
        chunk = min(interval, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk
        if remaining <= 0:
            break
        heartbeat_details = dict(details)
        heartbeat_details["retry_in_seconds"] = remaining
        _heartbeat(status, heartbeat_details, dsn)


async def async_main() -> None:
    configure_logging(service_name="websocket_stream")
    args = parse_args()
    settings = load_settings(args.env)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    resolution = validate_resolution(args.resolution or settings.default_resolution)
    validate_price_side(args.price_side or settings.default_price_side)
    retry_seconds = max(5, args.retry_seconds)
    max_retry_seconds = max(retry_seconds, args.max_retry_seconds)
    log_event(
        LOGGER,
        logging.INFO,
        "websocket.service.start",
        symbol=args.symbol,
        market=args.market,
        resolution=resolution,
        env=args.env or settings.env,
        retry_seconds=retry_seconds,
        max_retry_seconds=max_retry_seconds,
    )

    while True:
        loop_started = time.perf_counter()
        ws_client: CapitalOhlcWebSocketClient | None = None
        epic = args.epic or args.market or settings.default_epic
        sleep_status = "RECONNECTING"
        websocket_session_id = new_correlation_id("ws")
        try:
            authenticator = CapitalAuthenticator(settings)
            rest_client = CapitalRestClient(settings, authenticator=authenticator)
            rest_client.authenticate()
            selected = rest_client.resolve_market(args.market, args.epic, streaming=True)
            epic = selected["epic"]
            market_details_path = rest_client.save_market_details(epic)
            ws_client = CapitalOhlcWebSocketClient(
                settings,
                authenticator,
                epic=epic,
                resolution=resolution,
                symbol=args.symbol or args.market or epic,
                price_side=args.price_side or settings.default_price_side,
                postgres_dsn=args.postgres_dsn,
                heartbeat_callback=lambda status, details: _heartbeat(status, details, args.postgres_dsn),
                websocket_session_id=websocket_session_id,
            )

            _heartbeat(
                "OK",
                {
                    "state": "connected",
                    "epic": epic,
                    "resolution": resolution,
                    "symbol": ws_client.symbol,
                    "market_details_path": str(Path(market_details_path)),
                },
                args.postgres_dsn,
            )
            log_event(
                LOGGER,
                logging.INFO,
                "websocket.connect.start",
                websocket_session_id=websocket_session_id,
                symbol=ws_client.symbol,
                epic=epic,
                resolution=resolution,
                price_side=args.price_side or settings.default_price_side,
            )
            print(f"Selected epic: {epic}")
            print(f"Instrument: {selected.get('instrumentName', '')}")
            print(f"Market details: {Path(market_details_path)}")
            print(f"Streaming files: {ws_client.events_path}, {ws_client.csv_path}")
            print("Press Ctrl+C to unsubscribe and stop.")
            await ws_client.stream_forever()

            log_event(
                LOGGER,
                logging.WARNING,
                "websocket.reconnect.scheduled",
                websocket_session_id=websocket_session_id,
                symbol=ws_client.symbol,
                epic=epic,
                resolution=resolution,
                retry_in_seconds=retry_seconds,
                duration_ms=int((time.perf_counter() - loop_started) * 1000),
            )

            _heartbeat(
                "RECONNECTING",
                {
                    "state": "stopped_unexpectedly",
                    "epic": epic,
                    "resolution": resolution,
                    "retry_in_seconds": retry_seconds,
                },
                args.postgres_dsn,
            )
            LOGGER.warning("WebSocket stream ended unexpectedly; retrying in %s seconds", retry_seconds)
        except KeyboardInterrupt:
            if ws_client is not None:
                await ws_client.stop()
            log_event(
                LOGGER,
                logging.INFO,
                "websocket.service.stopped",
                websocket_session_id=websocket_session_id,
                symbol=args.symbol or args.market,
                epic=epic,
                resolution=resolution,
                duration_ms=int((time.perf_counter() - loop_started) * 1000),
            )
            _heartbeat(
                "OK",
                {
                    "state": "stopped_by_user",
                    "epic": epic,
                    "resolution": resolution,
                },
                args.postgres_dsn,
            )
            print("\nWebSocket stream stopped")
            print(f"Selected epic: {epic}")
            print(f"JSONL events: {settings.output_dir / f'ws_ohlc_events_{safe_epic_for_filename(epic)}_{resolution}.jsonl'}")
            print(f"Kronos rolling CSV: {settings.output_dir / f'kronos_stream_input_{safe_epic_for_filename(epic)}_{resolution}.csv'}")
            return
        except Exception as exc:  # noqa: BLE001
            status = "COOLDOWN" if isinstance(exc, RateLimitCooldownError) else ("RECONNECTING" if _is_transient_websocket_error(exc) else "ERROR")
            sleep_status = status
            log_event(
                LOGGER,
                logging.WARNING if status != "ERROR" else logging.ERROR,
                "websocket.cooldown" if status == "COOLDOWN" else "websocket.error",
                websocket_session_id=websocket_session_id,
                symbol=args.symbol or args.market,
                epic=epic,
                resolution=resolution,
                retry_in_seconds=retry_seconds,
                duration_ms=int((time.perf_counter() - loop_started) * 1000),
                error=str(exc),
            )
            _heartbeat(
                status,
                {
                    "state": "cooldown" if status == "COOLDOWN" else "error",
                    "epic": epic,
                    "resolution": resolution,
                    "error": str(exc),
                    "retry_in_seconds": retry_seconds,
                },
                args.postgres_dsn,
            )
            LOGGER.exception("WebSocket stream failed; retrying in %s seconds", retry_seconds)

        log_event(
            LOGGER,
            logging.INFO,
            "websocket.reconnect.scheduled",
            websocket_session_id=websocket_session_id,
            symbol=args.symbol or args.market,
            epic=epic,
            resolution=resolution,
            retry_in_seconds=retry_seconds,
            state="cooldown" if sleep_status == "COOLDOWN" else "retry_sleep",
        )

        await _sleep_with_heartbeat(
            total_seconds=retry_seconds,
            status="COOLDOWN" if sleep_status == "COOLDOWN" else "RECONNECTING",
            details={
                "state": "cooldown" if sleep_status == "COOLDOWN" else "retry_sleep",
                "epic": epic,
                "resolution": resolution,
            },
            dsn=args.postgres_dsn,
        )
        retry_seconds = min(max_retry_seconds, retry_seconds * 2)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
