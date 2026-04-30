from __future__ import annotations

import argparse
import json
from pathlib import Path

from cumulative_forecast_report import build_cumulative_report, scan_and_build_cumulative_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cumulative forecast quality report from many quality reports.")
    parser.add_argument("--input-dir", default="output", help="Directory to scan for quality reports.")
    parser.add_argument("--pattern", default="forecast_quality_report_*.json", help="Glob pattern used with --input-dir.")
    parser.add_argument("--reports", nargs="*", default=None, help="Explicit report paths. Overrides --input-dir.")
    parser.add_argument("--output", default="output/cumulative_forecast_quality_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.reports:
        report = build_cumulative_report(args.reports)
    else:
        report = scan_and_build_cumulative_report(args.input_dir, args.pattern)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = report["cumulative_forecast_quality_report"]
    print("\nCumulative forecast quality")
    print(f"Total forecasts evaluated: {summary['total_forecasts_evaluated']}")
    print(f"Total matched candles: {summary['total_matched_candles']}")
    print(f"Average MAE: {summary['average_mae']}")
    print(f"Average RMSE: {summary['average_rmse']}")
    print(f"Average MAPE: {summary['average_mape']}")
    print(f"Average direction accuracy: {summary['average_direction_accuracy']}")
    print(f"Overall quality status: {summary['overall_quality_status']}")
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
