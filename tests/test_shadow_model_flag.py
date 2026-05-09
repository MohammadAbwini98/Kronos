from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_forecast_latest


class ShadowModelFlagTests(unittest.TestCase):
    def test_shadow_model_follows_auto_finetune_when_not_explicit(self):
        with patch.dict("os.environ", {"ENABLE_AUTO_FINETUNE": "false"}, clear=True):
            self.assertFalse(main_forecast_latest._shadow_model_enabled())

    def test_shadow_model_explicit_flag_overrides_auto_finetune(self):
        with patch.dict(
            "os.environ",
            {"ENABLE_AUTO_FINETUNE": "false", "ENABLE_SHADOW_MODEL": "true"},
            clear=False,
        ):
            self.assertTrue(main_forecast_latest._shadow_model_enabled())


if __name__ == "__main__":
    unittest.main()
