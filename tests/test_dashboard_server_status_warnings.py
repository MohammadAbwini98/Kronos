from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server


class StatusWarningsTests(unittest.TestCase):
    def test_status_warnings_cover_stale_missing_and_error_states(self):
        snapshot = {
            "live_quote": {"source": "latest_fetch"},
            "live_health": {"websocket_stale_alert": True, "websocket_stale_seconds": 125},
            "worker_statuses": {
                "prediction_scheduler": {
                    "status": "MISSING",
                    "stale_alert": True,
                    "stale_seconds": None,
                },
                "validation_worker": {
                    "status": "ERROR",
                    "stale_alert": False,
                    "stale_seconds": 5,
                },
                "websocket_stream": {
                    "status": "STALE",
                    "stale_alert": True,
                    "stale_seconds": 240,
                },
                "auto_finetune_worker": {
                    "status": "OK",
                    "stale_alert": True,
                    "stale_seconds": 241,
                },
                "maintenance_worker": {
                    "status": "ERROR",
                    "stale_alert": False,
                    "stale_seconds": 2,
                },
            },
        }

        with patch.dict("os.environ", {"ENABLE_AUTO_FINETUNE": "true"}):
            warnings = dashboard_server._status_warnings(snapshot)

        self.assertTrue(any("source is latest_fetch" in item for item in warnings))
        self.assertTrue(any("Websocket health warning" in item and "125s" in item for item in warnings))
        self.assertIn("Worker prediction_scheduler status is MISSING.", warnings)
        self.assertIn("Worker validation_worker status is ERROR.", warnings)
        self.assertIn("Worker websocket_stream heartbeat is stale (240s).", warnings)
        self.assertIn("Worker auto_finetune_worker heartbeat appears stale (241s).", warnings)
        self.assertIn("Worker maintenance_worker status is ERROR.", warnings)

    def test_status_warnings_skip_disabled_auto_finetune_worker(self):
        snapshot = {
            "live_quote": {"source": "websocket"},
            "worker_statuses": {
                "prediction_scheduler": {"status": "OK", "stale_alert": False},
                "validation_worker": {"status": "OK", "stale_alert": False},
                "websocket_stream": {"status": "OK", "stale_alert": False},
                "auto_finetune_worker": {
                    "status": "ERROR",
                    "stale_alert": True,
                    "stale_seconds": 999,
                },
            },
        }

        with patch.dict("os.environ", {"ENABLE_AUTO_FINETUNE": "false"}):
            warnings = dashboard_server._status_warnings(snapshot)

        self.assertFalse(any("auto_finetune_worker" in item for item in warnings))


class AutoFinetuneStatusTests(unittest.TestCase):
    def test_auto_finetune_status_enriches_current_model_and_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "auto_finetune_status.json").write_text(
                json.dumps(
                    {
                        "dataset_rows": 500,
                        "required_dataset_rows": 2000,
                        "websocket_rows": 25,
                        "historical_rows": 475,
                        "active_model_path": r"C:\AI\Models\Kronos\Kronos-auto-finetuned",
                        "active_model_ready": True,
                        "promotion_status": "approved",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(dashboard_server, "OUTPUT_DIR", output_dir):
                with patch.dict("os.environ", {"ENABLE_AUTO_FINETUNE": "true"}):
                    payload = dashboard_server._auto_finetune_status()

        self.assertEqual(25.0, payload["promotion_progress_pct"])
        self.assertEqual("Kronos-auto-finetuned", payload["current_model_label"])
        self.assertTrue(payload["auto_model_running"])

    def test_auto_finetune_status_reports_base_model_until_approved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "auto_finetune_status.json").write_text(
                json.dumps(
                    {
                        "dataset_rows": 100,
                        "min_rows": 200,
                        "active_model_path": r"C:\AI\Models\Kronos\Kronos-auto-finetuned",
                        "active_model_ready": True,
                        "promotion_status": "pending_review",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(dashboard_server, "OUTPUT_DIR", output_dir):
                with patch.dict("os.environ", {"ENABLE_AUTO_FINETUNE": "true"}):
                    payload = dashboard_server._auto_finetune_status()

        self.assertEqual(50.0, payload["promotion_progress_pct"])
        self.assertEqual("Kronos-base", payload["current_model_label"])
        self.assertFalse(payload["auto_model_running"])


if __name__ == "__main__":
    unittest.main()
