from __future__ import annotations

import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_kronos_auto_finetune


def _write_dataset(path: Path, rows: int = 80) -> None:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamps": timestamps,
            "open": [100.0 + i * 0.1 for i in range(rows)],
            "high": [100.5 + i * 0.1 for i in range(rows)],
            "low": [99.5 + i * 0.1 for i in range(rows)],
            "close": [100.2 + i * 0.1 for i in range(rows)],
            "volume": [1.0 for _ in range(rows)],
            "amount": [0.0 for _ in range(rows)],
        }
    )
    df.to_csv(path, index=False)


def _write_model_artifacts(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_text("stub", encoding="utf-8")


class KronosAutoFinetuneEntrypointTests(unittest.TestCase):
    def test_dataset_validation_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset = Path(temp_dir) / "bad.csv"
            pd.DataFrame({"timestamps": ["2026-01-01T00:00:00Z"], "open": [1]}).to_csv(dataset, index=False)

            with self.assertRaises(main_kronos_auto_finetune.AutoFinetuneError):
                main_kronos_auto_finetune._validate_dataset(dataset, lookback=10, pred_len=2, val_ratio=0.3)

    def test_dry_run_writes_basemodel_only_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = root / "dataset.csv"
            model_dir = root / "candidate"
            pretrained_model = root / "base"
            pretrained_tokenizer = root / "tokenizer"
            work_dir = root / "work"
            _write_dataset(dataset)
            _write_model_artifacts(pretrained_model)
            _write_model_artifacts(pretrained_tokenizer)
            argv = [
                "main_kronos_auto_finetune.py",
                "--dataset",
                str(dataset),
                "--model-dir",
                str(model_dir),
                "--repo-dir",
                str(root / "KRONOS-MODEL"),
                "--pretrained-model-dir",
                str(pretrained_model),
                "--pretrained-tokenizer-dir",
                str(pretrained_tokenizer),
                "--work-dir",
                str(work_dir),
                "--lookback",
                "10",
                "--pred-len",
                "2",
                "--epochs",
                "1",
                "--batch-size",
                "4",
                "--device",
                "cpu",
                "--dry-run",
            ]

            with patch.object(sys, "argv", argv):
                main_kronos_auto_finetune.main()

            config = (work_dir / "auto_finetune_config.yaml").read_text(encoding="utf-8")
            self.assertIn("train_tokenizer: false", config)
            self.assertIn("train_basemodel: true", config)
            self.assertIn(str(dataset), config)
            self.assertIn(str(pretrained_tokenizer), config)

    def test_successful_training_copies_best_model_to_worker_model_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = root / "dataset.csv"
            model_dir = root / "candidate"
            repo_dir = root / "KRONOS-MODEL"
            pretrained_model = root / "base"
            pretrained_tokenizer = root / "tokenizer"
            work_dir = root / "work"
            _write_dataset(dataset)
            _write_model_artifacts(pretrained_model)
            _write_model_artifacts(pretrained_tokenizer)

            def fake_training(*, repo_dir, config_path, timeout_minutes):
                best_model = config_path.parent / "training" / "basemodel" / "best_model"
                _write_model_artifacts(best_model)
                return subprocess.CompletedProcess(["train"], 0, "ok", "")

            argv = [
                "main_kronos_auto_finetune.py",
                "--dataset",
                str(dataset),
                "--model-dir",
                str(model_dir),
                "--repo-dir",
                str(repo_dir),
                "--pretrained-model-dir",
                str(pretrained_model),
                "--pretrained-tokenizer-dir",
                str(pretrained_tokenizer),
                "--work-dir",
                str(work_dir),
                "--lookback",
                "10",
                "--pred-len",
                "2",
                "--epochs",
                "1",
                "--batch-size",
                "4",
                "--device",
                "cpu",
            ]
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(sys, "argv", argv))
                stack.enter_context(patch.object(main_kronos_auto_finetune, "_run_training", side_effect=fake_training))
                main_kronos_auto_finetune.main()

            self.assertTrue((model_dir / "config.json").exists())
            self.assertTrue((model_dir / "model.safetensors").exists())
            manifest = json.loads((model_dir / "auto_finetune_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["ok"])


if __name__ == "__main__":
    unittest.main()
