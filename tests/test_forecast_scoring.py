from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from forecast_scoring import direction_from_prices, score_forecast_against_actuals, score_trade_signal_outcome


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

    def test_trade_signal_long_wins_on_take_profit_touch(self):
        actual = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T00:05:00Z",
                    "open": 100.0,
                    "high": 102.1,
                    "low": 99.7,
                    "close": 101.5,
                }
            ]
        )

        outcome = score_trade_signal_outcome(
            signal="LONG",
            entry_price=100.0,
            tp_price=102.0,
            sl_price=99.0,
            actual_df=actual,
            forecast_end_timestamp_utc="2026-05-01T00:05:00Z",
        )

        self.assertEqual("WIN", outcome["status"])
        self.assertEqual("2026-05-01T00:05:00+00:00", outcome["hit_timestamp_utc"])

    def test_trade_signal_short_loses_on_stop_loss_touch(self):
        actual = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T00:05:00Z",
                    "open": 100.0,
                    "high": 101.2,
                    "low": 99.4,
                    "close": 100.8,
                }
            ]
        )

        outcome = score_trade_signal_outcome(
            signal="SHORT",
            entry_price=100.0,
            tp_price=98.0,
            sl_price=101.0,
            actual_df=actual,
            forecast_end_timestamp_utc="2026-05-01T00:05:00Z",
        )

        self.assertEqual("LOSS", outcome["status"])

    def test_trade_signal_marks_same_candle_tp_sl_as_ambiguous(self):
        actual = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T00:05:00Z",
                    "open": 100.0,
                    "high": 102.5,
                    "low": 98.5,
                    "close": 100.5,
                }
            ]
        )

        outcome = score_trade_signal_outcome(
            signal="LONG",
            entry_price=100.0,
            tp_price=102.0,
            sl_price=99.0,
            actual_df=actual,
            forecast_end_timestamp_utc="2026-05-01T00:05:00Z",
        )

        self.assertEqual("AMBIGUOUS", outcome["status"])
        self.assertTrue(outcome["ambiguous"])

    def test_hold_signal_is_not_counted_as_win_loss(self):
        actual = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T00:05:00Z",
                    "open": 100.0,
                    "high": 100.02,
                    "low": 99.98,
                    "close": 100.01,
                }
            ]
        )

        outcome = score_trade_signal_outcome(
            signal="HOLD",
            entry_price=100.0,
            tp_price=100.0,
            sl_price=100.0,
            actual_df=actual,
            cost_threshold_pct=0.05,
            forecast_end_timestamp_utc="2026-05-01T00:05:00Z",
        )

        self.assertEqual("GOOD_HOLD", outcome["status"])
        self.assertEqual("GOOD_HOLD", outcome["hold_quality"])


if __name__ == "__main__":
    unittest.main()
