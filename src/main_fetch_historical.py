from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from logging_utils import log_event, new_correlation_id
from prediction_store import upsert_instrument, upsert_ohlcv_df


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Capital.com historical OHLC data for Kronos.")
    parser.add_argument("--market", default=None, help="Search term such as XAUUSD, XAU/USD, or Gold.")
    parser.add_argument("--epic", default=None, help="Explicit Capital.com epic. Skips market search.")
    parser.add_argument("--resolution", default=None, help="MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY, WEEK.")
    parser.add_argument("--max", type=int, default=512, dest="max_points", help="Maximum price points, default 512.")
    parser.add_argument("--from", default=None, dest="from_utc", help="UTC start, e.g. 2026-04-01T00:00:00.")
    parser.add_argument("--to", default=None, dest="to_utc", help="UTC end, e.g. 2026-04-02T00:00:00.")
    parser.add_argument("--price-side", default=None, choices=["bid", "ask", "mid"], help="Capital.com price side mapping.")
    parser.add_argument("--env", default=None, choices=["demo", "live"], help="Capital.com environment override.")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market or epic.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    return parser.parse_args()


def main() -> None:
    configure_logging(service_name="fetch_historical")
    args = parse_args()
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "fetch_historical.start",
        request_id=request_id,
        market=args.market,
        epic=args.epic,
        symbol=args.symbol,
        resolution=args.resolution,
        max_points=args.max_points,
        env=args.env,
    )
    try:
        settings = load_settings(args.env)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        resolution = validate_resolution(args.resolution or settings.default_resolution)
        price_side = validate_price_side(args.price_side or settings.default_price_side)

        client = CapitalRestClient(settings)
        client.authenticate()
        selected = client.resolve_market(args.market, args.epic, streaming=False)
        epic = selected["epic"]
        symbol = args.symbol or args.market or epic
        market_details_path = client.save_market_details(epic)
        df = client.get_historical_prices(
            epic=epic,
            resolution=resolution,
            max_points=args.max_points,
            from_utc=args.from_utc,
            to_utc=args.to_utc,
            price_side=price_side,
            save_outputs=True,
        )
        upsert_instrument(
            symbol=symbol,
            epic=epic,
            market_name=selected.get("instrumentName", ""),
            price_side=price_side,
            metadata=selected,
            dsn=args.postgres_dsn,
        )
        stored_rows = upsert_ohlcv_df(
            df,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            source="historical",
            dsn=args.postgres_dsn,
        )
        sentiment_path = client.save_client_sentiment(epic)
        raw_path = settings.output_dir / f"capital_raw_prices_{safe_epic_for_filename(epic)}_{resolution}.json"
        csv_path = settings.output_dir / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}.csv"

        log_event(
            LOGGER,
            logging.INFO,
            "fetch_historical.completed",
            request_id=request_id,
            market=args.market,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            rows=len(df),
            stored_rows=stored_rows,
            from_utc=args.from_utc,
            to_utc=args.to_utc,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        print("\nHistorical fetch complete")
        print(f"Selected epic: {epic}")
        print(f"Instrument: {selected.get('instrumentName', '')}")
        print(f"Rows: {len(df)}")
        print(f"PostgreSQL candles upserted: {stored_rows}")
        print(f"Market details: {Path(market_details_path)}")
        print(f"Raw prices: {raw_path}")
        print(f"Kronos CSV: {csv_path}")
        print(f"Client sentiment: {Path(sentiment_path)}")
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "fetch_historical.error",
            request_id=request_id,
            market=args.market,
            epic=args.epic,
            symbol=args.symbol,
            resolution=args.resolution,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
