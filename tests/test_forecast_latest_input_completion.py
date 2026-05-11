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

import main_forecast_latest


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return self

    def fetchall(self):
        return self.rows


class ForecastLatestInputCompletionTests(unittest.TestCase):
    def test_complete_input_from_stored_candles_repairs_gap_and_trims_lookback(self):
        fetched = pd.DataFrame(
            {
                "timestamps": pd.to_datetime(
                    [
                        "2026-05-01T00:00:00Z",
                        "2026-05-01T00:10:00Z",
                        "2026-05-01T00:15:00Z",
                    ],
                    utc=True,
                ),
                "open": [100.0, 102.0, 103.0],
                "high": [101.0, 103.0, 104.0],
                "low": [99.0, 101.0, 102.0],
                "close": [100.5, 102.5, 103.5],
                "volume": [1.0, 1.0, 1.0],
                "amount": [0.0, 0.0, 0.0],
            }
        )
        stored_rows = [
            {
                "timestamps": pd.Timestamp("2026-05-01T00:05:00Z"),
                "open": 100.5,
                "high": 100.5,
                "low": 100.5,
                "close": 100.5,
                "volume": 0.0,
                "amount": 0.0,
            }
        ]

        with patch("main_forecast_latest.connect", return_value=_FakeConnection(stored_rows)):
            completed, stored_gap_rows = main_forecast_latest._complete_input_from_stored_candles(
                fetched,
                symbol="ETHUSD",
                epic="ETHUSD",
                resolution="MINUTE_5",
                price_side="mid",
                lookback=3,
                dsn="postgresql://example",
            )

        self.assertEqual(1, stored_gap_rows)
        self.assertEqual(
            [
                pd.Timestamp("2026-05-01T00:05:00Z"),
                pd.Timestamp("2026-05-01T00:10:00Z"),
                pd.Timestamp("2026-05-01T00:15:00Z"),
            ],
            list(completed["timestamps"]),
        )
        self.assertEqual([100.5, 102.5, 103.5], list(completed["close"]))


if __name__ == "__main__":
    unittest.main()
