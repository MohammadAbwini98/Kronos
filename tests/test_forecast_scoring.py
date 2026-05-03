from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from forecast_scoring import direction_from_prices, score_forecast_against_actuals


class ForecastScoringTests(unittest.TestCase):
    def test_first_horizon_uses_last_input_close_anchor(self):
        forecast = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 102.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 98.0},
            ]
        )
        actual = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 101.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 97.0},
            ]
        )

        score = score_forecast_against_actuals(forecast, actual, last_input_close=100.0)

        self.assertEqual(["WIN", "WIN"], [row["status"] for row in score["rows"]])
        self.assertEqual(2, score["summary"]["wins"])
        self.assertEqual(100.0, score["summary"]["direction_accuracy_pct"])
        self.assertEqual("UP", score["rows"][0]["predicted_direction"])
        self.assertEqual("UP", score["rows"][0]["actual_direction"])
        self.assertEqual("DOWN", score["rows"][1]["predicted_direction"])
        self.assertEqual("DOWN", score["rows"][1]["actual_direction"])

    def test_missing_last_input_leaves_first_direction_pending(self):
        forecast = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 102.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 98.0},
            ]
        )
        actual = pd.DataFrame(
            [
                {"timestamps": "2026-05-01T00:05:00Z", "close": 101.0},
                {"timestamps": "2026-05-01T00:10:00Z", "close": 97.0},
            ]
        )

        score = score_forecast_against_actuals(forecast, actual)

        self.assertEqual("PENDING", score["rows"][0]["status"])
        self.assertEqual("WIN", score["rows"][1]["status"])
        self.assertEqual(1, score["summary"]["direction_comparable_candles"])
        self.assertEqual(1, score["summary"]["direction_pending"])

    def test_direction_from_prices_handles_zero_anchor_as_flat(self):
        self.assertEqual("FLAT", direction_from_prices(0.0, 100.0))


if __name__ == "__main__":
    unittest.main()
