from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data_quality import analyze_ohlcv_quality, grade_meets_minimum
from dataset_snapshots import dataset_windows_overlap
from feature_engineering import generate_features
from forecast_scoring import score_signal_quality
from model_registry import artifact_manifest, model_version_id_for_path
from rate_limit_state import endpoint_class_for_path


class Pl002ServiceTests(unittest.TestCase):
    def test_data_quality_detects_missing_and_duplicates(self):
        df = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1, "amount": 1, "source": "historical"},
                {"timestamps": "2026-05-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1, "amount": 1, "source": "historical"},
                {"timestamps": "2026-05-01T00:15:00Z", "open": 1.5, "high": 2, "low": 1, "close": 1.6, "volume": 1, "amount": 1, "source": "latest_fetch"},
            ]
        )

        report = analyze_ohlcv_quality(df, resolution="MINUTE_5", expected_rows=4)

        self.assertEqual(1, report.duplicate_timestamp_count)
        self.assertGreaterEqual(report.missing_candle_count, 2)
        self.assertIn("historical", report.source_counts)
        self.assertFalse(grade_meets_minimum(report.quality_grade, "A"))

    def test_feature_generation_keeps_rolling_values_null_until_enough_history(self):
        timestamps = pd.date_range("2026-05-01T00:00:00Z", periods=14, freq="5min")
        df = pd.DataFrame(
            {
                "id": list(range(1, 15)),
                "timestamps": timestamps,
                "open": [100 + i for i in range(14)],
                "high": [101 + i for i in range(14)],
                "low": [99 + i for i in range(14)],
                "close": [100.5 + i for i in range(14)],
                "volume": [10 + i for i in range(14)],
                "amount": [20 + i for i in range(14)],
            }
        )

        features = generate_features(df)

        self.assertIsNone(features.loc[0, "rolling_volatility_12"])
        self.assertIsNotNone(features.loc[13, "atr_pct_14"])
        self.assertEqual("ASIA", features.loc[0, "session_label"])

    def test_signal_quality_scores_actionable_and_hold_cases(self):
        actionable = score_signal_quality(
            signal="LONG",
            confidence=0.7,
            expected_move_pct=0.2,
            cost_threshold_pct=0.05,
            scoring_summary={"status": "WIN", "direction_accuracy_pct": 66.0, "realized_movement_pct": 0.3, "average_movement_after_cost_pct": 0.25},
        )
        hold = score_signal_quality(
            signal="HOLD",
            confidence=0.1,
            expected_move_pct=0.01,
            cost_threshold_pct=0.05,
            scoring_summary={"status": "PENDING", "realized_movement_pct": 0.01},
        )

        self.assertTrue(actionable["actionable"])
        self.assertFalse(actionable["false_positive"])
        self.assertEqual("GOOD_HOLD", hold["hold_quality"])

    def test_dataset_overlap_and_model_helpers_are_deterministic(self):
        first = {"start_timestamp_utc": "2026-05-01T00:00:00Z", "end_timestamp_utc": "2026-05-02T00:00:00Z"}
        second = {"start_timestamp_utc": "2026-05-01T12:00:00Z", "end_timestamp_utc": "2026-05-03T00:00:00Z"}

        self.assertTrue(dataset_windows_overlap(first, second))
        self.assertEqual(
            model_version_id_for_path("Kronos", "C:/models/a"),
            model_version_id_for_path("Kronos", "C:/models/a"),
        )
        self.assertFalse(artifact_manifest(None)["complete"])

    def test_rate_limit_endpoint_classification(self):
        self.assertEqual("prices", endpoint_class_for_path("/prices/ETHUSD"))
        self.assertEqual("markets", endpoint_class_for_path("/markets"))
        self.assertEqual("sentiment", endpoint_class_for_path("/clientsentiment/ETHUSD"))


if __name__ == "__main__":
    unittest.main()
