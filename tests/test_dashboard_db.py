from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import contextlib
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_db


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


class SecondsSinceTests(unittest.TestCase):
    def test_seconds_since_none(self):
        self.assertIsNone(dashboard_db._seconds_since(None))

    def test_seconds_since_timezone_aware_datetime(self):
        ts = datetime.now(timezone.utc) - timedelta(seconds=30)
        value = dashboard_db._seconds_since(ts)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 29)
        self.assertLessEqual(value, 35)

    def test_seconds_since_naive_datetime(self):
        ts = (datetime.now(timezone.utc) - timedelta(seconds=15)).replace(tzinfo=None)
        value = dashboard_db._seconds_since(ts)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 14)
        self.assertLessEqual(value, 20)

    def test_seconds_since_iso_string(self):
        ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        value = dashboard_db._seconds_since(ts)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 9)
        self.assertLessEqual(value, 15)

    def test_seconds_since_invalid_value(self):
        self.assertIsNone(dashboard_db._seconds_since("not-a-timestamp"))


class WorkerStaleDerivationTests(unittest.TestCase):
    def test_old_ok_heartbeat_is_marked_stale_and_defaults_are_preserved(self):
        now = datetime.now(timezone.utc)
        heartbeats = [
            {
                "service_name": "prediction_scheduler",
                "status": "OK",
                "details": {"heartbeat": "ok"},
                "updated_at": now - timedelta(seconds=181),
            },
            {
                "service_name": "validation_worker",
                "status": "ERROR",
                "details": {"error": "boom"},
                "updated_at": now - timedelta(seconds=5),
            },
        ]

        query_results = [
            [],  # candles
            [],  # signals
            [],  # websocket live quote
            [],  # fallback live quote
            [],  # websocket candle quote
            [],  # outcomes
            heartbeats,
        ]

        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("dashboard_db.healthcheck", return_value={"ok": True}))
            _stack.enter_context(patch(
                "dashboard_db.connect",
                side_effect=[
                    _FakeConnection(query_results),
                    _FakeConnection([[]]),
                ],
            ))
            _stack.enter_context(patch("dashboard_db.prediction_summary", return_value={"recent_runs": []}))
            snapshot = dashboard_db.postgres_dashboard_snapshot(symbol="ETHUSD", resolution="MINUTE")

        workers = snapshot["worker_statuses"]
        required = [
            "prediction_scheduler",
            "validation_worker",
            "websocket_stream",
            "auto_finetune_worker",
            "maintenance_worker",
        ]
        for name in required:
            self.assertIn(name, workers)
            for field in ("status", "details", "updated_at", "stale_seconds", "stale_alert"):
                self.assertIn(field, workers[name])

        scheduler = workers["prediction_scheduler"]
        self.assertEqual("STALE", scheduler["status"])
        self.assertTrue(scheduler["stale_alert"])
        self.assertGreaterEqual(int(scheduler["stale_seconds"]), 181)

        validation = workers["validation_worker"]
        self.assertEqual("ERROR", validation["status"])

        websocket = workers["websocket_stream"]
        self.assertEqual("MISSING", websocket["status"])
        self.assertIsNone(websocket["stale_seconds"])
        self.assertTrue(websocket["stale_alert"])

    def test_live_quote_prefers_websocket_tick_table(self):
        now = datetime.now(timezone.utc)
        websocket_live_quote = [
            {
                "symbol": "ETHUSD",
                "epic": "ETHUSD",
                "resolution": None,
                "price": 2300.25,
                "bid": 2300.0,
                "ask": 2300.5,
                "timestamp_utc": now,
                "updated_at": now,
                "source": "websocket_quote",
            }
        ]
        fallback_quote = [
            {
                "symbol": "ETHUSD",
                "epic": "ETHUSD",
                "resolution": "MINUTE_5",
                "price": 2299.0,
                "timestamp_utc": now - timedelta(minutes=5),
                "updated_at": now - timedelta(minutes=5),
                "source": "latest_fetch",
            }
        ]

        query_results = [
            [],  # candles
            [],  # signals
            websocket_live_quote,
            fallback_quote,
            [],  # websocket candle quote
            [],  # outcomes
            [],  # heartbeats
        ]

        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("dashboard_db.healthcheck", return_value={"ok": True}))
            _stack.enter_context(patch(
                "dashboard_db.connect",
                side_effect=[
                    _FakeConnection(query_results),
                    _FakeConnection([[]]),
                ],
            ))
            _stack.enter_context(patch("dashboard_db.prediction_summary", return_value={"recent_runs": []}))
            snapshot = dashboard_db.postgres_dashboard_snapshot(symbol="ETHUSD", resolution="MINUTE_5")

        self.assertEqual("websocket_quote", snapshot["live_quote"]["source"])
        self.assertEqual(2300.25, snapshot["live_quote"]["price"])
        self.assertFalse(snapshot["live_health"]["websocket_stale_alert"])


class SignalStatusDerivationTests(unittest.TestCase):
    def test_effective_signal_status_uses_persisted_status(self):
        row = {
            "status": "LOSS",
            "status_raw": "WIN",
            "outcomes_wins": 5,
            "outcomes_losses": 0,
        }
        self.assertEqual("LOSS", dashboard_db._effective_signal_status(row))

    def test_effective_signal_status_unknown_value_defaults_pending(self):
        self.assertEqual("PENDING", dashboard_db._effective_signal_status({"status": "UNKNOWN"}))

    def test_query_signals_keeps_stored_status(self):
        now = datetime.now(timezone.utc)
        query_rows = [
            [{"total": 1}],
            [
                {
                    "signal_id": "sig_1",
                    "run_id": "run_1",
                    "symbol": "ETHUSD",
                    "epic": "ETHUSD",
                    "resolution": "MINUTE_5",
                    "timestamp_utc": now,
                    "signal": "LONG",
                    "direction": "UP",
                    "status": "LOSS",
                    "status_raw": "LOSS",
                    "confidence": 0.6,
                    "expected_move_pct": 0.2,
                    "cost_threshold_pct": 0.05,
                    "entry_price": 2300.0,
                    "tp_price": 2302.0,
                    "sl_price": 2298.5,
                    "last_input_close": 2300.0,
                    "outcomes_wins": 10,
                    "outcomes_losses": 0,
                    "outcomes_pending": 0,
                }
            ],
        ]

        with patch("dashboard_db.connect", return_value=_FakeConnection(query_rows)):
            result = dashboard_db.query_signals(symbol="ETHUSD", resolution="MINUTE_5", page=1, page_size=10)

        self.assertEqual(1, result["pagination"]["total"])
        self.assertEqual("LOSS", result["rows"][0]["status"])


if __name__ == "__main__":
    unittest.main()
