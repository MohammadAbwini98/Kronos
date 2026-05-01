from __future__ import annotations

from pathlib import Path
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
        with (
            patch.dict("os.environ", {"CAPITAL_DEFAULT_RESOLUTION": "MINUTE_5"}, clear=True),
            patch.object(sys, "argv", ["main_prediction_scheduler.py"]),
        ):
            args = main_prediction_scheduler.parse_args()

        self.assertEqual("MINUTE_5", args.resolution)
        self.assertEqual(5, args.interval_minutes)

    def test_signal_interval_override_wins(self):
        with (
            patch.dict(
                "os.environ",
                {"CAPITAL_DEFAULT_RESOLUTION": "MINUTE_5", "SIGNAL_INTERVAL_MINUTES": "1"},
                clear=True,
            ),
            patch.object(sys, "argv", ["main_prediction_scheduler.py"]),
        ):
            args = main_prediction_scheduler.parse_args()

        self.assertEqual("MINUTE_5", args.resolution)
        self.assertEqual(1, args.interval_minutes)


if __name__ == "__main__":
    unittest.main()
