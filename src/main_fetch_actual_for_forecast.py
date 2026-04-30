from __future__ import annotations

import argparse
import json
from pathlib import Path

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from kronos_mapper import save_kronos_csv
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch actual Capital.com candles for a saved forecast window.")
    parser.add_argument("--metadata", required=True, help="Forecast metadata JSON.")
    parser.add_argument("--price-side", default=None, choices=["bid", "ask", "mid"], help="Override metadata price side.")
    parser.add_argument("--env", default=None, choices=["demo", "live"], help="Capital.com environment override.")
    parser.add_argument("--output", default=None, help="Actual candles CSV path. Defaults to timestamped output file.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--buffer-candles", type=int, default=2, help="Fetch extra candles around the forecast window, then trim locally.")
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


def main() -> None:
    configure_logging()
    args = parse_args()
    metadata_path = Path(args.metadata)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    epic = metadata["epic"]
    resolution = validate_resolution(metadata["resolution"])
    price_side = validate_price_side(args.price_side or metadata.get("price_side", "mid"))
    forecast_start_raw = metadata["forecast_start_timestamp"]
    forecast_end_raw = metadata["forecast_end_timestamp"]
    forecast_start = _capital_utc_timestamp(forecast_start_raw)
    forecast_end = _capital_utc_timestamp(forecast_end_raw)
    forecast_end_ts = pd.to_datetime(metadata["forecast_end_timestamp"], utc=True)
    now_utc = pd.Timestamp.now(tz="UTC")
    if forecast_end_ts > now_utc:
        raise RuntimeError(
            f"Forecast window has not completed yet. forecast_end={forecast_end_ts}, now_utc={now_utc}. "
            "Run this script after the forecast period has passed."
        )
    timestamp = _metadata_timestamp(metadata_path)

    settings = load_settings(args.env)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    client = CapitalRestClient(settings)
    client.authenticate()
    df = client.get_historical_prices(
        epic=epic,
        resolution=resolution,
        max_points=int(metadata.get("forecast_rows", 0)) + (args.buffer_candles * 2) + 10,
        from_utc=_shift_timestamp(forecast_start_raw, resolution, -args.buffer_candles),
        to_utc=_shift_timestamp(forecast_end_raw, resolution, args.buffer_candles),
        price_side=price_side,
        save_outputs=False,
        min_rows=1,
    )
    start_ts = pd.to_datetime(forecast_start_raw, utc=True)
    end_ts = pd.to_datetime(forecast_end_raw, utc=True)
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df[(df["timestamps"] >= start_ts) & (df["timestamps"] <= end_ts)].copy()
    if df.empty:
        raise RuntimeError("Fetched actual candle buffer but no candles matched the forecast window after trimming.")
    output = (
        Path(args.output)
        if args.output
        else settings.output_dir / f"actual_for_forecast_{safe_epic_for_filename(epic)}_{resolution}_{timestamp}.csv"
    )
    save_kronos_csv(df, output, min_rows=1)
    stored_rows = upsert_ohlcv_df(
        df,
        symbol=metadata.get("symbol") or epic,
        epic=epic,
        resolution=resolution,
        price_side=price_side,
        source="actual_validation",
        dsn=args.postgres_dsn,
    )
    print("\nActual candles fetched")
    print(f"Epic: {epic}")
    print(f"Resolution: {resolution}")
    print(f"Forecast window: {format_local_timestamp(forecast_start_raw)} -> {format_local_timestamp(forecast_end_raw)}")
    print(f"Rows: {len(df)}")
    print(f"PostgreSQL actual candles upserted: {stored_rows}")
    print(f"Actual CSV: {output}")


if __name__ == "__main__":
    main()
