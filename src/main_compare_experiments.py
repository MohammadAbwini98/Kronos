from __future__ import annotations

import argparse
from pathlib import Path

from experiment_comparison import build_experiment_comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare forecast experiment settings from forecast_runs_index.csv.")
    parser.add_argument("--index", default="output/forecast_runs_index.csv")
    parser.add_argument("--output", default="output/experiment_comparison_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_experiment_comparison(args.index, args.output)
    summary = report["experiment_comparison"]
    print("\nExperiment comparison")
    print(f"Total runs: {summary['total_runs']}")
    print(f"Output: {Path(args.output)}")


if __name__ == "__main__":
    main()
