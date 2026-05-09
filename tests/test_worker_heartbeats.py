from __future__ import annotations

from pathlib import Path
from decimal import Decimal
import contextlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import orjson

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from capital_auth import CapitalAuthenticator
from capital_ws_ohlc_client import CapitalOhlcWebSocketClient
from config import BridgeSettings
import main_auto_finetune_worker


class WebsocketHeartbeatTests(unittest.TestCase):
    def test_append_row_refreshes_streaming_heartbeat(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = BridgeSettings(output_dir=Path(temp_dir))
            client = CapitalOhlcWebSocketClient(
                settings,
                CapitalAuthenticator(settings),
                epic="ETHUSD",
                resolution="MINUTE",
                symbol="ETHUSD",
                heartbeat_callback=lambda status, details: calls.append((status, details)),
                heartbeat_interval_seconds=1,
            )
            row = {
                "timestamps": "2026-05-01T10:00:00Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1.0,
                "amount": 0.0,
            }
            with patch("capital_ws_ohlc_client.upsert_ohlcv_df", return_value=1):
                client._append_row(row)

        self.assertEqual(1, len(calls))
        self.assertEqual("OK", calls[0][0])
        self.assertEqual("streaming", calls[0][1].get("state"))
        self.assertEqual("streaming_ohlc", calls[0][1].get("stream_state"))
        self.assertEqual("2026-05-01T10:00:00Z", calls[0][1].get("last_candle_timestamp_utc"))

    def test_quote_message_persists_live_quote_and_refreshes_heartbeat(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = BridgeSettings(output_dir=Path(temp_dir))
            client = CapitalOhlcWebSocketClient(
                settings,
                CapitalAuthenticator(settings),
                epic="ETHUSD",
                resolution="MINUTE_5",
                symbol="ETHUSD",
                heartbeat_callback=lambda status, details: calls.append((status, details)),
                heartbeat_interval_seconds=1,
            )
            event = {
                "status": "OK",
                "destination": "quote",
                "payload": {
                    "epic": "ETHUSD",
                    "bid": 2300.0,
                    "ofr": 2301.0,
                    "timestamp": 1777638000000,
                },
            }
            with contextlib.ExitStack() as _stack:
                _stack.enter_context(patch("capital_ws_ohlc_client.insert_raw_market_event"))
                upsert_quote = _stack.enter_context(patch(
                    "capital_ws_ohlc_client.upsert_live_quote",
                    return_value={
                        "price": Decimal("2300.5"),
                        "bid": 2300.0,
                        "ask": 2301.0,
                        "timestamp_utc": "2026-05-01T12:20:00+00:00",
                    },
                ))
                import asyncio

                asyncio.run(client._handle_message(orjson.dumps(event)))

        upsert_quote.assert_called_once()
        self.assertEqual(1, len(calls))
        self.assertEqual("streaming_quote", calls[0][1].get("stream_state"))
        self.assertEqual(2300.5, calls[0][1].get("last_close"))


class AutoFinetuneHeartbeatSleepTests(unittest.TestCase):
    def test_long_sleep_refreshes_heartbeat_before_next_cycle(self):
        sleeps = []
        with patch("main_auto_finetune_worker._heartbeat") as heartbeat:
            main_auto_finetune_worker._sleep_with_heartbeat(
                total_seconds=125,
                heartbeat_status="OK",
                heartbeat_details={"symbol": "ETHUSD", "resolution": "MINUTE"},
                dsn=None,
                heartbeat_interval_seconds=60,
                sleep_func=lambda seconds: sleeps.append(seconds),
            )

        self.assertEqual([60, 60, 5], sleeps)
        self.assertEqual(2, heartbeat.call_count)
        self.assertEqual("sleeping", heartbeat.call_args_list[0].args[1].get("state"))


if __name__ == "__main__":
    unittest.main()
