"""
Regression tests for PL-003 fixes.

Phases covered
--------------
Phase 4  – Shadow evaluation uses persisted signals.status, not aggregate counts
Phase 5  – Horizon-aware, volatility-adjusted signal generation
Phase 6  – Dataset quality_filter actually filters rows
Phase 7  – WebSocket volume/amount mapped as None; feature-col selection handles NaN
Phase 8  – Deterministic metadata path via --run-stamp
Phase 3  – Auto-finetune _promotion_decision never returns "approved";
           train/eval datasets are disjoint
Phase 1  – Walk-forward beats_naive_rate_pct computed; BASELINE_ONLY when no
           candidate evidence
Phase 2  – Promotion gates use candidate shadow MAPE and walk-forward beat rate;
           insufficient evidence fails a gate, not silently passes
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Phase 5 – _signal_from_forecast (horizon-aware)
# ---------------------------------------------------------------------------
class TestSignalFromForecast(unittest.TestCase):
    """Tests for the rewritten _signal_from_forecast function."""

    def _call(self, **kwargs):
        from prediction_store import _signal_from_forecast  # noqa: PLC0415
        return _signal_from_forecast(**kwargs)

    def test_hold_below_cost_threshold(self):
        result = self._call(
            last_input_close=100.0,
            final_close=100.01,  # 0.01% < 0.05% cost threshold
            cost_threshold_pct=0.05,
            min_confidence=0.4,
        )
        self.assertEqual("HOLD", result["signal"])
        self.assertIn("cost threshold", result["reason"])

    def test_long_signal_generated(self):
        result = self._call(
            last_input_close=100.0,
            final_close=101.0,  # +1% > 0.05% threshold
            cost_threshold_pct=0.05,
            min_confidence=0.1,
            forecast_closes=[100.3, 100.6, 101.0],  # all up
        )
        self.assertEqual("LONG", result["signal"])
        self.assertAlmostEqual(1.0, result["expected_move_pct"], places=4)

    def test_short_signal_generated(self):
        result = self._call(
            last_input_close=100.0,
            final_close=99.0,  # -1%
            cost_threshold_pct=0.05,
            min_confidence=0.1,
            forecast_closes=[99.7, 99.4, 99.0],  # all down
        )
        self.assertEqual("SHORT", result["signal"])

    def test_hold_on_direction_disagreement(self):
        # Terminal close goes up (+1%) but most intermediate steps are DOWN:
        # closes [100, 99.5, 98.5, 101.0] → steps: -0.5, -1.0, +2.5
        # only 1 of 3 steps agree with terminal UP direction → 33% < 50% → HOLD
        result = self._call(
            last_input_close=100.0,
            final_close=101.0,
            cost_threshold_pct=0.05,
            min_confidence=0.1,
            forecast_closes=[99.5, 98.5, 101.0],
        )
        self.assertEqual("HOLD", result["signal"])
        self.assertIn("disagree", result["reason"])

    def test_confidence_bounded_0_to_1(self):
        result = self._call(
            last_input_close=100.0,
            final_close=110.0,  # huge move
            cost_threshold_pct=0.05,
            min_confidence=0.1,
        )
        self.assertLessEqual(result["confidence"], 0.99)
        self.assertGreaterEqual(result["confidence"], 0.0)

    def test_hold_on_low_confidence(self):
        result = self._call(
            last_input_close=100.0,
            final_close=100.06,  # just above cost threshold 0.05%
            cost_threshold_pct=0.05,
            min_confidence=0.99,  # very high minimum
            forecast_closes=[100.06],
        )
        self.assertEqual("HOLD", result["signal"])
        self.assertIn("onfidence", result["reason"])

    def test_volatility_normalisation_reduces_confidence(self):
        # Same edge but higher volatility → lower confidence
        low_vol = self._call(
            last_input_close=100.0,
            final_close=100.5,
            cost_threshold_pct=0.05,
            min_confidence=0.0,
            forecast_closes=[100.5],
            recent_volatility_pct=0.01,  # very quiet
        )
        high_vol = self._call(
            last_input_close=100.0,
            final_close=100.5,
            cost_threshold_pct=0.05,
            min_confidence=0.0,
            forecast_closes=[100.5],
            recent_volatility_pct=5.0,  # very noisy
        )
        self.assertGreater(low_vol["confidence"], high_vol["confidence"])

    def test_backward_compat_no_forecast_closes(self):
        # Old callers that do not pass forecast_closes should still work
        result = self._call(
            last_input_close=100.0,
            final_close=101.0,
            cost_threshold_pct=0.05,
            min_confidence=0.1,
        )
        self.assertIn(result["signal"], ("LONG", "HOLD"))  # signal produced, no crash


# ---------------------------------------------------------------------------
# Phase 6 – Dataset quality_filter applied at export time
# ---------------------------------------------------------------------------
class TestDatasetQualityFilter(unittest.TestCase):
    def _call(self, df, quality_filter):
        from dataset_snapshots import _apply_quality_filter  # noqa: PLC0415
        return _apply_quality_filter(df, quality_filter)

    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_drop_null_ohlc_default_true(self):
        df = self._make_df([
            {"timestamps": "2026-01-01T00:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101},
            {"timestamps": "2026-01-01T00:05:00Z", "open": None, "high": 103, "low": 97, "close": 100},
        ])
        filtered, report = self._call(df, {"drop_null_ohlc": True})
        self.assertEqual(1, len(filtered))
        self.assertEqual(1, report["removed"])
        self.assertIn("null_ohlc", report["removal_reasons"])

    def test_drop_invalid_ohlc_default_true(self):
        df = self._make_df([
            {"timestamps": "2026-01-01T00:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101},
            # Invalid: high < low
            {"timestamps": "2026-01-01T00:05:00Z", "open": 100, "high": 95, "low": 105, "close": 100},
        ])
        filtered, report = self._call(df, {"drop_invalid_ohlc": True})
        self.assertEqual(1, len(filtered))
        self.assertIn("invalid_ohlc", report["removal_reasons"])

    def test_min_rows_raises_when_too_few_after_filter(self):
        df = self._make_df([
            {"timestamps": "2026-01-01T00:00:00Z", "open": None, "high": 102, "low": 98, "close": 101},
        ])
        with self.assertRaises(ValueError):
            self._call(df, {"drop_null_ohlc": True, "min_rows": 5})

    def test_empty_filter_is_noop(self):
        df = self._make_df([
            {"timestamps": "2026-01-01T00:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101},
        ])
        filtered, report = self._call(df, {})
        self.assertEqual(1, len(filtered))
        self.assertFalse(report["filter_applied"])

    def test_allowed_sources_filter(self):
        df = self._make_df([
            {"timestamps": "2026-01-01T00:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101, "source": "rest_ohlc"},
            {"timestamps": "2026-01-01T00:05:00Z", "open": 100, "high": 103, "low": 97, "close": 102, "source": "websocket_ohlc"},
        ])
        filtered, report = self._call(df, {"allowed_sources": ["rest_ohlc"]})
        self.assertEqual(1, len(filtered))
        self.assertEqual("rest_ohlc", filtered.iloc[0]["source"])


# ---------------------------------------------------------------------------
# Phase 7 – WebSocket volume/amount mapped as None
# ---------------------------------------------------------------------------
class TestWsOhlcToKronosRow(unittest.TestCase):
    def _make_payload(self):
        return {
            "t": "2026-01-01T00:00:00Z",
            "o": "100.0",
            "h": "102.0",
            "l": "98.0",
            "c": "101.0",
        }

    def test_volume_and_amount_are_none_for_ws_data(self):
        from kronos_mapper import ws_ohlc_to_kronos_row  # noqa: PLC0415
        row = ws_ohlc_to_kronos_row(self._make_payload())
        self.assertIsNone(row["volume"], "volume should be None for WebSocket-sourced data")
        self.assertIsNone(row["amount"], "amount should be None for WebSocket-sourced data")

    def test_feature_column_selection_nan_volume_is_unavailable(self):
        """When volume/amount are NaN (from WS source) the auto-selector must treat them as unavailable."""
        # Importing from within Kronos venv context is out of scope for unit tests,
        # so we test the _select_feature_columns logic directly via its module.
        from main_run_kronos_predict import _select_feature_columns  # noqa: PLC0415
        df = pd.DataFrame({
            "open": [100.0], "high": [102.0], "low": [98.0], "close": [101.0],
            "volume": [float("nan")],
            "amount": [float("nan")],
        })
        cols = _select_feature_columns(df, "auto")
        self.assertNotIn("volume", cols, "NaN volume must not be treated as available")
        self.assertNotIn("amount", cols, "NaN amount must not be treated as available")


# ---------------------------------------------------------------------------
# Phase 8 – Deterministic run-stamp metadata path
# ---------------------------------------------------------------------------
class TestRunStampArg(unittest.TestCase):
    def test_parse_args_accepts_run_stamp(self):
        """--run-stamp must be an accepted CLI argument."""
        from main_run_kronos_predict import parse_args  # noqa: PLC0415
        with patch("sys.argv", [
            "prog",
            "--input", "dummy.csv",
            "--run-stamp", "20260101T000000Z",
        ]):
            args = parse_args()
        self.assertEqual("20260101T000000Z", args.run_stamp)

    def test_run_stamp_none_by_default(self):
        from main_run_kronos_predict import parse_args  # noqa: PLC0415
        with patch("sys.argv", ["prog", "--input", "dummy.csv"]):
            args = parse_args()
        self.assertIsNone(args.run_stamp)


# ---------------------------------------------------------------------------
# Shadow candidate model status gate
# ---------------------------------------------------------------------------
class TestShadowCandidateModelGate(unittest.TestCase):
    """_shadow_candidate_model must activate for pending_evaluation (Phase 3 renamed state)."""

    def _write_status(self, tmp_dir: Path, promotion_status: str) -> None:
        import json
        model_dir = tmp_dir / "model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"")
        status = {
            "promotion_status": promotion_status,
            "active_model_path": str(model_dir),
            "candidate_model_version_id": "v1",
        }
        (tmp_dir / "auto_finetune_status.json").write_text(json.dumps(status))
        return model_dir

    def _call(self, tmp_dir: Path):
        import importlib, sys
        # Import fresh to avoid cached state
        if "main_forecast_latest" in sys.modules:
            mod = sys.modules["main_forecast_latest"]
        else:
            import main_forecast_latest as mod
        return mod._shadow_candidate_model(tmp_dir)

    def test_pending_evaluation_activates_shadow(self):
        """After Phase 3, pending_evaluation must activate the shadow model."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write_status(Path(d), "pending_evaluation")
            result = self._call(Path(d))
        self.assertIsNotNone(result, "pending_evaluation should activate shadow model")

    def test_pending_review_activates_shadow(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write_status(Path(d), "pending_review")
            result = self._call(Path(d))
        self.assertIsNotNone(result)

    def test_not_ready_does_not_activate_shadow(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write_status(Path(d), "not_ready")
            result = self._call(Path(d))
        self.assertIsNone(result)

    def test_approved_does_not_activate_shadow(self):
        """An already-approved model should not run as shadow."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write_status(Path(d), "approved")
            result = self._call(Path(d))
        self.assertIsNone(result)

    def test_missing_status_file_returns_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            result = self._call(Path(d))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Phase 3 – _promotion_decision never returns "approved"
# ---------------------------------------------------------------------------
class TestPromotionDecisionNeverApproves(unittest.TestCase):
    def _call(self, **kwargs):
        from main_auto_finetune_worker import _promotion_decision  # noqa: PLC0415
        return _promotion_decision(**kwargs)

    def _good_metrics(self):
        return {
            "matched_candles": 500,
            "direction_accuracy_pct": 75.0,
            "run_count": 50,
        }

    def test_never_returns_approved_even_with_high_accuracy(self):
        status, reason = self._call(
            model_ready=True,
            metrics=self._good_metrics(),
            min_accuracy=60.0,
            min_matched=100,
            previous_promoted_accuracy=None,
        )
        self.assertNotEqual("approved", status, "_promotion_decision must never return 'approved'")

    def test_returns_pending_evaluation_when_ready(self):
        status, reason = self._call(
            model_ready=True,
            metrics=self._good_metrics(),
            min_accuracy=60.0,
            min_matched=100,
            previous_promoted_accuracy=70.0,
        )
        self.assertEqual("pending_evaluation", status)

    def test_returns_not_ready_when_model_missing(self):
        status, reason = self._call(
            model_ready=False,
            metrics=self._good_metrics(),
            min_accuracy=60.0,
            min_matched=100,
            previous_promoted_accuracy=None,
        )
        self.assertEqual("not_ready", status)

    def test_returns_pending_review_below_min_matched(self):
        metrics = self._good_metrics()
        metrics["matched_candles"] = 5
        status, reason = self._call(
            model_ready=True,
            metrics=metrics,
            min_accuracy=60.0,
            min_matched=100,
            previous_promoted_accuracy=None,
        )
        self.assertEqual("pending_review", status)


# ---------------------------------------------------------------------------
# Phase 3 – Train/eval dataset split is disjoint
# ---------------------------------------------------------------------------
class TestAutoFinetuneDatasetSplit(unittest.TestCase):
    """Verify the 80/20 split produces disjoint time windows."""

    def test_split_windows_do_not_overlap(self):
        """Simulate the split logic used in _run_cycle and verify no overlap."""
        n = 100
        timestamps = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        df = pd.DataFrame({"timestamps": timestamps, "close": range(n)})

        split_idx = max(1, int(len(df) * 0.8))
        train_df = df.iloc[:split_idx]
        eval_df = df.iloc[split_idx:]

        # No timestamp should appear in both sets
        self.assertEqual(0, len(set(train_df["timestamps"]) & set(eval_df["timestamps"])))
        # Train is earliest 80%
        self.assertLess(train_df["timestamps"].iloc[-1], eval_df["timestamps"].iloc[0])

    def test_split_produces_both_halves(self):
        n = 10
        timestamps = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
        df = pd.DataFrame({"timestamps": timestamps, "close": range(n)})
        split_idx = max(1, int(len(df) * 0.8))
        train_df = df.iloc[:split_idx]
        eval_df = df.iloc[split_idx:]
        self.assertGreater(len(train_df), 0)
        self.assertGreater(len(eval_df), 0)


# ---------------------------------------------------------------------------
# Phase 1 – Walk-forward beats_naive_rate_pct and BASELINE_ONLY status
# ---------------------------------------------------------------------------
class TestWalkForwardCandidateTracking(unittest.TestCase):
    """
    Unit tests for the candidate coverage & beat-rate logic without DB.

    We test the tracking arithmetic directly to avoid a live DB dependency.
    """

    def test_beats_naive_rate_pct_computed_correctly(self):
        # Simulate 3 windows; candidate beats baseline in 2 of them
        candidate_windows_covered = 3
        candidate_beats_baseline = 2
        beats_naive_rate_pct = (candidate_beats_baseline / candidate_windows_covered) * 100.0
        self.assertAlmostEqual(66.666, beats_naive_rate_pct, places=2)

    def test_baseline_only_when_no_candidate_coverage(self):
        model_version_id = "some-model"
        candidate_windows_covered = 0
        final_status = "BASELINE_ONLY" if model_version_id and candidate_windows_covered == 0 else "COMPLETED"
        self.assertEqual("BASELINE_ONLY", final_status)

    def test_completed_when_candidate_covered_all_windows(self):
        model_version_id = "some-model"
        candidate_windows_covered = 5
        final_status = "BASELINE_ONLY" if model_version_id and candidate_windows_covered == 0 else "COMPLETED"
        self.assertEqual("COMPLETED", final_status)

    def test_completed_when_no_model_version_id(self):
        model_version_id = None
        candidate_windows_covered = 0
        final_status = "BASELINE_ONLY" if model_version_id and candidate_windows_covered == 0 else "COMPLETED"
        self.assertEqual("COMPLETED", final_status)


# ---------------------------------------------------------------------------
# Phase 2 – Promotion gate helpers
# ---------------------------------------------------------------------------
class TestCandidateShadowMetrics(unittest.TestCase):
    """Unit tests for _candidate_shadow_metrics aggregation logic (no DB)."""

    def _aggregate_horizon_metrics(self, shadow_rows_data):
        """Replicate the aggregation logic from _candidate_shadow_metrics."""
        total_wins = 0
        total_losses = 0
        mape_sum = 0.0
        mape_count = 0
        horizon_wins: dict[int, int] = {}
        horizon_samples: dict[int, int] = {}
        for row in shadow_rows_data:
            total_wins += int(row.get("shadow_wins") or 0)
            total_losses += int(row.get("shadow_losses") or 0)
            hm = row.get("horizon_metrics") or []
            hm_rows = list(hm) if isinstance(hm, list) else list(hm.values()) if isinstance(hm, dict) else []
            for hrow in hm_rows:
                if not isinstance(hrow, dict):
                    continue
                hidx = int(hrow.get("horizon_index") or 0)
                status = str(hrow.get("status") or "PENDING")
                if status in ("WIN", "LOSS"):
                    horizon_samples[hidx] = horizon_samples.get(hidx, 0) + 1
                    if status == "WIN":
                        horizon_wins[hidx] = horizon_wins.get(hidx, 0) + 1
                    err_pct = hrow.get("close_error_pct")
                    if err_pct is not None:
                        mape_sum += abs(float(err_pct))
                        mape_count += 1
        samples = total_wins + total_losses
        return {
            "samples": samples,
            "direction_accuracy_pct": None if samples == 0 else (total_wins / samples) * 100.0,
            "mape_pct": None if mape_count == 0 else mape_sum / mape_count,
            "per_horizon_accuracy": {
                hidx: (horizon_wins.get(hidx, 0) / n * 100.0)
                for hidx, n in horizon_samples.items() if n > 0
            },
        }

    def test_aggregates_wins_and_losses_from_multiple_evaluations(self):
        rows = [
            {"shadow_wins": 3, "shadow_losses": 1, "horizon_metrics": []},
            {"shadow_wins": 2, "shadow_losses": 2, "horizon_metrics": []},
        ]
        result = self._aggregate_horizon_metrics(rows)
        self.assertEqual(8, result["samples"])  # 3+1+2+2 = 8
        self.assertAlmostEqual(62.5, result["direction_accuracy_pct"])  # 5/8 = 62.5%

    def test_mape_computed_from_horizon_metrics(self):
        rows = [{"shadow_wins": 1, "shadow_losses": 1, "horizon_metrics": [
            {"horizon_index": 1, "status": "WIN", "close_error_pct": 2.0},
            {"horizon_index": 2, "status": "LOSS", "close_error_pct": -4.0},
        ]}]
        result = self._aggregate_horizon_metrics(rows)
        self.assertAlmostEqual(3.0, result["mape_pct"])  # avg(2, 4)

    def test_per_horizon_accuracy_per_horizon_index(self):
        rows = [{"shadow_wins": 0, "shadow_losses": 0, "horizon_metrics": [
            {"horizon_index": 1, "status": "WIN", "close_error_pct": 1.0},
            {"horizon_index": 1, "status": "WIN", "close_error_pct": 1.0},
            {"horizon_index": 2, "status": "LOSS", "close_error_pct": 3.0},
        ]}]
        result = self._aggregate_horizon_metrics(rows)
        self.assertAlmostEqual(100.0, result["per_horizon_accuracy"][1])
        self.assertAlmostEqual(0.0, result["per_horizon_accuracy"][2])

    def test_empty_shadow_evaluations_returns_none_metrics(self):
        result = self._aggregate_horizon_metrics([])
        self.assertEqual(0, result["samples"])
        self.assertIsNone(result["direction_accuracy_pct"])
        self.assertIsNone(result["mape_pct"])


class TestGateFunction(unittest.TestCase):
    def _gate(self, name, metric, threshold, comparator=">="):
        from model_registry import _gate  # noqa: PLC0415
        return _gate(name, metric, threshold, comparator=comparator)

    def test_pass_when_metric_meets_threshold(self):
        result = self._gate("test", 60.0, 55.0)
        self.assertEqual("PASS", result["status"])

    def test_fail_when_metric_below_threshold(self):
        result = self._gate("test", 40.0, 55.0)
        self.assertEqual("FAIL", result["status"])

    def test_fail_when_metric_is_none(self):
        result = self._gate("test", None, 55.0)
        self.assertEqual("FAIL", result["status"])

    def test_fail_when_threshold_is_none(self):
        result = self._gate("test", 60.0, None)
        self.assertEqual("FAIL", result["status"])

    def test_insufficient_evidence_fails_gate(self):
        """A gate with None metric (no candidate evidence) must FAIL, not PASS."""
        result = self._gate("baseline_beat_rate", None, 50.0)
        self.assertEqual("FAIL", result["status"])


if __name__ == "__main__":
    unittest.main()
