from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_fetch_actual_for_forecast


class ActualWindowCoverageTests(unittest.TestCase):
    def test_db_window_coverage_requires_every_expected_timestamp(self):
        start = pd.Timestamp("2026-05-01T10:00:00Z")
        end = pd.Timestamp("2026-05-01T10:10:00Z")
        complete = pd.DataFrame({"timestamps": pd.date_range(start, end, freq="5min", tz="UTC")})
        missing_middle = pd.DataFrame({"timestamps": [start, end]})

        self.assertTrue(main_fetch_actual_for_forecast._covers_required_window(complete, start, end, "MINUTE_5"))
        self.assertFalse(main_fetch_actual_for_forecast._covers_required_window(missing_middle, start, end, "MINUTE_5"))

    def test_latest_closed_timestamp_excludes_current_open_candle(self):
        now = pd.Timestamp("2026-05-01T10:07:30Z")

        closed = main_fetch_actual_for_forecast._latest_closed_timestamp(now, "MINUTE_5")

        self.assertEqual(pd.Timestamp("2026-05-01T10:00:00Z"), closed)


if __name__ == "__main__":
    unittest.main()
