from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from kronos_mapper import save_kronos_csv
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
    parser = argparse.ArgumentParser(description="Fetch a longer historical Capital.com range into Kronos CSV format.")
    parser.add_argument("--market", default="ETHUSD")
    parser.add_argument("--epic", default=None)
    parser.add_argument("--resolution", default="MINUTE_5")
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--from", dest="from_utc", default=None, help="UTC start override, e.g. 2026-01-29T00:00:00.")
    parser.add_argument("--to", dest="to_utc", default=None, help="UTC end override, defaults to latest completed data time.")
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"])
    parser.add_argument("--env", default="demo", choices=["demo", "live"])
    parser.add_argument("--chunk-points", type=int, default=900, help="Candles per request; keep below API max.")
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def _capital_time(value: pd.Timestamp) -> str:
    return value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S")


def _default_window(months: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    start = end - pd.DateOffset(months=months)
    return start, end


def main() -> None:
    configure_logging()
    args = parse_args()
    resolution = validate_resolution(args.resolution)
    price_side = validate_price_side(args.price_side)
    if args.chunk_points <= 0 or args.chunk_points > 1000:
        raise ValueError("--chunk-points must be between 1 and 1000")

    settings = load_settings(args.env)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    client = CapitalRestClient(settings)
    client.authenticate()
    selected = client.resolve_market(args.market, args.epic, streaming=False)
    epic = selected["epic"]
    client.save_market_details(epic)

    default_start, default_end = _default_window(args.months)
    start = pd.to_datetime(args.from_utc, utc=True) if args.from_utc else default_start
    end = pd.to_datetime(args.to_utc, utc=True) if args.to_utc else default_end
    if start >= end:
        raise ValueError("Start time must be before end time")

    step = pd.Timedelta(minutes=RESOLUTION_TO_MINUTES[resolution] * args.chunk_points)
    cursor = start
    frames: list[pd.DataFrame] = []
    while cursor < end:
        chunk_end = min(cursor + step, end)
        df = client.get_historical_prices(
            epic=epic,
            resolution=resolution,
            max_points=args.chunk_points,
            from_utc=_capital_time(cursor),
            to_utc=_capital_time(chunk_end),
            price_side=price_side,
            save_outputs=False,
            min_rows=1,
        )
        frames.append(df)
        print(f"Fetched {len(df)} rows: {format_local_timestamp(cursor)} -> {format_local_timestamp(chunk_end)}")
        cursor = chunk_end

    combined = pd.concat(frames, ignore_index=True)
    combined["timestamps"] = pd.to_datetime(combined["timestamps"], utc=True)
    combined = combined.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    output = (
        Path(args.output)
        if args.output
        else settings.output_dir
        / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}_{args.months}months.csv"
    )
    save_kronos_csv(combined, output, min_rows=1)
    print("\nHistorical range fetch complete")
    print(f"Epic: {epic}")
    print(f"Market: {selected.get('instrumentName', '')}")
    print(f"Resolution: {resolution}")
    print(f"Rows: {len(combined)}")
    print(f"Start: {format_local_timestamp(combined['timestamps'].iloc[0])}")
    print(f"End: {format_local_timestamp(combined['timestamps'].iloc[-1])}")
    print(f"CSV: {output}")


if __name__ == "__main__":
    main()
