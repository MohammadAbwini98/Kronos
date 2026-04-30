from __future__ import annotations

import argparse
from pathlib import Path

import orjson

from config import configure_logging, validate_price_side
from kronos_mapper import capital_prices_to_kronos_df, save_kronos_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert raw Capital.com prices JSON into Kronos CSV.")
    parser.add_argument("--input", required=True, help="Raw Capital.com prices JSON file.")
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"], help="Price side mapping.")
    parser.add_argument("--output", required=True, help="Destination Kronos CSV.")
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    price_side = validate_price_side(args.price_side)
    input_path = Path(args.input)
    output_path = Path(args.output)
    raw = orjson.loads(input_path.read_bytes())
    df = capital_prices_to_kronos_df(raw, price_side)
    save_kronos_csv(df, output_path)

    print("\nKronos input prepared")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Rows: {len(df)}")


if __name__ == "__main__":
    main()
