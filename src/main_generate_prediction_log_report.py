from __future__ import annotations

import argparse
from pathlib import Path

from prediction_log_report import generate_prediction_log_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an HTML report for a forecast prediction log/output.")
    parser.add_argument("--forecast", required=True)
    parser.add_argument("--metadata", default=None)
    parser.add_argument("--validation", default=None)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = generate_prediction_log_report(args.forecast, args.metadata, args.validation, args.output)
    print("\nPrediction log report generated")
    print(f"HTML: {Path(output)}")


if __name__ == "__main__":
    main()
