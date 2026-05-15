from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import higher_timeframe_fetcher
import main_validate_signal_context


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class HigherTimeframeSnapshotTests(unittest.TestCase):
    def test_minute_30_uses_latest_closed_candle(self):
        now_utc = pd.Timestamp("2026-05-05T20:15:32Z")
        row = {
            "total_rows": 240,
            "closed_rows": 239,
            "latest_timestamp_utc": pd.Timestamp("2026-05-05T20:00:00Z"),
            "latest_closed_timestamp_utc": pd.Timestamp("2026-05-05T19:30:00Z"),
        }

        with patch("higher_timeframe_fetcher.connect", return_value=_FakeConnection(row)):
            snapshot = higher_timeframe_fetcher._timeframe_snapshot(
                symbol="ETHUSD",
                resolution="MINUTE_30",
                price_side="mid",
                dsn=None,
                now_utc=now_utc,
            )

        self.assertTrue(snapshot["has_closed_latest"])
        self.assertEqual("2026-05-05T19:30:00+00:00", snapshot["latest_closed_timestamp_utc"])
        self.assertEqual("2026-05-05T19:30:00+00:00", snapshot["expected_latest_closed_timestamp_utc"])

    def test_hour_4_uses_latest_closed_bucket_even_with_open_current(self):
        now_utc = pd.Timestamp("2026-05-05T20:15:32Z")
        row = {
            "total_rows": 240,
            "closed_rows": 239,
            "latest_timestamp_utc": pd.Timestamp("2026-05-05T20:00:00Z"),
            "latest_closed_timestamp_utc": pd.Timestamp("2026-05-05T16:00:00Z"),
        }

        with patch("higher_timeframe_fetcher.connect", return_value=_FakeConnection(row)):
            snapshot = higher_timeframe_fetcher._timeframe_snapshot(
                symbol="ETHUSD",
                resolution="HOUR_4",
                price_side="mid",
                dsn=None,
                now_utc=now_utc,
            )

        self.assertTrue(snapshot["has_closed_latest"])
        self.assertEqual("2026-05-05T16:00:00+00:00", snapshot["latest_closed_timestamp_utc"])
        self.assertEqual("2026-05-05T16:00:00+00:00", snapshot["expected_latest_closed_timestamp_utc"])


class ClosedInputFilterTests(unittest.TestCase):
    def test_validation_uses_closed_primary_candles(self):
        frame = pd.DataFrame(
            {
                "timestamps": pd.to_datetime(
                    [
                        "2026-05-05T20:05:00Z",
                        "2026-05-05T20:10:00Z",
                        "2026-05-05T20:15:00Z",
                    ],
                    utc=True,
                ),
                "open": [1.0, 1.0, 1.0],
                "high": [1.1, 1.1, 1.1],
                "low": [0.9, 0.9, 0.9],
                "close": [1.0, 1.0, 1.0],
                "volume": [10.0, 10.0, 1.0],
                "amount": [0.0, 0.0, 0.0],
            }
        )

        filtered = main_validate_signal_context._closed_candles_only(
            frame,
            resolution="MINUTE_5",
            now_utc=pd.Timestamp("2026-05-05T20:16:00Z"),
        )

        self.assertEqual(2, len(filtered.index))
        self.assertEqual(pd.Timestamp("2026-05-05T20:10:00Z"), filtered["timestamps"].iloc[-1])


class HigherTimeframeFetchGateTests(unittest.TestCase):
    def test_entry_timeframe_is_not_treated_as_required_higher_timeframe(self):
        with patch("higher_timeframe_fetcher._timeframe_snapshot") as snapshot, patch(
            "higher_timeframe_fetcher._write_fetcher_heartbeat"
        ):
            out = higher_timeframe_fetcher.ensure_higher_timeframe_candles(
                symbol="ETHUSD",
                price_side="mid",
                epic="ETHUSD",
                required_timeframes=["MINUTE"],
                min_rows_per_timeframe=240,
                env_name="demo",
                dsn=None,
                now_utc=pd.Timestamp("2026-05-05T20:15:00Z"),
            )

        self.assertTrue(out["ok"])
        self.assertEqual([], out["required_timeframes"])
        self.assertEqual([], out["missing_timeframes"])
        snapshot.assert_not_called()

    def test_single_open_candle_buffer_is_not_marked_missing(self):
        with patch(
            "higher_timeframe_fetcher._timeframe_snapshot",
            return_value={
                "total_rows": 240,
                "closed_rows": 239,
                "latest_timestamp_utc": "2026-05-05T20:00:00+00:00",
                "latest_closed_timestamp_utc": "2026-05-05T19:30:00+00:00",
                "expected_latest_closed_timestamp_utc": "2026-05-05T19:30:00+00:00",
                "has_closed_latest": True,
                "stale_seconds": 300,
                "resolution_delta_minutes": 30,
            },
        ), patch("higher_timeframe_fetcher._write_fetcher_heartbeat"):
            out = higher_timeframe_fetcher.ensure_higher_timeframe_candles(
                symbol="ETHUSD",
                price_side="mid",
                epic="ETHUSD",
                required_timeframes=["MINUTE_30"],
                min_rows_per_timeframe=240,
                env_name="demo",
                dsn=None,
                now_utc=pd.Timestamp("2026-05-05T20:15:00Z"),
            )

        self.assertTrue(out["ok"])
        self.assertEqual([], out["missing_timeframes"])


if __name__ == "__main__":
    unittest.main()
