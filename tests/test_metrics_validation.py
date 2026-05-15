from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from forecast_scoring import score_forecast_against_actuals
from metrics_validation import (
    compute_baseline_comparisons,
    compute_executed_trade_performance,
    compute_forecast_quality_metrics,
    terminal_direction_outcome,
)


class MetricsValidationTests(unittest.TestCase):
    def test_forecast_metrics_do_not_count_pending_rows_as_losses(self):
        metrics = compute_forecast_quality_metrics(
            [
                {"horizon_index": 1, "status": "WIN", "close_error": 1.0, "close_error_pct": 1.0},
                {"horizon_index": 2, "status": "PENDING", "close_error": None, "close_error_pct": None},
                {"horizon_index": 3, "status": "NEEDS_MORE_SAMPLES", "close_error": None, "close_error_pct": None},
            ]
        )

        self.assertEqual(1, metrics["wins"])
        self.assertEqual(0, metrics["losses"])
        self.assertEqual(2, metrics["pending"])
        self.assertEqual(100.0, metrics["directional_forecast_hit_rate_pct"])

    def test_hold_or_skipped_predictions_are_not_counted_as_executed_wins(self):
        metrics = compute_executed_trade_performance(
            [
                {
                    "status": "SKIPPED",
                    "final_outcome": "WIN",
                    "outcome_finalized_at": datetime.now(timezone.utc),
                    "net_pnl": 10,
                },
                {
                    "status": "VALIDATION_FAILED",
                    "final_outcome": "WIN",
                    "outcome_finalized_at": datetime.now(timezone.utc),
                    "net_pnl": 10,
                },
            ]
        )

        self.assertEqual(0, metrics["closed_trade_count"])
        self.assertIsNone(metrics["executed_trade_win_rate_pct"])

    def test_partial_windows_remain_outside_final_forecast_quality(self):
        metrics = compute_forecast_quality_metrics(
            [
                {
                    "horizon_index": 1,
                    "status": "WIN",
                    "validation_state": "PARTIAL_PROGRESS",
                    "actual_window_complete": False,
                    "close_error": 0.5,
                    "close_error_pct": 0.5,
                },
                {
                    "horizon_index": 2,
                    "status": "PENDING",
                    "validation_state": "PARTIAL_PROGRESS",
                    "close_error": 0.5,
                    "close_error_pct": 0.5,
                },
                {"horizon_index": 3, "status": "PENDING", "validation_state": "NEEDS_MORE_SAMPLES"},
            ]
        )

        self.assertEqual(0, metrics["sample_count"])
        self.assertIsNone(metrics["directional_forecast_hit_rate_pct"])

    def test_executed_win_rate_uses_only_closed_finalized_trades(self):
        finalized_at = datetime.now(timezone.utc)
        metrics = compute_executed_trade_performance(
            [
                {"status": "CLOSED", "final_outcome": "WIN", "outcome_finalized_at": finalized_at, "net_pnl": 12},
                {"status": "CLOSED", "final_outcome": "LOSS", "outcome_finalized_at": finalized_at, "net_pnl": -4},
                {"status": "OPEN", "final_outcome": "WIN", "outcome_finalized_at": finalized_at, "net_pnl": 20},
                {"status": "CLOSED", "final_outcome": "UNKNOWN", "outcome_finalized_at": None, "net_pnl": None},
            ]
        )

        self.assertEqual(3, metrics["closed_trade_count"])
        self.assertEqual(2, metrics["finalized_trade_count"])
        self.assertEqual(1, metrics["unknown_outcome_count"])
        self.assertEqual(50.0, metrics["executed_trade_win_rate_pct"])
        self.assertEqual(4.0, metrics["expectancy"])

    def test_baselines_use_only_history_available_at_prediction_time(self):
        input_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T00:00:00Z", periods=20, freq="5min"),
                "open": range(100, 120),
                "high": range(101, 121),
                "low": range(99, 119),
                "close": range(100, 120),
                "volume": [1] * 20,
                "amount": [1] * 20,
            }
        )
        forecast_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T01:40:00Z", periods=2, freq="5min"),
                "close": [121, 122],
            }
        )
        actual_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T01:40:00Z", periods=2, freq="5min"),
                "close": [80, 70],
            }
        )

        rows = compute_baseline_comparisons(input_df, forecast_df, actual_df, last_input_close=119)
        momentum = next(row for row in rows if row["baseline_name"] == "naive_momentum")
        terminal = momentum["details"]["terminal_direction"]

        self.assertEqual("UP", terminal["terminal_predicted_direction"])
        self.assertEqual("DOWN", terminal["terminal_actual_direction"])

    def test_terminal_direction_and_per_horizon_direction_are_independent(self):
        forecast = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 90.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 105.0},
            ]
        )
        actual = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 95.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 94.0},
            ]
        )

        per_horizon = score_forecast_against_actuals(forecast, actual, last_input_close=100.0)
        terminal = terminal_direction_outcome(forecast, actual, last_input_close=100.0)

        self.assertEqual(["WIN", "LOSS"], [row["status"] for row in per_horizon["rows"]])
        self.assertEqual("UP", terminal["terminal_predicted_direction"])
        self.assertEqual("DOWN", terminal["terminal_actual_direction"])
        self.assertEqual("LOSS", terminal["terminal_direction_status"])


class MigrationCoverageTests(unittest.TestCase):
    def test_phase1_migration_adds_outcome_and_validation_tables(self):
        sql = (ROOT / "migrations" / "015_phase1_metric_trust.sql").read_text(encoding="utf-8")

        for expected in (
            "entry_price",
            "exit_price",
            "gross_pnl",
            "net_pnl",
            "final_outcome",
            "validation_status_at_execution",
            "validation_state",
            "actual_window_complete",
            "terminal_direction_status",
            "baseline_comparison_metrics",
        ):
            self.assertIn(expected, sql)


if __name__ == "__main__":
    unittest.main()
