from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config import DEFAULT_INSTRUMENT_SYMBOL
from prediction_store import load_recent_ohlcv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export PostgreSQL OHLCV candles for Kronos fine-tuning experiments.")
    parser.add_argument("--symbol", default=DEFAULT_INSTRUMENT_SYMBOL)
    parser.add_argument("--resolution", default="MINUTE_5")
    parser.add_argument("--price-side", default="mid")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--output", default="output/kronos_finetune_dataset.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_recent_ohlcv(
        symbol=args.symbol,
        resolution=args.resolution,
        price_side=args.price_side,
        limit=args.limit,
        dsn=args.postgres_dsn,
    )
    if df.empty:
        raise SystemExit("No PostgreSQL candles found for fine-tuning export.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"Fine-tuning dataset exported: {output}")
    print(f"Rows: {len(df)}")
    print(f"Window UTC: {df['timestamps'].iloc[0]} -> {df['timestamps'].iloc[-1]}")


if __name__ == "__main__":
    main()
