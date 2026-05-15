from __future__ import annotations

from pathlib import Path
import contextlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server
import main_run_kronos_predict
import prediction_store
from prediction_input_quality import evaluate_strict_input_policy, feature_mode_for_columns, select_feature_columns


def _window(start: str = "2026-05-01T10:00:00Z", rows: int = 4) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=rows, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [10.0] * rows,
            "amount": [0.0] * rows,
        }
    )


class StrictInputPolicyTests(unittest.TestCase):
    def test_candle_gap_hard_blocks(self):
        df = _window(rows=4)
        df.loc[2, "timestamps"] = pd.Timestamp("2026-05-01T10:20:00Z")

        decision = evaluate_strict_input_policy(
            df,
            resolution="MINUTE_5",
            requested_lookback=4,
            now_utc=pd.Timestamp("2026-05-01T10:30:00Z"),
        )

        self.assertFalse(decision.allow)
        self.assertIn("missing_candle_count", decision.reason)
        self.assertTrue(decision.checks["gap_list"])

    def test_stale_terminal_candle_hard_blocks(self):
        decision = evaluate_strict_input_policy(
            _window(rows=4),
            resolution="MINUTE_5",
            requested_lookback=4,
            now_utc=pd.Timestamp("2026-05-01T11:30:00Z"),
        )

        self.assertFalse(decision.allow)
        self.assertIn("stale", decision.reason)

    def test_unclosed_terminal_candle_hard_blocks(self):
        decision = evaluate_strict_input_policy(
            _window(start="2026-05-01T10:40:00Z", rows=4),
            resolution="MINUTE_5",
            requested_lookback=4,
            now_utc=pd.Timestamp("2026-05-01T10:58:00Z"),
        )

        self.assertFalse(decision.allow)
        self.assertIn("not closed", decision.reason)

    def test_duplicate_timestamp_hard_blocks(self):
        df = _window(rows=4)
        df.loc[3, "timestamps"] = df.loc[2, "timestamps"]

        decision = evaluate_strict_input_policy(
            df,
            resolution="MINUTE_5",
            requested_lookback=4,
            now_utc=pd.Timestamp("2026-05-01T10:25:00Z"),
        )

        self.assertFalse(decision.allow)
        self.assertIn("duplicate_timestamp_count", decision.reason)

    def test_source_counts_metadata_and_explicit_amount_feature_mode(self):
        df = _window(rows=4)
        df["source"] = ["latest_fetch", "latest_fetch", "websocket_ohlc", "latest_fetch"]
        feature_columns = select_feature_columns(df, "auto")
        decision = evaluate_strict_input_policy(
            df,
            resolution="MINUTE_5",
            requested_lookback=4,
            now_utc=pd.Timestamp("2026-05-01T10:25:00Z"),
            selected_feature_columns=feature_columns,
        )

        self.assertTrue(decision.allow)
        self.assertEqual({"latest_fetch": 3, "websocket_ohlc": 1}, decision.checks["source_counts"])
        self.assertEqual(["open", "high", "low", "close", "volume"], feature_columns)
        self.assertEqual("OHLCV_ONLY", feature_mode_for_columns(feature_columns, amount_available=False))


class ForecastTimestampEqualityTests(unittest.TestCase):
    def test_forecast_timestamp_equality_check_reports_mismatch(self):
        pred = pd.DataFrame(
            {
                "timestamps": [
                    "2026-05-01T10:05:00Z",
                    "2026-05-01T10:15:00Z",
                ]
            }
        )

        mismatches = main_run_kronos_predict._forecast_timestamp_mismatches(
            pred,
            last_input_timestamp=pd.Timestamp("2026-05-01T10:00:00Z"),
            resolution="MINUTE_5",
        )

        self.assertEqual(1, len(mismatches))
        self.assertEqual("2026-05-01T10:10:00+00:00", mismatches[0]["expected_timestamp_utc"])


class WebSocketUpsertPreservationTests(unittest.TestCase):
    def test_websocket_upsert_preserves_existing_volume_amount_when_incoming_missing(self):
        captured = {}

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def executemany(self, sql, rows):
                captured["sql"] = sql
                captured["rows"] = rows

        class _Connection:
            def cursor(self):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        df = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T10:00:00Z",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": None,
                    "amount": None,
                }
            ]
        )

        with patch.object(prediction_store, "connect", return_value=_Connection()):
            prediction_store.upsert_ohlcv_df(
                df,
                symbol="ETHUSD",
                epic="ETHUSD",
                resolution="MINUTE_5",
                price_side="mid",
                source="websocket_ohlc",
            )

        self.assertIn("preserved_volume_from_existing", captured["sql"])
        self.assertIn("preserved_amount_from_existing", captured["sql"])
        raw_payload = captured["rows"][0][-1]
        self.assertTrue(raw_payload.obj["incoming_volume_missing"])
        self.assertTrue(raw_payload.obj["incoming_amount_missing"])

    def test_websocket_zero_volume_amount_are_treated_as_unavailable(self):
        captured = {}

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def executemany(self, sql, rows):
                captured["sql"] = sql
                captured["rows"] = rows

        class _Connection:
            def cursor(self):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        df = pd.DataFrame(
            [
                {
                    "timestamps": "2026-05-01T10:00:00Z",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 0,
                    "amount": 0,
                }
            ]
        )

        with patch.object(prediction_store, "connect", return_value=_Connection()):
            prediction_store.upsert_ohlcv_df(
                df,
                symbol="ETHUSD",
                epic="ETHUSD",
                resolution="MINUTE_5",
                price_side="mid",
                source="websocket_ohlc",
            )

        self.assertIn("websocket_provisional", captured["sql"])
        raw_payload = captured["rows"][0][-1]
        self.assertTrue(raw_payload.obj["incoming_volume_missing"])
        self.assertTrue(raw_payload.obj["incoming_amount_missing"])


class MetadataAuditFieldTests(unittest.TestCase):
    def test_metadata_writes_top_level_input_audit_fields(self):
        input_df = _window(rows=2)
        pred_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T10:10:00Z", periods=2, freq="5min", tz="UTC"),
                "open": [102.0, 103.0],
                "high": [103.0, 104.0],
                "low": [101.0, 102.0],
                "close": [102.5, 103.5],
                "volume": [1.0, 1.0],
                "amount": [0.0, 0.0],
            }
        )
        quality = {
            "missing_candle_count": 0,
            "largest_gap_minutes": 5,
            "gap_list": [],
            "source_counts": {"latest_fetch": 2},
            "selected_feature_columns": ["open", "high", "low", "close", "volume"],
            "strict_policy_passed": True,
            "amount_available": False,
            "volume_available": True,
        }

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "metadata.json"
            main_run_kronos_predict._write_metadata(
                path,
                epic="ETHUSD",
                market_name="Ethereum",
                resolution="MINUTE_5",
                price_side="mid",
                input_rows_used=2,
                forecast_rows=2,
                model_name="Kronos-base",
                model_dir=Path("model"),
                tokenizer_dir=Path("tokenizer"),
                source="Capital.com",
                generated_at_utc="2026-05-01T10:00:00+00:00",
                input_df=input_df,
                pred_df=pred_df,
                forecast_csv=Path("forecast.csv"),
                input_copy_csv=Path("input.csv"),
                validation_report=Path("validation.json"),
                selected_feature_columns=["open", "high", "low", "close", "volume"],
                feature_mode="OHLCV_ONLY",
                input_quality_snapshot=quality,
            )

            metadata = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, metadata["input_missing_candle_count"])
        self.assertEqual(5, metadata["input_largest_gap_minutes"])
        self.assertEqual({"latest_fetch": 2}, metadata["input_source_counts"])
        self.assertEqual(["open", "high", "low", "close", "volume"], metadata["input_feature_columns"])
        self.assertEqual("UNAVAILABLE", metadata["amount_mode"])
        self.assertTrue(metadata["input_closed_candle_verified"])
        self.assertTrue(metadata["forecast_timestamp_verified"])


class DashboardLookbackTests(unittest.TestCase):
    def test_dashboard_predict_honors_supported_lookback_in_max_argument(self):
        captured = {}

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "output": "ok"}

        responses = []

        class _Handler:
            _request_id = "req-1"

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(dashboard_server, "_run", side_effect=fake_run))
            stack.enter_context(patch.object(dashboard_server, "_latest_file", return_value=None))
            stack.enter_context(patch.object(dashboard_server, "_json_response", side_effect=lambda _self, _status, payload: responses.append(payload)))
            dashboard_server.DashboardHandler._predict(
                _Handler(),
                {"market": "ETHUSD", "symbol": "ETHUSD", "resolution": "MINUTE_5", "lookback": 256, "pred_len": 12},
            )

        max_index = captured["cmd"].index("--max")
        self.assertEqual("256", captured["cmd"][max_index + 1])
        self.assertEqual("completed", responses[0]["status"])

    def test_dashboard_predict_rejects_lookback_above_supported_context(self):
        errors = []

        class _Handler:
            _request_id = "req-1"

        with patch.object(dashboard_server, "_error_response", side_effect=lambda _self, status, code, message, details=None: errors.append((status, code, message))):
            dashboard_server.DashboardHandler._predict(
                _Handler(),
                {"market": "ETHUSD", "symbol": "ETHUSD", "resolution": "MINUTE_5", "lookback": 2048, "pred_len": 12},
            )

        self.assertEqual(400, errors[0][0])
        self.assertIn("50-512", errors[0][2])


class Phase2MigrationTests(unittest.TestCase):
    def test_phase2_migration_contains_rejection_and_quality_fields(self):
        sql = (ROOT / "migrations" / "016_phase2_input_integrity.sql").read_text(encoding="utf-8")

        for expected in (
            "prediction_input_rejections",
            "gap_list",
            "feature_mode",
            "input_quality_snapshot",
            "forecast_timestamp_mismatches",
        ):
            self.assertIn(expected, sql)


if __name__ == "__main__":
    unittest.main()
