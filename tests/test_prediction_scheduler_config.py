from __future__ import annotations

from pathlib import Path
import contextlib
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_prediction_scheduler


class SchedulerConfigTests(unittest.TestCase):
    def test_default_resolution_uses_capital_default_and_matching_interval(self):
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.dict("os.environ", {"CAPITAL_DEFAULT_RESOLUTION": "MINUTE_5"}, clear=True))
            _stack.enter_context(patch.object(sys, "argv", ["main_prediction_scheduler.py"]))
            args = main_prediction_scheduler.parse_args()

        self.assertEqual("MINUTE_5", args.resolution)
        self.assertEqual(5, args.interval_minutes)

    def test_signal_interval_override_wins(self):
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.dict(
                "os.environ",
                {"CAPITAL_DEFAULT_RESOLUTION": "MINUTE_5", "SIGNAL_INTERVAL_MINUTES": "1"},
                clear=True,
            ))
            _stack.enter_context(patch.object(sys, "argv", ["main_prediction_scheduler.py"]))
            args = main_prediction_scheduler.parse_args()

        self.assertEqual("MINUTE_5", args.resolution)
        self.assertEqual(1, args.interval_minutes)

    def test_default_kronos_python_uses_current_interpreter(self):
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.dict("os.environ", {}, clear=True))
            _stack.enter_context(patch.object(sys, "argv", ["main_prediction_scheduler.py"]))
            args = main_prediction_scheduler.parse_args()

        self.assertEqual(sys.executable, args.kronos_python)
        self.assertIsNone(args.kronos_python_warning)

    def test_missing_kronos_python_falls_back_with_warning(self):
        missing_path = str(ROOT / "missing-python.exe")
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.dict("os.environ", {"KRONOS_PYTHON": missing_path}, clear=True))
            _stack.enter_context(patch.object(sys, "argv", ["main_prediction_scheduler.py"]))
            args = main_prediction_scheduler.parse_args()

        self.assertEqual(sys.executable, args.kronos_python)
        self.assertIn("kronos_python_path_not_found", args.kronos_python_warning)

    def test_existing_kronos_python_env_is_used(self):
        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.dict("os.environ", {"KRONOS_PYTHON": sys.executable}, clear=True))
            _stack.enter_context(patch.object(sys, "argv", ["main_prediction_scheduler.py"]))
            args = main_prediction_scheduler.parse_args()

        self.assertEqual(sys.executable, args.kronos_python)
        self.assertIsNone(args.kronos_python_warning)

    def test_sleep_heartbeat_preserves_last_cycle_error_status(self):
        args = type(
            "Args",
            (),
            {
                "interval_minutes": 5,
                "symbol": "ETHUSD",
                "resolution": "MINUTE_5",
                "postgres_dsn": None,
            },
        )()

        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(main_prediction_scheduler.time, "sleep", return_value=None))
            heartbeat = _stack.enter_context(patch.object(main_prediction_scheduler, "_heartbeat"))
            main_prediction_scheduler._sleep_to_next_boundary(
                args,
                heartbeat_interval_seconds=1,
                last_cycle_status="ERROR",
                last_cycle_details={"last_cycle_returncode": 1},
            )

        self.assertTrue(heartbeat.call_args_list)
        self.assertEqual("ERROR", heartbeat.call_args_list[0].args[1])
        self.assertEqual("sleeping_after_error", heartbeat.call_args_list[0].args[2]["state"])


if __name__ == "__main__":
    unittest.main()
