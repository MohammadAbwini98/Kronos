from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from prediction_store import upsert_instrument, upsert_ohlcv_df
from time_utils import format_local_timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch latest Capital.com candles and generate a current/future Kronos forecast.")
    parser.add_argument("--market", default="ETHUSD")
    parser.add_argument("--epic", default=None)
    parser.add_argument("--resolution", default="MINUTE_5")
    parser.add_argument("--max", type=int, default=512, dest="max_points")
    parser.add_argument("--lookback", type=int, default=512)
    parser.add_argument("--pred-len", type=int, default=12)
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"])
    parser.add_argument("--env", default="demo", choices=["demo", "live"])
    parser.add_argument("--feature-set", default="auto", choices=["auto", "ohlc", "ohlcv", "ohlcva"])
    parser.add_argument("--repair-ohlc", action="store_true", help="Repair forecast high/low if raw Kronos output violates OHLC envelope.")
    parser.add_argument("--kronos-python", default=r"C:\AI\Kronos\.venv\Scripts\python.exe")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    return parser.parse_args()


def _read_window(csv_path: Path) -> tuple[str, str]:
    df = pd.read_csv(csv_path)
    return str(df.iloc[0]["timestamps"]), str(df.iloc[-1]["timestamps"])


def main() -> None:
    configure_logging()
    args = parse_args()
    resolution = validate_resolution(args.resolution)
    price_side = validate_price_side(args.price_side)
    settings = load_settings(args.env)
    settings.output_dir = Path(args.output_dir)
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    client = CapitalRestClient(settings)
    client.authenticate()
    selected = client.resolve_market(args.market, args.epic, streaming=False)
    epic = selected["epic"]
    symbol = args.symbol or args.market or epic
    market_name = selected.get("instrumentName") or ""
    client.save_market_details(epic)
    df = client.get_historical_prices(
        epic=epic,
        resolution=resolution,
        max_points=args.max_points,
        price_side=price_side,
        save_outputs=True,
        min_rows=min(args.lookback, args.max_points, 50),
    )
    upsert_instrument(
        symbol=symbol,
        epic=epic,
        market_name=market_name,
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
        source="latest_fetch",
        dsn=args.postgres_dsn,
    )
    input_path = settings.output_dir / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}.csv"
    last_input = df["timestamps"].iloc[-1]
    print("\nLatest input fetched")
    print(f"Epic: {epic}")
    print(f"Market: {market_name}")
    print(f"Rows: {len(df)}")
    print(f"PostgreSQL candles upserted: {stored_rows}")
    print(f"Last input candle: {format_local_timestamp(last_input)}")

    cmd = [
        args.kronos_python,
        str(Path("src") / "main_run_kronos_predict.py"),
        "--input",
        str(input_path),
        "--resolution",
        resolution,
        "--lookback",
        str(args.lookback),
        "--pred-len",
        str(args.pred_len),
        "--epic",
        epic,
        "--market-name",
        market_name,
        "--price-side",
        price_side,
        "--feature-set",
        args.feature_set,
        "--output-dir",
        str(settings.output_dir),
        "--postgres-dsn",
        args.postgres_dsn or "",
    ]
    if args.repair_ohlc:
        cmd.append("--repair-ohlc")

    result = subprocess.run(cmd, cwd=Path.cwd(), text=True)
    if result.returncode != 0 and not args.repair_ohlc:
        print("\nRaw Kronos output failed validation. Retrying with --repair-ohlc.")
        result = subprocess.run([*cmd, "--repair-ohlc"], cwd=Path.cwd(), text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    latest_metadata = sorted(settings.output_dir.glob(f"forecast_metadata_{safe_epic_for_filename(epic)}_{resolution}_*.json"))[-1]
    import json

    metadata = json.loads(latest_metadata.read_text(encoding="utf-8"))
    print("\nCurrent/future forecast ready")
    print(f"Forecast start: {metadata['forecast_start_timestamp']}")
    print(f"Forecast end: {metadata['forecast_end_timestamp']}")
    print(f"Forecast CSV: {metadata['forecast_csv_path']}")
    print(f"Metadata: {latest_metadata}")


if __name__ == "__main__":
    main()
