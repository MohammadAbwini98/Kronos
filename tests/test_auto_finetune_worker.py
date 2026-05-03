from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_auto_finetune_worker


def _dataset(rows: int) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1.0 for _ in range(rows)],
            "amount": [0.0 for _ in range(rows)],
        }
    )


class PromotionDecisionTests(unittest.TestCase):
    def test_model_artifacts_missing(self):
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=False,
            metrics={"matched_candles": 30, "direction_accuracy_pct": 65.0},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=None,
        )
        self.assertEqual(("not_ready", "model_artifacts_missing"), (status, reason))

    def test_matched_candles_below_threshold(self):
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=True,
            metrics={"matched_candles": 10, "direction_accuracy_pct": 65.0},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=None,
        )
        self.assertEqual("pending_review", status)
        self.assertIn("matched_candles_below_threshold", reason)

    def test_direction_accuracy_unavailable(self):
        # With enough matched candles, accuracy=None now returns pending_evaluation
        # so that formal evaluate_promotion() can be run with candidate evidence.
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=True,
            metrics={"matched_candles": 30, "direction_accuracy_pct": None},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=None,
        )
        self.assertEqual("pending_evaluation", status)

    def test_direction_accuracy_below_threshold(self):
        # _promotion_decision no longer rejects on accuracy threshold;
        # that decision belongs to evaluate_promotion() with candidate evidence.
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=True,
            metrics={"matched_candles": 30, "direction_accuracy_pct": 50.0},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=None,
        )
        self.assertEqual("pending_evaluation", status)
        self.assertNotEqual("approved", status)

    def test_direction_accuracy_not_improved(self):
        # Even when accuracy is good, _promotion_decision returns pending_evaluation;
        # final approval must come from evaluate_promotion().
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=True,
            metrics={"matched_candles": 30, "direction_accuracy_pct": 60.0},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=60.0,
        )
        self.assertNotEqual("approved", status)

    def test_promotion_approved(self):
        # _promotion_decision must NEVER return 'approved'; that is now exclusively
        # the role of evaluate_promotion() in model_registry.
        status, reason = main_auto_finetune_worker._promotion_decision(
            model_ready=True,
            metrics={"matched_candles": 30, "direction_accuracy_pct": 61.0},
            min_accuracy=55.0,
            min_matched=20,
            previous_promoted_accuracy=60.0,
        )
        self.assertNotEqual("approved", status,
            "_promotion_decision must never return 'approved'; use evaluate_promotion() instead")


class FinetuneDatasetTests(unittest.TestCase):
    def test_source_counts_split_websocket_and_historical_rows(self):
        df = _dataset(4)
        df["source"] = ["historical", "latest_fetch", "websocket_ohlc", "websocket_ohlc"]

        counts = main_auto_finetune_worker._dataset_source_counts(df)
        progress = main_auto_finetune_worker._promotion_progress_pct(len(df), 10)

        self.assertEqual({"websocket_ohlc": 2, "historical": 1, "latest_fetch": 1}, counts)
        self.assertEqual(40.0, progress)

    def test_finetune_dataset_loads_all_sources_for_selected_resolution(self):
        rows = [
            {
                "timestamps": pd.Timestamp("2026-01-01T00:05:00Z"),
                "open": 101,
                "high": 102,
                "low": 100,
                "close": 101.5,
                "volume": 1,
                "amount": 0,
                "source": "websocket_ohlc",
            },
            {
                "timestamps": pd.Timestamp("2026-01-01T00:00:00Z"),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1,
                "amount": 0,
                "source": "historical",
            },
        ]

        class Cursor:
            def execute(self, query, params):
                self.query = query
                self.params = params
                return self

            def fetchall(self):
                return rows

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params):
                self.cursor = Cursor()
                return self.cursor.execute(query, params)

        with patch("main_auto_finetune_worker.connect", return_value=Conn()):
            df = main_auto_finetune_worker._load_finetune_dataset(
                symbol="ETHUSD",
                resolution="MINUTE_5",
                price_side="mid",
                limit=100,
                dsn=None,
            )

        self.assertEqual(["historical", "websocket_ohlc"], df["source"].tolist())
        self.assertEqual(["2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"], [ts.isoformat() for ts in df["timestamps"]])

    def test_latest_live_metrics_aggregates_validated_outcomes(self):
        class Cursor:
            def execute(self, query, params):
                self.query = query
                self.params = params
                return self

            def fetchone(self):
                return {
                    "generated_at_utc": pd.Timestamp("2026-01-01T01:00:00Z"),
                    "run_count": 3,
                    "wins": 7,
                    "losses": 3,
                }

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params):
                self.cursor = Cursor()
                return self.cursor.execute(query, params)

        with patch("main_auto_finetune_worker.connect", return_value=Conn()):
            metrics = main_auto_finetune_worker._latest_live_metrics(
                symbol="ETHUSD",
                resolution="MINUTE_5",
                dsn=None,
            )

        self.assertEqual("validated_runs", metrics["run_id"])
        self.assertEqual(3, metrics["run_count"])
        self.assertEqual(10, metrics["matched_candles"])
        self.assertEqual(70.0, metrics["direction_accuracy_pct"])


class FinetuneCommandTemplateSafetyTests(unittest.TestCase):
    def test_invalid_command_template_skips_without_subprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            status_path = root / "auto_finetune_status.json"
            model_dir = root / "model"
            model_dir.mkdir(parents=True, exist_ok=True)

            args = argparse.Namespace(
                symbol="ETHUSD",
                resolution="MINUTE",
                price_side="mid",
                postgres_dsn=None,
                limit=100,
                min_rows=3,
                min_new_rows=1,
                poll_minutes=15,
                command="python train.py --dataset {dataset}",
                model_dir=str(model_dir),
                promotion_min_direction_accuracy=55.0,
                promotion_min_matched_candles=20,
            )

            with (
                patch("main_auto_finetune_worker._load_finetune_dataset", return_value=_dataset(3)),
                patch(
                    "main_auto_finetune_worker._latest_live_metrics",
                    return_value={"matched_candles": 30, "direction_accuracy_pct": 62.0},
                ),
                patch("main_auto_finetune_worker._model_ready", return_value=False),
                patch("main_auto_finetune_worker.subprocess.run") as run_mock,
            ):
                main_auto_finetune_worker._run_cycle(args, output_dir, status_path)

            run_mock.assert_not_called()
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual("skip", payload.get("action"))
            self.assertEqual("invalid_finetune_command_template", payload.get("reason"))
            self.assertIn("{dataset}", payload.get("hint", ""))
            self.assertIn("{model_dir}", payload.get("hint", ""))


if __name__ == "__main__":
    unittest.main()
