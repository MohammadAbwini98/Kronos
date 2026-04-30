from __future__ import annotations

import argparse
from pathlib import Path

from baseline_forecasts import generate_baseline_forecast


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate simple baseline forecasts for Kronos comparison.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--resolution", required=True)
    parser.add_argument("--pred-len", type=int, default=12)
    parser.add_argument("--method", default="naive", choices=["naive", "drift", "moving_average", "last_direction"])
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = generate_baseline_forecast(args.input, args.output, args.resolution, args.pred_len, args.method)
    print("\nBaseline forecast generated")
    print(f"Method: {args.method}")
    print(f"Rows: {len(df)}")
    print(f"Output: {Path(args.output)}")


if __name__ == "__main__":
    main()
