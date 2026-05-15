from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

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


class PostgresDsnArgumentTests(unittest.TestCase):
    def test_postgres_dsn_is_not_converted_to_windows_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_csv = root / "input.csv"
            input_csv.write_text("timestamps,open,high,low,close,volume,amount\n", encoding="utf-8")
            dsn = "postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos"
            fake_df = pd.DataFrame({"timestamps": [pd.Timestamp("2026-01-01T00:00:00Z")], "close": [1.0]})

            argv = [
                "main_run_kronos_predict.py",
                "--input",
                str(input_csv),
                "--output-dir",
                str(root),
                "--postgres-dsn",
                dsn,
            ]
            with patch.object(sys, "argv", argv), patch.object(main_run_kronos_predict, "run_prediction", return_value=fake_df) as run_prediction:
                main_run_kronos_predict.main()

            self.assertEqual(dsn, run_prediction.call_args.kwargs["prediction_db"])


class MetadataSymbolTests(unittest.TestCase):
    def test_metadata_keeps_configured_symbol_separate_from_provider_epic(self):
        input_df = pd.DataFrame(
            {
                "timestamps": pd.date_range("2026-05-01T10:00:00Z", periods=2, freq="5min", tz="UTC"),
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1.0, 1.0],
                "amount": [0.0, 0.0],
            }
        )
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

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata.json"
            main_run_kronos_predict._write_metadata(
                path,
                symbol="XAUUSD",
                epic="GOLD",
                market_name="Gold",
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
            )

            metadata = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("XAUUSD", metadata["symbol"])
        self.assertEqual("GOLD", metadata["epic"])


if __name__ == "__main__":
    unittest.main()
