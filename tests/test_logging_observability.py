from __future__ import annotations

import io
import contextlib
import json
import logging
from argparse import Namespace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server
import logging_utils
import main_prediction_scheduler
import main_validation_worker
import subprocess_utils
from config import _DailyLogFileHandler, configure_logging


def _json_messages(stream: io.StringIO) -> list[dict]:
    payloads: list[dict] = []
    for line in stream.getvalue().splitlines():
        line = line.strip()
        if not line:
            continue
        payloads.append(json.loads(line))
    return payloads


class LoggingUtilsMaskingTests(unittest.TestCase):
    def test_mask_dsn_masks_password(self):
        masked = logging_utils.mask_dsn("postgresql://user:topsecret@localhost:5432/app")
        self.assertIn("user:***@localhost:5432", masked)
        self.assertNotIn("topsecret", masked)

    def test_safe_log_dict_masks_sensitive_fields(self):
        payload = {
            "password": "abc12345",
            "postgres_dsn": "postgresql://user:verysecret@localhost:5432/app",
            "nested": {"token": "tok_123456"},
        }
        safe = logging_utils.safe_log_dict(payload)
        self.assertEqual("***", safe["password"])
        self.assertIn("user:***@localhost:5432", safe["postgres_dsn"])
        self.assertEqual("tok_...3456", safe["nested"]["token"])


class ConfigureLoggingDedupeTests(unittest.TestCase):
    def tearDown(self) -> None:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if getattr(handler, "_capital_managed", False):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

    def test_configure_logging_deduplicates_managed_handlers(self):
        with patch.dict("os.environ", {"LOG_TO_CONSOLE": "0", "LOG_TO_FILE": "0"}, clear=False):
            configure_logging(service_name="unit_test")
            root_logger = logging.getLogger()
            first_count = sum(1 for h in root_logger.handlers if getattr(h, "_capital_managed", False))
            configure_logging(service_name="unit_test")
            second_count = sum(1 for h in root_logger.handlers if getattr(h, "_capital_managed", False))

        self.assertEqual(1, first_count)
        self.assertEqual(1, second_count)

    def test_daily_file_handler_rotates_when_size_limit_reached(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            handler = _DailyLogFileHandler(log_dir, max_bytes=60, backup_count=2)
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                record = logging.LogRecord("unit", logging.INFO, __file__, 1, "x" * 80, (), None)
                handler.emit(record)
                handler.emit(record)
            finally:
                handler.close()

            current = next(log_dir.glob("log_*.log"))
            rotated = log_dir / f"{current.name}.1"
            self.assertTrue(rotated.exists())
            self.assertGreater(rotated.stat().st_size, 0)

    def test_configure_logging_uses_service_specific_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "CAPITAL_LOG_DIR": temp_dir,
                    "LOG_TO_CONSOLE": "0",
                    "LOG_TO_FILE": "1",
                },
                clear=False,
            ):
                configure_logging(service_name="db_migrate")
                logging.getLogger("unit.service_file").info("hello")
                self.tearDown()

            files = list(Path(temp_dir).glob("log_*_db_migrate.log"))
            self.assertEqual(1, len(files))

    def test_daily_file_handler_does_not_raise_when_rotation_file_is_locked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            handler = _DailyLogFileHandler(log_dir, max_bytes=10, backup_count=2)
            handler.setFormatter(logging.Formatter("%(message)s"))
            try:
                record = logging.LogRecord("unit", logging.INFO, __file__, 1, "x" * 20, (), None)
                handler.emit(record)
                with patch("config.os.replace", side_effect=PermissionError("locked")):
                    handler.emit(record)
            finally:
                handler.close()


class TimedStepTests(unittest.TestCase):
    def test_timed_step_logs_start_and_completed(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("test.timed_step.ok")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        with logging_utils.timed_step(logger, "unit.step", request_id="req_1"):
            pass

        payloads = _json_messages(stream)
        events = [item.get("event") for item in payloads]
        self.assertIn("unit.step.start", events)
        self.assertIn("unit.step.completed", events)

    def test_timed_step_logs_error(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("test.timed_step.error")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        with self.assertRaises(RuntimeError):
            with logging_utils.timed_step(logger, "unit.step", request_id="req_1"):
                raise RuntimeError("boom")

        payloads = _json_messages(stream)
        events = [item.get("event") for item in payloads]
        self.assertIn("unit.step.start", events)
        self.assertIn("unit.step.error", events)


class SubprocessObservabilityTests(unittest.TestCase):
    def test_run_logged_subprocess_masks_command_and_output(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("test.subprocess")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        cmd = ["python", "task.py", "--password", "supersecret"]
        fake_result = subprocess.CompletedProcess(cmd, 1, "token=abc123", "password=supersecret")

        with patch.object(subprocess_utils.subprocess, "run", return_value=fake_result):
            result = subprocess_utils.run_logged_subprocess(cmd, logger, "unit.subprocess")

        self.assertEqual(1, result.returncode)
        payloads = _json_messages(stream)
        start = next(item for item in payloads if item.get("event") == "unit.subprocess.start")
        error = next(item for item in payloads if item.get("event") == "unit.subprocess.error")
        self.assertIn("--password", start.get("command", []))
        self.assertNotIn("supersecret", json.dumps(start))
        self.assertNotIn("supersecret", json.dumps(error))
        self.assertIn("password=***", error.get("output_tail", ""))


class DashboardRunLoggingTests(unittest.TestCase):
    def test_dashboard_run_logs_request_id(self):
        cmd = ["python", "-V"]
        fake_result = subprocess.CompletedProcess(cmd, 0, "ok", "")
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(dashboard_server.subprocess, "run", return_value=fake_result))
            mocked_log_event = _stack.enter_context(patch.object(dashboard_server, "log_event"))
            dashboard_server._run(cmd, request_id="req_test", endpoint="/api/test")

        events = [call.args[2] for call in mocked_log_event.call_args_list]
        self.assertIn("dashboard.subprocess.start", events)
        start_call = next(call for call in mocked_log_event.call_args_list if call.args[2] == "dashboard.subprocess.start")
        self.assertEqual("req_test", start_call.kwargs.get("request_id"))


class CycleCorrelationIdTests(unittest.TestCase):
    def _scheduler_args(self) -> Namespace:
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

    def test_scheduler_cycle_logs_scheduler_cycle_id(self):
        gate = main_prediction_scheduler.WebSocketPredictionGate(
            allow=False,
            reason="websocket_stale",
            details={"state": "paused_websocket_gate", "gate_reason": "websocket_stale"},
            latest_candle_timestamp_utc=None,
        )
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(main_prediction_scheduler, "new_correlation_id", return_value="sched_test_id"))
            _stack.enter_context(patch.object(main_prediction_scheduler, "_websocket_prediction_gate", return_value=gate))
            _stack.enter_context(patch.object(main_prediction_scheduler, "_heartbeat"))
            mocked_log_event = _stack.enter_context(patch.object(main_prediction_scheduler, "log_event"))
            main_prediction_scheduler._run_cycle(self._scheduler_args())

        cycle_start = next(call for call in mocked_log_event.call_args_list if call.args[2] == "scheduler.cycle.start")
        gate_pause = next(call for call in mocked_log_event.call_args_list if call.args[2] == "scheduler.websocket_gate.pause")
        self.assertEqual("sched_test_id", cycle_start.kwargs.get("scheduler_cycle_id"))
        self.assertEqual("sched_test_id", gate_pause.kwargs.get("scheduler_cycle_id"))

    def test_validation_cycle_logs_validation_cycle_id(self):
        args = Namespace(batch_size=5, postgres_dsn=None, env="demo")
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(main_validation_worker, "_due_runs", return_value=[]))
            _stack.enter_context(patch.object(main_validation_worker, "refresh_shadow_prediction_statuses", return_value={"checked": 0, "updated": 0, "pending": 0, "errors": 0}))
            mocked_log_event = _stack.enter_context(patch.object(main_validation_worker, "log_event"))
            payload = main_validation_worker._run_validation_cycle(args, "val_test_id")

        cycle_start = next(call for call in mocked_log_event.call_args_list if call.args[2] == "validation.cycle.start")
        cycle_completed = next(call for call in mocked_log_event.call_args_list if call.args[2] == "validation.cycle.completed")
        self.assertEqual("val_test_id", cycle_start.kwargs.get("validation_cycle_id"))
        self.assertEqual("val_test_id", cycle_completed.kwargs.get("validation_cycle_id"))
        self.assertEqual("val_test_id", payload.get("validation_cycle_id"))


if __name__ == "__main__":
    unittest.main()
