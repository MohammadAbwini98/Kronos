from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import contextlib
import subprocess
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_prediction_scheduler


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

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


def _args() -> Namespace:
    return Namespace(
        symbol="ETHUSD",
        market="ETHUSD",
        resolution="MINUTE_5",
        interval_minutes=5,
        lookback=512,
        pred_len=12,
        env="demo",
        postgres_dsn=None,
        kronos_python=r"C:\\AI\\Kronos\\.venv\\Scripts\\python.exe",
        websocket_stale_seconds=90,
        once=False,
    )


class WebSocketGateTests(unittest.TestCase):
    def tearDown(self) -> None:
        main_prediction_scheduler._LAST_PROCESSED_WEBSOCKET_CANDLE.clear()

    def test_gate_blocks_when_websocket_is_stale(self):
        args = _args()
        now = pd.Timestamp("2026-05-02T12:00:00+00:00")
        responses = [
            [{"updated_at": now - pd.Timedelta(seconds=200), "timestamp_utc": now - pd.Timedelta(seconds=199), "source": "websocket_quote"}],
            [{"timestamp_utc": now - pd.Timedelta(minutes=5), "updated_at": now - pd.Timedelta(seconds=200)}],
            [{"status": "OK", "updated_at": now - pd.Timedelta(seconds=5)}],
        ]
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("main_prediction_scheduler.connect", return_value=_FakeConnection(responses)))
            _stack.enter_context(patch("main_prediction_scheduler.pd.Timestamp.now", return_value=now))
            gate = main_prediction_scheduler._websocket_prediction_gate(args)

        self.assertFalse(gate.allow)
        self.assertEqual("websocket_stale", gate.reason)
        self.assertEqual("paused_websocket_gate", gate.details.get("state"))

    def test_gate_blocks_when_no_new_websocket_candle(self):
        args = _args()
        now = pd.Timestamp("2026-05-02T12:00:00+00:00")
        latest_candle = pd.Timestamp("2026-05-02T11:55:00+00:00")
        main_prediction_scheduler._LAST_PROCESSED_WEBSOCKET_CANDLE[("ETHUSD", "MINUTE_5")] = latest_candle

        responses = [
            [{"updated_at": now - pd.Timedelta(seconds=3), "timestamp_utc": now - pd.Timedelta(seconds=2), "source": "websocket_quote"}],
            [{"timestamp_utc": latest_candle, "updated_at": now - pd.Timedelta(seconds=3)}],
            [{"status": "OK", "updated_at": now - pd.Timedelta(seconds=2)}],
        ]
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("main_prediction_scheduler.connect", return_value=_FakeConnection(responses)))
            _stack.enter_context(patch("main_prediction_scheduler.pd.Timestamp.now", return_value=now))
            gate = main_prediction_scheduler._websocket_prediction_gate(args)

        self.assertFalse(gate.allow)
        self.assertEqual("no_new_websocket_candle", gate.reason)


class SchedulerCycleGateTests(unittest.TestCase):
    def tearDown(self) -> None:
        main_prediction_scheduler._LAST_PROCESSED_WEBSOCKET_CANDLE.clear()

    def test_run_cycle_pauses_without_forecast_when_gate_blocks(self):
        args = _args()
        gate = main_prediction_scheduler.WebSocketPredictionGate(
            allow=False,
            reason="websocket_stale",
            details={"state": "paused_websocket_gate", "gate_reason": "websocket_stale"},
            latest_candle_timestamp_utc=None,
        )
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("main_prediction_scheduler._websocket_prediction_gate", return_value=gate))
            run_forecast = _stack.enter_context(patch("main_prediction_scheduler._run_forecast_command"))
            heartbeat = _stack.enter_context(patch("main_prediction_scheduler._heartbeat"))
            code = main_prediction_scheduler._run_cycle(args)

        self.assertEqual(0, code)
        run_forecast.assert_not_called()
        heartbeat.assert_called_once()
        self.assertEqual("PAUSED", heartbeat.call_args.args[1])

    def test_run_cycle_success_tracks_latest_websocket_candle(self):
        args = _args()
        candle_ts = "2026-05-02T11:55:00+00:00"
        gate = main_prediction_scheduler.WebSocketPredictionGate(
            allow=True,
            reason="ok",
            details={"state": "websocket_gate_passed", "gate_reason": "ok", "latest_websocket_candle_timestamp_utc": candle_ts},
            latest_candle_timestamp_utc=candle_ts,
        )
        result = subprocess.CompletedProcess(["python", "src/main_forecast_latest.py"], 0, "", "")
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch("main_prediction_scheduler._websocket_prediction_gate", return_value=gate))
            _stack.enter_context(patch("main_prediction_scheduler._run_forecast_command", return_value=result))
            _stack.enter_context(patch("main_prediction_scheduler._heartbeat"))
            code = main_prediction_scheduler._run_cycle(args)

        self.assertEqual(0, code)
        key = ("ETHUSD", "MINUTE_5")
        self.assertIn(key, main_prediction_scheduler._LAST_PROCESSED_WEBSOCKET_CANDLE)
        self.assertEqual(pd.Timestamp(candle_ts), main_prediction_scheduler._LAST_PROCESSED_WEBSOCKET_CANDLE[key])


if __name__ == "__main__":
    unittest.main()
