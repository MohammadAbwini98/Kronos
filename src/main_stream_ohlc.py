from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from capital_auth import CapitalAuthenticator
from capital_rest_client import CapitalRestClient
from capital_ws_ohlc_client import CapitalOhlcWebSocketClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream Capital.com OHLC candles into a Kronos-ready rolling CSV.")
    parser.add_argument("--market", default=None, help="Search term such as ETHUSD, ETH/USD, or Ethereum.")
    parser.add_argument("--epic", default=None, help="Explicit Capital.com epic. Skips market search.")
    parser.add_argument("--resolution", default=None, help="MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY, WEEK.")
    parser.add_argument("--price-side", default=None, choices=["bid", "ask", "mid"], help="Accepted for CLI symmetry; stream payload is used as delivered.")
    parser.add_argument("--env", default=None, choices=["demo", "live"], help="Capital.com environment override.")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market or epic.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    return parser.parse_args()


async def async_main() -> None:
    configure_logging()
    args = parse_args()
    settings = load_settings(args.env)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    resolution = validate_resolution(args.resolution or settings.default_resolution)
    validate_price_side(args.price_side or settings.default_price_side)

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
    )

    print(f"Selected epic: {epic}")
    print(f"Instrument: {selected.get('instrumentName', '')}")
    print(f"Market details: {Path(market_details_path)}")
    print(f"Streaming files: {ws_client.events_path}, {ws_client.csv_path}")
    print("Press Ctrl+C to unsubscribe and stop.")

    try:
        await ws_client.stream_forever()
    except KeyboardInterrupt:
        await ws_client.stop()
    finally:
        print("\nWebSocket stream stopped")
        print(f"Selected epic: {epic}")
        print(f"JSONL events: {settings.output_dir / f'ws_ohlc_events_{safe_epic_for_filename(epic)}_{resolution}.jsonl'}")
        print(f"Kronos rolling CSV: {settings.output_dir / f'kronos_stream_input_{safe_epic_for_filename(epic)}_{resolution}.csv'}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
