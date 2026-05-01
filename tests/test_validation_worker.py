from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_validation_worker


def _run(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "metadata_path": f"output/forecast_metadata_{run_id}.json",
        "forecast_csv_path": f"output/kronos_forecast_{run_id}.csv",
        "epic": "ETHUSD",
        "resolution": "MINUTE",
        "price_side": "mid",
        "forecast_end_timestamp_utc": "2026-05-01T10:00:00Z",
    }


class ValidationCycleTests(unittest.TestCase):
    def test_due_runs_orders_by_least_recently_updated_first(self):
        class _FakeResult:
            def fetchall(self):
                return []

        class _FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def execute(self, sql, params):
                self.sql = sql
                self.params = params
                return _FakeResult()

        fake = _FakeConnection()
        with patch("main_validation_worker.connect", return_value=fake):
            main_validation_worker._due_runs(None, limit=5)

        self.assertIn("ORDER BY updated_at ASC, forecast_end_timestamp_utc ASC", fake.sql)
        self.assertEqual((5,), fake.params)

    def test_cycle_stops_after_rate_limit(self):
        args = argparse.Namespace(postgres_dsn=None, batch_size=5, env="demo")
        with (
            patch("main_validation_worker._due_runs", return_value=[_run("one"), _run("two")]),
            patch(
                "main_validation_worker._validate_run",
                return_value=(1, 'Capital.com authentication failed with HTTP 429: {"errorCode":"error.too-many.requests"}'),
            ) as validate,
        ):
            details = main_validation_worker._run_validation_cycle(args)

        self.assertEqual(1, validate.call_count)
        self.assertEqual(1, details["errors"])
        self.assertTrue(details["rate_limited"])
        self.assertIn("HTTP 429", details["last_error"])

    def test_cycle_keeps_child_error_tail(self):
        args = argparse.Namespace(postgres_dsn=None, batch_size=5, env="demo")
        with (
            patch("main_validation_worker._due_runs", return_value=[_run("one")]),
            patch("main_validation_worker._validate_run", return_value=(2, "actual CSV contains null OHLC values")),
        ):
            details = main_validation_worker._run_validation_cycle(args)

        self.assertEqual(1, details["errors"])
        self.assertFalse(details["rate_limited"])
        self.assertIn("actual CSV contains null OHLC values", details["last_error"])


if __name__ == "__main__":
    unittest.main()
