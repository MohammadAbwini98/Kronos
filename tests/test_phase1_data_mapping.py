from __future__ import annotations

import contextlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db
import main_fetch_historical_range
import prediction_store


class PostgresDsnAlignmentTests(unittest.TestCase):
    def test_default_postgres_dsn_matches_docker_credentials(self):
        self.assertEqual(
            "postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos",
            db.DEFAULT_POSTGRES_DSN,
        )


class OhlcvValidationTests(unittest.TestCase):
    def _base_kwargs(self) -> dict[str, str]:
        return {
            "symbol": "ETHUSD",
            "epic": "ETHUSD",
            "resolution": "MINUTE_5",
            "price_side": "mid",
        }

    def test_upsert_rejects_null_required_ohlc(self):
        df = pd.DataFrame(
            [
                {
                    "timestamps": "2026-01-01T00:00:00Z",
                    "open": None,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1.0,
                    "amount": 0.0,
                }
            ]
        )

        with patch("prediction_store.connect") as mocked_connect:
            with self.assertRaises(prediction_store.PredictionStoreError):
                prediction_store.upsert_ohlcv_df(df, **self._base_kwargs())
        mocked_connect.assert_not_called()

    def test_upsert_rejects_invalid_ohlc_ordering(self):
        df = pd.DataFrame(
            [
                {
                    "timestamps": "2026-01-01T00:00:00Z",
                    "open": 100.0,
                    "high": 95.0,
                    "low": 105.0,
                    "close": 100.0,
                    "volume": 1.0,
                    "amount": 0.0,
                }
            ]
        )

        with patch("prediction_store.connect") as mocked_connect:
            with self.assertRaises(prediction_store.PredictionStoreError):
                prediction_store.upsert_ohlcv_df(df, **self._base_kwargs())
        mocked_connect.assert_not_called()


class HistoricalRangePersistenceTests(unittest.TestCase):
    def test_range_fetch_upserts_instrument_and_candles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            fake_settings = types.SimpleNamespace(output_dir=output_dir)

            fake_client = MagicMock()
            fake_client.resolve_market.return_value = {
                "epic": "ETHUSD",
                "instrumentName": "Ethereum/USD",
            }
            fake_client.get_historical_prices.return_value = pd.DataFrame(
                [
                    {
                        "timestamps": "2026-01-01T00:00:00Z",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1.0,
                        "amount": 0.0,
                    },
                    {
                        "timestamps": "2026-01-01T00:05:00Z",
                        "open": 100.5,
                        "high": 101.5,
                        "low": 100.0,
                        "close": 101.0,
                        "volume": 1.0,
                        "amount": 0.0,
                    },
                ]
            )

            with contextlib.ExitStack() as _stack:
                _stack.enter_context(patch("main_fetch_historical_range.load_settings", return_value=fake_settings))
                _stack.enter_context(patch("main_fetch_historical_range.CapitalRestClient", return_value=fake_client))
                _stack.enter_context(patch("main_fetch_historical_range.save_kronos_csv"))
                mocked_upsert_instrument = _stack.enter_context(patch("main_fetch_historical_range.upsert_instrument"))
                mocked_upsert_ohlcv = _stack.enter_context(patch("main_fetch_historical_range.upsert_ohlcv_df", return_value=2))
                _stack.enter_context(patch(
                    "sys.argv",
                    [
                        "prog",
                        "--market",
                        "ETHUSD",
                        "--symbol",
                        "ETHUSD",
                        "--resolution",
                        "MINUTE_5",
                        "--from",
                        "2026-01-01T00:00:00Z",
                        "--to",
                        "2026-01-01T00:05:00Z",
                        "--postgres-dsn",
                        "postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos",
                    ],
                ))
                main_fetch_historical_range.main()

        mocked_upsert_instrument.assert_called_once()
        mocked_upsert_ohlcv.assert_called_once()
        self.assertEqual("ETHUSD", mocked_upsert_ohlcv.call_args.kwargs["symbol"])
        self.assertEqual("MINUTE_5", mocked_upsert_ohlcv.call_args.kwargs["resolution"])
        self.assertEqual("historical", mocked_upsert_ohlcv.call_args.kwargs["source"])


if __name__ == "__main__":
    unittest.main()
