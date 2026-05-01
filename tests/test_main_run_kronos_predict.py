from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_run_kronos_predict


class AutoFinetunedModelSelectionTests(unittest.TestCase):
    def test_unapproved_or_incomplete_models_are_not_selected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            model_dir = output_dir / "candidate_model"
            model_dir.mkdir(parents=True, exist_ok=True)

            self.assertIsNone(main_run_kronos_predict._auto_finetuned_model_dir(output_dir))

            status_path = output_dir / "auto_finetune_status.json"

            status_path.write_text(json.dumps({"active_model_path": str(model_dir)}), encoding="utf-8")
            self.assertIsNone(main_run_kronos_predict._auto_finetuned_model_dir(output_dir))

            status_path.write_text(
                json.dumps({"active_model_path": str(model_dir), "promotion_status": "pending_review"}),
                encoding="utf-8",
            )
            self.assertIsNone(main_run_kronos_predict._auto_finetuned_model_dir(output_dir))

            status_path.write_text(
                json.dumps({"active_model_path": str(model_dir), "promotion_status": "rejected"}),
                encoding="utf-8",
            )
            self.assertIsNone(main_run_kronos_predict._auto_finetuned_model_dir(output_dir))

            status_path.write_text(
                json.dumps({"active_model_path": str(model_dir), "promotion_status": "approved"}),
                encoding="utf-8",
            )
            self.assertIsNone(main_run_kronos_predict._auto_finetuned_model_dir(output_dir))

    def test_approved_ready_model_is_selected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            model_dir = output_dir / "candidate_model"
            model_dir.mkdir(parents=True, exist_ok=True)

            (model_dir / "config.json").write_text("{}", encoding="utf-8")
            (model_dir / "model.safetensors").write_text("stub", encoding="utf-8")
            (output_dir / "auto_finetune_status.json").write_text(
                json.dumps({"active_model_path": str(model_dir), "promotion_status": "approved"}),
                encoding="utf-8",
            )

            selected = main_run_kronos_predict._auto_finetuned_model_dir(output_dir)
            self.assertEqual(model_dir, selected)


if __name__ == "__main__":
    unittest.main()