from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from model_experiments import (  # noqa: E402
    build_regime_labels,
    compute_baseline_delta,
    compute_confidence_calibration_buckets,
    compute_horizon_skill_analysis,
)
from prediction_input_quality import resolve_feature_experiment  # noqa: E402


def _candles(rows: int = 24) -> pd.DataFrame:
    timestamps = pd.date_range("2026-05-01T00:00:00Z", periods=rows, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": [100.0 + i * 0.1 for i in range(rows)],
            "high": [100.3 + i * 0.1 for i in range(rows)],
            "low": [99.8 + i * 0.1 for i in range(rows)],
            "close": [100.1 + i * 0.1 for i in range(rows)],
            "volume": [10.0 + (i % 4) for i in range(rows)],
            "amount": [0.0] * rows,
            "spread_pct": [0.01 + (0.001 * (i % 3)) for i in range(rows)],
        }
    )


class Phase4FeatureModeTests(unittest.TestCase):
    def test_feature_mode_is_resolved_and_persistable(self):
        selection = resolve_feature_experiment(_candles(), "ohlcv_only")

        self.assertEqual("OHLCV_ONLY", selection.feature_mode)
        self.assertEqual(["open", "high", "low", "close", "volume"], selection.feature_columns)
        self.assertFalse(selection.amount_available)
        self.assertFalse(selection.regime_context_used)

    def test_amount_is_not_silently_all_zero_in_ohlcva_mode(self):
        selection = resolve_feature_experiment(_candles(), "ohlcva_derived_amount")

        self.assertEqual("OHLCVA_DERIVED_AMOUNT", selection.feature_mode)
        self.assertEqual("close_x_volume", selection.amount_derivation_method)
        self.assertTrue(selection.amount_available)
        self.assertTrue((selection.dataframe["amount"].abs() > 0).all())

    def test_ohlcva_mode_blocks_when_derived_amount_would_be_zero(self):
        df = _candles()
        df["volume"] = 0.0

        with self.assertRaises(ValueError):
            resolve_feature_experiment(df, "ohlcva_derived_amount")


class Phase4MetricTests(unittest.TestCase):
    def test_horizon_metrics_are_separated(self):
        rows = [
            {"horizon_index": 1, "status": "WIN", "close_error": 1.0, "close_error_pct": 1.0, "movement_after_cost_pct": 0.2},
            {"horizon_index": 3, "status": "LOSS", "close_error": -2.0, "close_error_pct": -2.0, "movement_after_cost_pct": -0.1},
            {"horizon_index": 6, "status": "PENDING", "close_error": None, "close_error_pct": None},
            {"horizon_index": 12, "status": "WIN", "close_error": 0.5, "close_error_pct": 0.5, "movement_after_cost_pct": 0.1},
        ]

        metrics = compute_horizon_skill_analysis(rows, minimum_samples=1)
        by_horizon = {row["horizon"]: row for row in metrics}

        self.assertEqual(100.0, by_horizon[1]["directional_hit_rate_pct"])
        self.assertEqual(0.0, by_horizon[3]["directional_hit_rate_pct"])
        self.assertIsNone(by_horizon[6]["directional_hit_rate_pct"])
        self.assertEqual(100.0, by_horizon[12]["net_edge_hit_rate_pct"])

    def test_baseline_deltas_are_model_minus_baseline(self):
        self.assertEqual(7.5, compute_baseline_delta(57.5, 50.0))
        self.assertEqual(-5.0, compute_baseline_delta(45.0, 50.0))

    def test_regime_labels_use_only_past_and_current_data(self):
        base = _candles(rows=12)
        changed_future = base.copy()
        changed_future.loc[8:, "close"] = [500.0, 100.0, 600.0, 90.0]
        labels_base = build_regime_labels(base)
        labels_changed = build_regime_labels(changed_future)

        pd.testing.assert_series_equal(
            labels_base.loc[:5, "volatility_regime"],
            labels_changed.loc[:5, "volatility_regime"],
            check_names=False,
        )
        pd.testing.assert_series_equal(
            labels_base.loc[:5, "trend_range_regime"],
            labels_changed.loc[:5, "trend_range_regime"],
            check_names=False,
        )

    def test_confidence_buckets_do_not_claim_calibration_without_enough_samples(self):
        rows = [
            {
                "symbol": "ETHUSD",
                "resolution": "MINUTE_5",
                "horizon": 3,
                "signal_type": "LONG",
                "validation_status": "LONG",
                "volatility_regime": "NORMAL",
                "confidence": 0.76,
                "status": "WIN",
            }
        ]

        buckets = compute_confidence_calibration_buckets(rows, minimum_samples=3)

        self.assertEqual("0.7-0.8", buckets[0]["confidence_bucket"])
        self.assertFalse(buckets[0]["enough_samples"])
        self.assertIsNone(buckets[0]["observed_win_rate"])
        self.assertEqual("insufficient_samples_not_calibrated", buckets[0]["calibration_claim"])

    def test_confidence_bucket_observed_rate_requires_enough_samples(self):
        rows = [
            {
                "symbol": "ETHUSD",
                "resolution": "MINUTE_5",
                "horizon": 1,
                "signal_type": "SHORT",
                "validation_status": "SHORT",
                "volatility_regime": "HIGH",
                "confidence": 0.62,
                "status": status,
            }
            for status in ["WIN", "LOSS", "WIN"]
        ]

        buckets = compute_confidence_calibration_buckets(rows, minimum_samples=3)

        self.assertTrue(buckets[0]["enough_samples"])
        self.assertAlmostEqual(66.6666667, buckets[0]["observed_win_rate"], places=4)


class Phase4MigrationAndDocsTests(unittest.TestCase):
    def test_phase4_migration_contains_prediction_run_experiment_fields(self):
        sql = (ROOT / "migrations" / "018_phase4_model_experiments.sql").read_text(encoding="utf-8")

        for expected in (
            "feature_columns",
            "amount_derivation_method",
            "regime_context_used",
            "confidence_calibration_buckets",
            "model_experiment_reports",
        ):
            self.assertIn(expected, sql)

    def test_prediction_store_persists_feature_metadata_fields(self):
        source = (ROOT / "src" / "prediction_store.py").read_text(encoding="utf-8")

        for expected in (
            "feature_columns",
            "amount_available",
            "amount_derivation_method",
            "regime_context_used",
            "baseline_comparison_summary_json",
        ):
            self.assertIn(expected, source)

    def test_model_experiments_guide_exists(self):
        text = (ROOT / "docs" / "MODEL_EXPERIMENTS_GUIDE.md").read_text(encoding="utf-8")

        self.assertIn("OHLCVA_DERIVED_AMOUNT", text)
        self.assertIn("Fine-tuning remains blocked", text)


if __name__ == "__main__":
    unittest.main()
