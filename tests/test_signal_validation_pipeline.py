from __future__ import annotations

import http.client
import contextlib
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from candle_context import validate_candle_frame
import dashboard_server
from forecast_normalizer import normalize_forecast
from higher_timeframe_validator import validate_single_timeframe
import main_run_kronos_predict
from signal_blockers import evaluate_hard_blockers
from signal_config import SignalConfig, load_signal_config
from signal_scoring import score_signal
from signal_validation_store import load_latest_signal_validation, save_signal_validation_run


class ForecastNormalizerTests(unittest.TestCase):
    def test_normalizer_calculates_core_metrics(self):
        input_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01", periods=5, freq="5min", tz="UTC"),
                "open": [100, 101, 102, 103, 104],
                "high": [101, 102, 103, 104, 105],
                "low": [99, 100, 101, 102, 103],
                "close": [100, 101, 102, 103, 104],
                "volume": [1, 1, 1, 1, 1],
                "amount": [0, 0, 0, 0, 0],
            }
        )
        forecast_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T00:25:00Z", periods=3, freq="5min", tz="UTC"),
                "open": [104.2, 104.8, 105.1],
                "high": [104.9, 105.5, 106.0],
                "low": [103.9, 104.5, 104.9],
                "close": [104.8, 105.2, 105.6],
                "volume": [1, 1, 1],
                "amount": [0, 0, 0],
            }
        )

        out = normalize_forecast(
            metadata={"resolution": "MINUTE_5", "symbol": "ETHUSD", "epic": "ETHUSD"},
            forecast=forecast_df,
            input_data=input_df,
            estimated_cost_pct=0.05,
            flat_threshold_pct=0.02,
        )

        self.assertAlmostEqual(1.5384615, out["forecast_return_pct"], places=5)
        self.assertAlmostEqual(153.84615, out["forecast_return_bps"], places=4)
        self.assertEqual("UP", out["forecast_direction"])
        self.assertAlmostEqual(0.05, out["estimated_cost_pct"], places=6)
        self.assertAlmostEqual(out["net_edge_pct"], abs(out["forecast_return_pct"]) - 0.05, places=6)


class HardBlockerTests(unittest.TestCase):
    def _cfg(self) -> SignalConfig:
        return load_signal_config()

    def test_blocks_flat_forecast(self):
        blockers = evaluate_hard_blockers(
            normalized_forecast={
                "candidate_signal": "HOLD",
                "forecast_direction": "FLAT",
                "net_edge_pct": 0.1,
            },
            primary_input_validation={"ok": True, "cadence_ok": True},
            context_fetch_status={"ok": True, "missing_timeframes": []},
            timeframe_validations=[],
            config=self._cfg(),
            market_context={"spread_pct": 0.01, "volume_zscore": 0.0, "atr_percentile": 50.0},
            database_available=True,
        )
        self.assertTrue(blockers["blocked"])
        self.assertIn("FORECAST_DIRECTION_FLAT", blockers["reason_codes"])

    def test_blocks_edge_below_cost(self):
        blockers = evaluate_hard_blockers(
            normalized_forecast={
                "candidate_signal": "LONG",
                "forecast_direction": "UP",
                "net_edge_pct": -0.01,
            },
            primary_input_validation={"ok": True, "cadence_ok": True},
            context_fetch_status={"ok": True, "missing_timeframes": []},
            timeframe_validations=[],
            config=self._cfg(),
            market_context={"spread_pct": 0.01, "volume_zscore": 0.0, "atr_percentile": 50.0},
            database_available=True,
        )
        self.assertTrue(blockers["blocked"])
        self.assertIn("FORECAST_EDGE_BELOW_COST", blockers["reason_codes"])

    def test_hold_candidate_is_not_forced_invalid(self):
        blockers = evaluate_hard_blockers(
            normalized_forecast={
                "candidate_signal": "HOLD",
                "forecast_direction": "UP",
                "net_edge_pct": 0.2,
            },
            primary_input_validation={"ok": True, "cadence_ok": True},
            context_fetch_status={"ok": True, "missing_timeframes": []},
            timeframe_validations=[],
            config=self._cfg(),
            market_context={"spread_pct": 0.01, "volume_zscore": 0.0, "atr_percentile": 50.0},
            database_available=True,
        )
        self.assertFalse(blockers["blocked"])
        self.assertNotIn("KRONOS_FORECAST_INVALID", blockers["reason_codes"])

    def test_low_volume_does_not_hard_block_by_default(self):
        blockers = evaluate_hard_blockers(
            normalized_forecast={
                "candidate_signal": "LONG",
                "forecast_direction": "UP",
                "net_edge_pct": 0.2,
            },
            primary_input_validation={"ok": True, "cadence_ok": True},
            context_fetch_status={"ok": True, "missing_timeframes": []},
            timeframe_validations=[],
            config=self._cfg(),
            market_context={"spread_pct": 0.01, "volume_zscore": -3.0, "atr_percentile": 50.0},
            database_available=True,
        )
        self.assertFalse(blockers["blocked"])
        self.assertNotIn("VERY_LOW_VOLUME", blockers["reason_codes"])


class CandleValidatorTests(unittest.TestCase):
    def test_rejects_duplicate_timestamps(self):
        ts = pd.Timestamp("2026-05-01T00:00:00Z")
        frame = pd.DataFrame(
            {
                "timestamps": [ts, ts],
                "open": [1.0, 1.1],
                "high": [1.2, 1.3],
                "low": [0.9, 1.0],
                "close": [1.1, 1.2],
                "volume": [1.0, 1.0],
                "amount": [0.0, 0.0],
            }
        )
        out = validate_candle_frame(frame, "MINUTE_5")
        self.assertFalse(out["ok"])
        self.assertTrue(any("Duplicate timestamps" in message for message in out["errors"]))

    def test_rejects_invalid_ohlc(self):
        frame = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01", periods=2, freq="5min", tz="UTC"),
                "open": [1.0, 1.0],
                "high": [0.8, 0.9],
                "low": [1.2, 1.1],
                "close": [1.1, 1.2],
                "volume": [1.0, 1.0],
                "amount": [0.0, 0.0],
            }
        )
        out = validate_candle_frame(frame, "MINUTE_5")
        self.assertFalse(out["ok"])
        self.assertTrue(any("OHLC invariant" in message for message in out["errors"]))

    def test_allows_single_cadence_gap_for_long_window(self):
        timestamps = pd.date_range("2026-05-01", periods=130, freq="5min", tz="UTC").tolist()
        del timestamps[60]
        frame = pd.DataFrame(
            {
                "timestamps": timestamps,
                "open": [1.0] * len(timestamps),
                "high": [1.2] * len(timestamps),
                "low": [0.8] * len(timestamps),
                "close": [1.1] * len(timestamps),
                "volume": [10.0] * len(timestamps),
                "amount": [0.0] * len(timestamps),
            }
        )
        out = validate_candle_frame(frame, "MINUTE_5")
        self.assertTrue(out["ok"])
        self.assertTrue(out["cadence_ok"])
        self.assertEqual(1, out.get("cadence_mismatch_count"))
        self.assertTrue(any("tolerated" in message for message in out["warnings"]))

    def test_allows_two_cadence_gaps_for_long_window(self):
        timestamps = pd.date_range("2026-05-01", periods=140, freq="5min", tz="UTC").tolist()
        for idx in sorted([80, 40], reverse=True):
            del timestamps[idx]
        frame = pd.DataFrame(
            {
                "timestamps": timestamps,
                "open": [1.0] * len(timestamps),
                "high": [1.2] * len(timestamps),
                "low": [0.8] * len(timestamps),
                "close": [1.1] * len(timestamps),
                "volume": [10.0] * len(timestamps),
                "amount": [0.0] * len(timestamps),
            }
        )
        out = validate_candle_frame(frame, "MINUTE_5")
        self.assertTrue(out["ok"])
        self.assertTrue(out["cadence_ok"])
        self.assertEqual(2, out.get("cadence_mismatch_count"))
        self.assertTrue(any("tolerated" in message for message in out["warnings"]))

    def test_rejects_cadence_gap_for_short_window(self):
        timestamps = pd.date_range("2026-05-01", periods=12, freq="5min", tz="UTC").tolist()
        del timestamps[5]
        frame = pd.DataFrame(
            {
                "timestamps": timestamps,
                "open": [1.0] * len(timestamps),
                "high": [1.2] * len(timestamps),
                "low": [0.8] * len(timestamps),
                "close": [1.1] * len(timestamps),
                "volume": [10.0] * len(timestamps),
                "amount": [0.0] * len(timestamps),
            }
        )
        out = validate_candle_frame(frame, "MINUTE_5")
        self.assertFalse(out["ok"])
        self.assertFalse(out["cadence_ok"])


class HigherTimeframeTrendTests(unittest.TestCase):
    def _frame(self, closes: list[float]) -> pd.DataFrame:
        rows = len(closes)
        return pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-01-01", periods=rows, freq="1h", tz="UTC"),
                "open": closes,
                "high": [value + 0.4 for value in closes],
                "low": [value - 0.4 for value in closes],
                "close": closes,
                "volume": [120 + index for index in range(rows)],
                "amount": [0.0] * rows,
            }
        )

    def test_classifies_bullish_trend(self):
        frame = self._frame([100 + (index * 0.6) for index in range(90)])
        with patch("higher_timeframe_validator.load_recent_candles", return_value=frame):
            result = validate_single_timeframe(
                symbol="ETHUSD",
                timeframe="HOUR",
                candidate_signal="LONG",
                now_utc=pd.Timestamp("2026-01-10T12:00:00Z"),
            )
        self.assertEqual("BULLISH", result["trend"])

    def test_classifies_bearish_trend(self):
        frame = self._frame([160 - (index * 0.6) for index in range(90)])
        with patch("higher_timeframe_validator.load_recent_candles", return_value=frame):
            result = validate_single_timeframe(
                symbol="ETHUSD",
                timeframe="HOUR",
                candidate_signal="SHORT",
                now_utc=pd.Timestamp("2026-01-10T12:00:00Z"),
            )
        self.assertEqual("BEARISH", result["trend"])

    def test_returns_neutral_for_mixed_context(self):
        closes = [100.0 for _ in range(90)]
        frame = self._frame(closes)
        with patch("higher_timeframe_validator.load_recent_candles", return_value=frame):
            result = validate_single_timeframe(
                symbol="ETHUSD",
                timeframe="HOUR",
                candidate_signal="LONG",
                now_utc=pd.Timestamp("2026-01-10T12:00:00Z"),
            )
        self.assertEqual("NEUTRAL", result["trend"])


class SignalScoringTests(unittest.TestCase):
    def _cfg(self) -> SignalConfig:
        return load_signal_config()

    def _timeframes_full(self) -> list[dict]:
        return [
            {"timeframe": "MINUTE_15", "trend_score": 8, "momentum_score": 2, "volume_score": 2, "volatility_score": 1, "support_resistance_score": 1},
            {"timeframe": "MINUTE_30", "trend_score": 6, "momentum_score": 2, "volume_score": 2, "volatility_score": 1, "support_resistance_score": 1},
            {"timeframe": "HOUR", "trend_score": 8, "momentum_score": 2, "volume_score": 2, "volatility_score": 1, "support_resistance_score": 1},
            {"timeframe": "HOUR_4", "trend_score": 3, "momentum_score": 2, "volume_score": 2, "volatility_score": 1, "support_resistance_score": 1},
        ]

    def test_scoring_maps_final_signals(self):
        cfg = self._cfg()
        base_norm = {
            "candidate_signal": "LONG",
            "net_edge_pct": 1.0,
            "forecast_path_consistency_score": 100.0,
            "forecast_quality_score": 95.0,
        }
        open_blockers = {"blocked": False}

        strong = score_signal(
            normalized_forecast=base_norm,
            timeframe_validations=self._timeframes_full(),
            blockers=open_blockers,
            config=cfg,
            market_context={"spread_pct": 0.01},
        )
        self.assertEqual("STRONG_LONG", strong["final_signal"])

        long_result = score_signal(
            normalized_forecast={**base_norm, "net_edge_pct": 0.25, "forecast_path_consistency_score": 70.0, "forecast_quality_score": 70.0},
            timeframe_validations=[
                {"timeframe": "MINUTE_30", "trend_score": 6, "momentum_score": 1, "volume_score": 1, "volatility_score": 1, "support_resistance_score": 1},
                {"timeframe": "HOUR", "trend_score": 8, "momentum_score": 1, "volume_score": 1, "volatility_score": 1, "support_resistance_score": 1},
            ],
            blockers=open_blockers,
            config=cfg,
            market_context={"spread_pct": 0.02},
        )
        self.assertEqual("LONG", long_result["final_signal"])

        watch_result = score_signal(
            normalized_forecast={**base_norm, "net_edge_pct": 0.1, "forecast_path_consistency_score": 45.0, "forecast_quality_score": 50.0},
            timeframe_validations=[{"timeframe": "HOUR", "trend_score": 6, "momentum_score": 1, "volume_score": 1, "volatility_score": 1, "support_resistance_score": 1}],
            blockers=open_blockers,
            config=cfg,
            market_context={"spread_pct": 0.05},
        )
        self.assertEqual("WATCH", watch_result["final_signal"])

        hold_result = score_signal(
            normalized_forecast={**base_norm, "net_edge_pct": 0.01, "forecast_path_consistency_score": 20.0, "forecast_quality_score": 20.0},
            timeframe_validations=[{"timeframe": "HOUR", "trend_score": 0, "momentum_score": 0, "volume_score": 0, "volatility_score": 0, "support_resistance_score": 0}],
            blockers=open_blockers,
            config=cfg,
            market_context={"spread_pct": 0.2},
        )
        self.assertEqual("HOLD", hold_result["final_signal"])

        blocked = score_signal(
            normalized_forecast=base_norm,
            timeframe_validations=self._timeframes_full(),
            blockers={"blocked": True, "block_reason": "FORECAST_EDGE_BELOW_COST", "reason_codes": ["FORECAST_EDGE_BELOW_COST"], "reason_details": ["edge too low"]},
            config=cfg,
            market_context={"spread_pct": 0.01},
        )
        self.assertEqual("BLOCKED", blocked["final_signal"])

    def test_low_volume_applies_score_penalty(self):
        cfg = self._cfg()
        result = score_signal(
            normalized_forecast={
                "candidate_signal": "LONG",
                "net_edge_pct": 0.25,
                "forecast_path_consistency_score": 70.0,
                "forecast_quality_score": 70.0,
            },
            timeframe_validations=[
                {"timeframe": "HOUR", "trend_score": 8, "momentum_score": 1, "volume_score": 1, "volatility_score": 1, "support_resistance_score": 1},
            ],
            blockers={"blocked": False},
            config=cfg,
            market_context={"spread_pct": 0.02, "volume_zscore": -2.5},
        )
        self.assertLess(result["component_scores"]["cost_liquidity"], 10.0)
        self.assertTrue(any("Very low volume context reduced" in item for item in result["reason_details"]))


class MigrationIdempotenceTests(unittest.TestCase):
    def test_migration_contains_idempotent_statements(self):
        migration_path = ROOT / "migrations" / "002_signal_validation_scoring.sql"
        sql_text = migration_path.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS signal_validation_runs", sql_text)
        self.assertIn("CREATE TABLE IF NOT EXISTS signal_timeframe_validations", sql_text)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_signal_validation_runs_created", sql_text)
        self.assertIn("ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_score", sql_text)
        self.assertIn("ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_status", sql_text)
        self.assertIn("ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_summary", sql_text)


class _FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        if self._row is None:
            return []
        if isinstance(self._row, list):
            return self._row
        return [self._row]


class _FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)

    def execute(self, *_args, **_kwargs):
        if not self.responses:
            return _FakeResult(None)
        return _FakeResult(self.responses.pop(0))

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class SignalValidationStoreTests(unittest.TestCase):
    def test_can_save_and_load_validation_rows(self):
        save_row = {
            "run_id": "RUN_1",
            "final_signal": "LONG",
            "total_score": 78.5,
            "blocked": False,
            "block_reason": None,
        }
        load_row = {
            "run_id": "RUN_1",
            "symbol": "ETHUSD",
            "final_signal": "LONG",
            "total_score": 78.5,
            "blocked": False,
        }

        with patch("signal_validation_store.connect", return_value=_FakeConnection([save_row])):
            save_out = save_signal_validation_run(
                {
                    "run_id": "RUN_1",
                    "symbol": "ETHUSD",
                    "epic": "ETHUSD",
                    "base_resolution": "MINUTE_5",
                    "candidate_signal": "LONG",
                    "final_signal": "LONG",
                    "forecast_direction": "UP",
                    "confidence_level": "HIGH",
                    "total_score": 78.5,
                }
            )

        with patch("signal_validation_store.connect", return_value=_FakeConnection([load_row])):
            loaded = load_latest_signal_validation("ETHUSD")

        self.assertTrue(save_out.get("ok"))
        self.assertEqual("RUN_1", save_out["saved"]["run_id"])
        self.assertEqual("RUN_1", loaded["run_id"])
        self.assertEqual("LONG", loaded["final_signal"])

    def test_timeframe_save_handles_null_timestamp(self):
        from signal_validation_store import save_timeframe_validations

        class _TimestampAssertingConnection(_FakeConnection):
            def execute(self, _query, params=None):
                if isinstance(params, dict) and "timestamp_utc" in params:
                    assert params["timestamp_utc"] is not None
                return _FakeResult(None)

        with patch("signal_validation_store.connect", return_value=_TimestampAssertingConnection([])):
            out = save_timeframe_validations(
                "RUN_NULL_TS",
                [
                    {
                        "timeframe": "HOUR",
                        "timestamp_utc": None,
                        "trend": "NEUTRAL",
                        "confirms_candidate": False,
                        "trend_score": 0,
                        "momentum_score": 0,
                        "volume_score": 0,
                        "volatility_score": 0,
                        "support_resistance_score": 0,
                        "total_timeframe_score": 0,
                        "indicator_snapshot": {},
                        "reason_details": ["cadence mismatch"],
                    }
                ],
            )
        self.assertTrue(out.get("ok"))


class DashboardStatusApiTests(unittest.TestCase):
    def _request_status(self, snapshot: dict) -> tuple[int, dict]:
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(dashboard_server, "_latest_metadata", return_value=(None, {})))
            _stack.enter_context(patch.object(dashboard_server, "_quality_report_for_metadata", return_value=(None, {})))
            _stack.enter_context(patch.object(dashboard_server, "_safe_csv", return_value=[]))
            _stack.enter_context(patch.object(dashboard_server, "_latest_file", return_value=None))
            _stack.enter_context(patch.object(dashboard_server, "_history", return_value=[]))
            _stack.enter_context(patch.object(dashboard_server, "_prediction_db_summary", return_value={"recent_runs": []}))
            _stack.enter_context(patch.object(dashboard_server, "_postgres_snapshot", return_value=snapshot))
            _stack.enter_context(patch.object(dashboard_server, "_auto_finetune_status", return_value={}))
            _stack.enter_context(
                patch.object(
                    dashboard_server,
                    "_trade_execution_status",
                    return_value={"ok": True, "queue": {}, "trades": [], "active_trades": [], "pending_trades": [], "historical_trades": []},
                )
            )
            server = dashboard_server.ThreadingHTTPServer(("127.0.0.1", 0), dashboard_server.DashboardHandler)
            try:
                port = server.server_address[1]
                thread = threading.Thread(target=server.handle_request, daemon=True)
                thread.start()
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/status")
                response = conn.getresponse()
                body = response.read().decode("utf-8")
                conn.close()
                thread.join(timeout=5)
                return response.status, json.loads(body)
            finally:
                server.server_close()

    def test_status_returns_validation_payload_when_available(self):
        status, payload = self._request_status(
            {
                "postgres": {"ok": True},
                "candles": [],
                "signals": [],
                "live_quote": {},
                "live_health": {},
                "worker_statuses": {},
                "prediction_db": {"recent_runs": []},
                "latest_validation": {},
                "signal_validation": {
                    "run_id": "RUN_1",
                    "candidate_signal": "LONG",
                    "final_signal": "LONG",
                    "confidence_level": "HIGH",
                    "total_score": 78.5,
                    "blocked": False,
                    "block_reason": None,
                    "component_scores": {},
                    "reason_codes": [],
                    "reason_details": [],
                },
                "timeframe_validations": [{"timeframe": "HOUR", "trend": "BULLISH"}],
                "active_model": None,
                "shadow_model": None,
                "rate_limits": [],
                "supervisor_lease": None,
                "horizon_metrics": [],
            }
        )

        self.assertEqual(200, status)
        self.assertIn("signal_validation", payload)
        self.assertIn("timeframe_validations", payload)
        self.assertEqual("LONG", payload["signal_validation"]["final_signal"])

    def test_status_still_returns_json_when_validation_tables_missing(self):
        status, payload = self._request_status(
            {
                "postgres": {"ok": True},
                "candles": [],
                "signals": [],
                "live_quote": {},
                "live_health": {},
                "worker_statuses": {},
                "prediction_db": {"recent_runs": []},
                "latest_validation": {},
                "signal_validation": {
                    "ok": False,
                    "error": "validation_tables_missing",
                    "reason": "relation signal_validation_runs does not exist",
                },
                "timeframe_validations": [],
                "active_model": None,
                "shadow_model": None,
                "rate_limits": [],
                "supervisor_lease": None,
                "horizon_metrics": [],
            }
        )

        self.assertEqual(200, status)
        self.assertIn("signal_validation", payload)
        self.assertEqual("validation_tables_missing", payload["signal_validation"]["error"])
        self.assertTrue(any("Signal validation tables are missing" in item for item in payload.get("status_warnings", [])))


class PredictionFlowWithoutCredentialsTests(unittest.TestCase):
    def test_non_strict_validation_failure_does_not_raise(self):
        with patch("main_validate_signal_context.run_validation_for_run", return_value={"ok": False, "error": "credentials missing"}):
            out = main_run_kronos_predict._run_external_signal_validation(
                run_id="RUN_1",
                dsn=None,
                env_name="demo",
                prediction_request_id="req_1",
                signal_validation_enabled_override="true",
                signal_validation_strict_override="false",
            )
        self.assertFalse(out["ok"])
        self.assertEqual("VALIDATION_UNAVAILABLE", out["final_signal"])


if __name__ == "__main__":
    unittest.main()
