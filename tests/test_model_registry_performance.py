from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import model_registry


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, responses):
        self._responses = list(responses)

    def execute(self, *_args, **_kwargs):
        if not self._responses:
            raise AssertionError("Unexpected query execution")
        return _FakeResult(self._responses.pop(0))

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class _CapturingConnection:
    def __init__(self):
        self.params = None

    def execute(self, _query, params):
        self.params = params
        return _FakeResult([])

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class ModelRegistrySerializationTests(unittest.TestCase):
    def test_register_model_version_accepts_datetime_approval_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            (model_dir / "config.json").write_text("{}", encoding="utf-8")
            (model_dir / "model.safetensors").write_text("weights", encoding="utf-8")
            conn = _CapturingConnection()
            generated_at = datetime(2026, 5, 7, 16, 25, tzinfo=timezone.utc)

            with patch("model_registry.connect", return_value=conn):
                payload = model_registry.register_model_version(
                    model_name="Kronos-auto-finetuned",
                    model_path=str(model_dir),
                    approval_metrics={"latest_live_metrics": {"generated_at_utc": generated_at}},
                )

        self.assertTrue(payload["artifact_manifest"]["complete"])
        approval_metrics = conn.params[-2]
        self.assertEqual(
            "2026-05-07T16:25:00+00:00",
            approval_metrics.obj["latest_live_metrics"]["generated_at_utc"],
        )


class ModelPerformanceTests(unittest.TestCase):
    def test_model_performance_populates_shadow_horizon_accuracy(self):
        active_metrics_rows = [
            {
                "wins": 2,
                "losses": 2,
                "mape_pct": 0.2,
                "rmse": 1.0,
            }
        ]

        shadow_horizon_rows = [
            {
                "horizon_metrics": [
                    {"horizon_index": 1, "status": "WIN"},
                    {"horizon_index": 1, "status": "LOSS"},
                    {"horizon_index": 2, "status": "LOSS"},
                ]
            },
            {
                "horizon_metrics": [
                    {"horizon_index": 1, "status": "WIN"},
                    {"horizon_index": 2, "status": "WIN"},
                ]
            },
        ]

        main_rows = [
            [
                {
                    "shadow_model_version_id": "shadow-v1",
                    "wins": 3,
                    "losses": 1,
                    "disagreement_samples": 1,
                    "shadow_wins_when_disagree": 1,
                    "active_wins_when_disagree": 0,
                }
            ],
            [{"wins": 2, "losses": 2, "pending": 0, "total": 4}],
            [{"wins": 2, "losses": 2, "pending": 0, "total": 4}],
            [{"wins": 3, "losses": 1, "pending": 0, "total": 4}],
            [
                {
                    "active_wins": 2,
                    "active_losses": 2,
                    "shadow_wins": 3,
                    "shadow_losses": 1,
                    "evaluation_rows": 4,
                    "disagreement_samples": 1,
                    "active_wins_when_disagree": 0,
                    "shadow_wins_when_disagree": 1,
                }
            ],
            [
                {"horizon_index": 1, "samples": 2, "wins": 1, "mape_pct": 0.11},
                {"horizon_index": 2, "samples": 2, "wins": 1, "mape_pct": 0.22},
            ],
            shadow_horizon_rows,
            [],
        ]

        with patch(
            "model_registry.connect",
            side_effect=[
                _FakeConnection([active_metrics_rows]),
                _FakeConnection(main_rows),
            ],
        ):
            payload = model_registry.model_performance(symbol="ETHUSD", resolution="MINUTE_5")

        horizons = payload["horizons"]
        self.assertEqual(2, len(horizons))
        self.assertAlmostEqual(66.6666666667, horizons[0]["shadow_accuracy_pct"], places=4)
        self.assertAlmostEqual(50.0, horizons[1]["shadow_accuracy_pct"], places=4)


if __name__ == "__main__":
    unittest.main()
