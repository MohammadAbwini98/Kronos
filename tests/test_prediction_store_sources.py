from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import prediction_store


class CandleSourcePriorityTests(unittest.TestCase):
    def test_websocket_source_is_sticky(self):
        self.assertEqual(
            "websocket_ohlc",
            prediction_store.preferred_candle_source("websocket_ohlc", "latest_fetch"),
        )
        self.assertEqual(
            "websocket_ohlc",
            prediction_store.preferred_candle_source("actual_validation", "websocket_ohlc"),
        )

    def test_latest_fetch_beats_validation_for_live_fallback(self):
        self.assertEqual(
            "latest_fetch",
            prediction_store.preferred_candle_source("actual_validation", "latest_fetch"),
        )
        self.assertEqual(
            "latest_fetch",
            prediction_store.preferred_candle_source("latest_fetch", "actual_validation"),
        )


if __name__ == "__main__":
    unittest.main()
