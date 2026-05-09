from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import time

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from db import connect
from kronos_mapper import KRONOS_COLUMNS, save_kronos_csv
from logging_utils import log_event, new_correlation_id
import pandas as pd
from prediction_store import upsert_ohlcv_df
from time_utils import format_local_timestamp


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


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch actual Capital.com candles for a saved forecast window.")
    parser.add_argument("--metadata", required=True, help="Forecast metadata JSON.")
    parser.add_argument("--price-side", default=None, choices=["bid", "ask", "mid"], help="Override metadata price side.")
    parser.add_argument("--env", default=None, choices=["demo", "live"], help="Capital.com environment override.")
    parser.add_argument("--output", default=None, help="Actual candles CSV path. Defaults to timestamped output file.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--buffer-candles", type=int, default=2, help="Fetch extra candles around the forecast window, then trim locally.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow fetching partial actual window up to now for incremental validation.",
    )
    return parser.parse_args()


def _metadata_timestamp(path: Path) -> str:
    parts = path.stem.split("_")
    if parts:
        return parts[-1]
    return "UNKNOWN"


def _capital_utc_timestamp(value: str) -> str:
    timestamp = pd.to_datetime(value, utc=True)
    return timestamp.strftime("%Y-%m-%dT%H:%M:%S")


def _shift_timestamp(value: str, resolution: str, candles: int) -> str:
    timestamp = pd.to_datetime(value, utc=True)
    shifted = timestamp + pd.Timedelta(minutes=RESOLUTION_TO_MINUTES[resolution] * candles)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S")


def _expected_timestamps(start_ts: pd.Timestamp, end_ts: pd.Timestamp, resolution: str) -> set[pd.Timestamp]:
    return set(pd.date_range(start_ts, end_ts, freq=f"{RESOLUTION_TO_MINUTES[resolution]}min", tz="UTC"))


def _latest_closed_timestamp(now_utc: pd.Timestamp, resolution: str) -> pd.Timestamp:
    resolution_minutes = RESOLUTION_TO_MINUTES[resolution]
    timestamp = pd.to_datetime(now_utc, utc=True)
    floored = timestamp.floor(f"{resolution_minutes}min")
    return floored - pd.Timedelta(minutes=resolution_minutes)


def _covers_required_window(df: pd.DataFrame, start_ts: pd.Timestamp, end_ts: pd.Timestamp, resolution: str) -> bool:
    if df.empty:
        return False
    available = set(pd.to_datetime(df["timestamps"], utc=True))
    return _expected_timestamps(start_ts, end_ts, resolution).issubset(available)


def _load_actuals_from_db(
    *,
    symbol: str,
    epic: str,
    resolution: str,
    price_side: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    dsn: str | None,
) -> pd.DataFrame:
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
                """
                SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount
                FROM ohlcv_candles
                WHERE symbol = %s
                  AND epic = %s
                  AND resolution = %s
                  AND price_side = %s
                  AND timestamp_utc >= %s
                  AND timestamp_utc <= %s
                ORDER BY timestamp_utc
                """,
                (symbol, epic, resolution, price_side, start_ts.isoformat(), end_ts.isoformat()),
            ).fetchall()
    except Exception:  # noqa: BLE001 - REST fallback keeps the command useful without PostgreSQL.
        return pd.DataFrame(columns=KRONOS_COLUMNS)
    df = pd.DataFrame(rows, columns=KRONOS_COLUMNS)
    if df.empty:
        return df
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    for column in KRONOS_COLUMNS[1:]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)


def main() -> None:
    configure_logging(service_name="fetch_actual_for_forecast")
    args = parse_args()
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    metadata_path = Path(args.metadata)
    log_event(
        LOGGER,
        logging.INFO,
        "fetch_actual.start",
        request_id=request_id,
        metadata_path=str(metadata_path),
        allow_partial=args.allow_partial,
        buffer_candles=args.buffer_candles,
        env=args.env,
    )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        epic = metadata["epic"]
        resolution = validate_resolution(metadata["resolution"])
        price_side = validate_price_side(args.price_side or metadata.get("price_side", "mid"))
        forecast_start_raw = metadata["forecast_start_timestamp"]
        forecast_end_raw = metadata["forecast_end_timestamp"]
        forecast_end_ts = pd.to_datetime(metadata["forecast_end_timestamp"], utc=True)
        now_utc = pd.Timestamp.now(tz="UTC")
        if forecast_end_ts > now_utc and not args.allow_partial:
            raise RuntimeError(
                f"Forecast window has not completed yet. forecast_end={forecast_end_ts}, now_utc={now_utc}. "
                "Run this script after the forecast period has passed."
            )
        closed_end_ts = _latest_closed_timestamp(now_utc, resolution)
        effective_end_ts = min(forecast_end_ts, closed_end_ts) if args.allow_partial else forecast_end_ts
        timestamp = _metadata_timestamp(metadata_path)

        settings = load_settings(args.env)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        start_ts = pd.to_datetime(forecast_start_raw, utc=True)
        end_ts = effective_end_ts
        output = (
            Path(args.output)
            if args.output
            else settings.output_dir / f"actual_for_forecast_{safe_epic_for_filename(epic)}_{resolution}_{timestamp}.csv"
        )
        symbol = metadata.get("symbol") or epic
        db_df = _load_actuals_from_db(
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            start_ts=start_ts,
            end_ts=end_ts,
            dsn=args.postgres_dsn,
        )
        can_reuse_db = (args.allow_partial and not db_df.empty) or _covers_required_window(db_df, start_ts, end_ts, resolution)
        if can_reuse_db:
            output.parent.mkdir(parents=True, exist_ok=True)
            save_kronos_csv(db_df, output, min_rows=1)
            log_event(
                LOGGER,
                logging.INFO,
                "fetch_actual.completed",
                request_id=request_id,
                epic=epic,
                symbol=symbol,
                resolution=resolution,
                source="postgres_reuse",
                rows=len(db_df),
                output_path=str(output),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            print("\nActual candles reused from PostgreSQL")
            print(f"Epic: {epic}")
            print(f"Resolution: {resolution}")
            print(f"Forecast window: {format_local_timestamp(forecast_start_raw)} -> {format_local_timestamp(forecast_end_raw)}")
            print(f"Fetched through: {format_local_timestamp(effective_end_ts)}")
            print(f"Partial mode: {args.allow_partial}")
            print(f"Rows: {len(db_df)}")
            print(f"Actual CSV: {output}")
            return

        client = CapitalRestClient(settings)
        client.authenticate()
        to_anchor = str(effective_end_ts) if args.allow_partial else forecast_end_raw
        to_buffer = 0 if args.allow_partial else args.buffer_candles
        df = client.get_historical_prices(
            epic=epic,
            resolution=resolution,
            max_points=int(metadata.get("forecast_rows", 0)) + (args.buffer_candles * 2) + 10,
            from_utc=_shift_timestamp(forecast_start_raw, resolution, -args.buffer_candles),
            to_utc=_shift_timestamp(to_anchor, resolution, to_buffer),
            price_side=price_side,
            save_outputs=False,
            min_rows=1,
        )
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
        df = df[(df["timestamps"] >= start_ts) & (df["timestamps"] <= end_ts)].copy()
        if df.empty and not args.allow_partial:
            raise RuntimeError("Fetched actual candle buffer but no candles matched the forecast window after trimming.")
        output.parent.mkdir(parents=True, exist_ok=True)
        if df.empty:
            pd.DataFrame(columns=KRONOS_COLUMNS).to_csv(output, index=False)
            stored_rows = 0
        else:
            save_kronos_csv(df, output, min_rows=1)
            stored_rows = upsert_ohlcv_df(
                df,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                price_side=price_side,
                source="actual_validation",
                dsn=args.postgres_dsn,
            )
        log_event(
            LOGGER,
            logging.INFO,
            "fetch_actual.completed",
            request_id=request_id,
            epic=epic,
            symbol=symbol,
            resolution=resolution,
            source="capital_rest",
            rows=len(df),
            stored_rows=stored_rows,
            output_path=str(output),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        print("\nActual candles fetched")
        print(f"Epic: {epic}")
        print(f"Resolution: {resolution}")
        print(f"Forecast window: {format_local_timestamp(forecast_start_raw)} -> {format_local_timestamp(forecast_end_raw)}")
        print(f"Fetched through: {format_local_timestamp(effective_end_ts)}")
        print(f"Partial mode: {args.allow_partial}")
        print(f"Rows: {len(df)}")
        print(f"PostgreSQL actual candles upserted: {stored_rows}")
        print(f"Actual CSV: {output}")
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "fetch_actual.error",
            request_id=request_id,
            metadata_path=str(metadata_path),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
