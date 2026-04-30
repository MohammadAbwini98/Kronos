from __future__ import annotations

import argparse
from pathlib import Path

from forecast_review_report import generate_forecast_review_html


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an HTML forecast review dashboard.")
    parser.add_argument("--forecast", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--metadata", default=None)
    parser.add_argument("--quality-report", default=None)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = generate_forecast_review_html(
        forecast_csv_path=args.forecast,
        actual_csv_path=args.actual,
        metadata_json_path=args.metadata,
        quality_report_json_path=args.quality_report,
        output_html_path=args.output,
    )
    print("\nForecast review generated")
    print(f"HTML: {Path(output)}")


if __name__ == "__main__":
    main()
