from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import time

import pandas as pd

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, validate_price_side, validate_resolution
from historical_backfill import ensure_historical_candles
from logging_utils import log_event, new_correlation_id


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill and gap-fill Capital.com 5-minute candles into PostgreSQL.")
    parser.add_argument("--market", default=os.getenv("CAPITAL_DEFAULT_MARKET_SEARCH", "ETHUSD"))
    parser.add_argument("--epic", default=os.getenv("CAPITAL_DEFAULT_EPIC") or None)
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--resolution", default=os.getenv("HISTORICAL_BACKFILL_RESOLUTION", "MINUTE_5"))
    parser.add_argument("--price-side", default=os.getenv("CAPITAL_DEFAULT_PRICE_SIDE", "mid"), choices=["bid", "ask", "mid"])
    parser.add_argument("--days", type=int, default=int(os.getenv("HISTORICAL_BACKFILL_DAYS", "35")))
    parser.add_argument("--chunk-points", type=int, default=int(os.getenv("HISTORICAL_BACKFILL_CHUNK_POINTS", "900")))
    parser.add_argument("--source", default="historical")
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--status-file", default="output/historical_5m_backfill_status.json")
    parser.add_argument("--now", default=None, help="UTC timestamp override for tests/manual replays.")
    return parser.parse_args()


def main() -> None:
    configure_logging(service_name="historical_5m_backfill")
    args = parse_args()
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "historical_5m_backfill.start",
        request_id=request_id,
        market=args.market,
        epic=args.epic,
        symbol=args.symbol,
        resolution=args.resolution,
        days=args.days,
        chunk_points=args.chunk_points,
        source=args.source,
        env=args.env,
    )
    try:
        resolution = validate_resolution(args.resolution)
        if resolution != "MINUTE_5":
            raise ValueError("Historical automatic backfill is pinned to MINUTE_5.")
        price_side = validate_price_side(args.price_side)
        settings = load_settings(args.env)
        settings.output_dir.mkdir(parents=True, exist_ok=True)

        client = CapitalRestClient(settings)
        client.authenticate()
        selected = client.resolve_market(args.market, args.epic, streaming=False)
        client.save_market_details(selected["epic"])
        summary = ensure_historical_candles(
            client=client,
            selected_market=selected,
            symbol=args.symbol,
            resolution=resolution,
            price_side=price_side,
            days=args.days,
            chunk_points=args.chunk_points,
            source=args.source,
            dsn=args.postgres_dsn,
            now=pd.to_datetime(args.now, utc=True) if args.now else None,
        )
        status = {
            "enabled": True,
            "checked_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            **summary.to_dict(),
        }
        target = Path(args.status_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(status, indent=2), encoding="utf-8")

        log_event(
            LOGGER,
            logging.INFO,
            "historical_5m_backfill.completed",
            request_id=request_id,
            market=args.market,
            symbol=summary.symbol,
            epic=summary.epic,
            resolution=resolution,
            expected_rows=summary.expected_rows,
            existing_rows=summary.existing_rows,
            missing_rows=summary.missing_rows,
            fetched_rows=summary.fetched_rows,
            upserted_rows=summary.upserted_rows,
            status_file=str(target),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        print("\nHistorical 5m backfill complete")
        print(f"Symbol: {summary.symbol}")
        print(f"Epic: {summary.epic}")
        print(f"Window: {summary.window_start_utc} -> {summary.window_end_utc}")
        print(f"Expected rows: {summary.expected_rows}")
        print(f"Existing rows: {summary.existing_rows}")
        print(f"Missing rows before fetch: {summary.missing_rows}")
        print(f"Missing ranges fetched: {summary.missing_ranges}")
        print(f"Fetched rows: {summary.fetched_rows}")
        print(f"PostgreSQL upserted rows: {summary.upserted_rows}")
        print(f"Status: {target}")
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "historical_5m_backfill.error",
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
