from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


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


class ShadowValidationSummaryTests(unittest.TestCase):
    def test_shadow_status_uses_forecast_directions_against_actuals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            forecast_path = Path(temp_dir) / "shadow.csv"
            pd.DataFrame(
                [
                    {
                        "timestamps": "2026-05-01T00:05:00Z",
                        "open": 100.0,
                        "high": 103.0,
                        "low": 99.0,
                        "close": 102.0,
                        "volume": 0.0,
                        "amount": 0.0,
                    },
                    {
                        "timestamps": "2026-05-01T00:10:00Z",
                        "open": 102.0,
                        "high": 103.0,
                        "low": 97.0,
                        "close": 98.0,
                        "volume": 0.0,
                        "amount": 0.0,
                    },
                ]
            ).to_csv(forecast_path, index=False)
            actual_by_ts = {
                pd.Timestamp("2026-05-01T00:05:00Z").isoformat(): pd.Series({"close": 101.0}),
                pd.Timestamp("2026-05-01T00:10:00Z").isoformat(): pd.Series({"close": 97.0}),
            }

            summary = prediction_store._shadow_validation_summary(
                forecast_csv_path=forecast_path,
                actual_by_ts=actual_by_ts,
                last_input_close=100.0,
                flat_threshold_pct=0.02,
            )

        self.assertEqual("WIN", summary["status"])
        self.assertEqual(2, summary["wins"])
        self.assertEqual(0, summary["losses"])

    def test_shadow_status_stays_pending_without_actual_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            forecast_path = Path(temp_dir) / "shadow.csv"
            pd.DataFrame(
                [
                    {
                        "timestamps": "2026-05-01T00:05:00Z",
                        "open": 100.0,
                        "high": 103.0,
                        "low": 99.0,
                        "close": 102.0,
                        "volume": 0.0,
                        "amount": 0.0,
                    }
                ]
            ).to_csv(forecast_path, index=False)

            summary = prediction_store._shadow_validation_summary(
                forecast_csv_path=forecast_path,
                actual_by_ts={},
                last_input_close=100.0,
                flat_threshold_pct=0.02,
            )

        self.assertEqual("PENDING", summary["status"])
        self.assertEqual(1, summary["pending"])

    def test_shadow_trade_status_uses_tp_sl_when_signal_context_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            forecast_path = Path(temp_dir) / "shadow.csv"
            pd.DataFrame(
                [
                    {
                        "timestamps": "2026-05-01T00:05:00Z",
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.5,
                        "volume": 0.0,
                        "amount": 0.0,
                    }
                ]
            ).to_csv(forecast_path, index=False)
            actual_by_ts = {
                pd.Timestamp("2026-05-01T00:05:00Z").isoformat(): pd.Series(
                    {"open": 100.0, "high": 99.8, "low": 98.8, "close": 99.0}
                ),
            }

            summary = prediction_store._shadow_validation_summary(
                forecast_csv_path=forecast_path,
                actual_by_ts=actual_by_ts,
                last_input_close=100.0,
                flat_threshold_pct=0.02,
                signal="LONG",
                entry_price=100.0,
                tp_price=102.0,
                sl_price=99.0,
                cost_threshold_pct=0.05,
                forecast_end_timestamp_utc="2026-05-01T00:05:00Z",
            )

        self.assertEqual("LOSS", summary["status"])
        self.assertEqual(0, summary["wins"])
        self.assertEqual(1, summary["losses"])
        self.assertEqual("LOSS", summary["trade_outcome"]["status"])


class SignalStatusPrimaryWindowTests(unittest.TestCase):
    def test_uses_first_horizon_status_only(self):
        rows = [
            {"horizon_index": 2, "status": "WIN"},
            {"horizon_index": 1, "status": "LOSS"},
        ]
        self.assertEqual("LOSS", prediction_store._signal_status_for_primary_window(rows))

    def test_pending_when_primary_horizon_not_decided(self):
        rows = [
            {"horizon_index": 1, "status": "PENDING"},
            {"horizon_index": 2, "status": "WIN"},
        ]
        self.assertEqual("PENDING", prediction_store._signal_status_for_primary_window(rows))


if __name__ == "__main__":
    unittest.main()
