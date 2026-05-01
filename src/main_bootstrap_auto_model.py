from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pandas as pd


REQUIRED_MODEL_FILES = ("config.json", "model.safetensors")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap the auto-finetuned Kronos model directory from an installed "
            "base model. This gives the dashboard a valid model artifact target; "
            "a heavier fine-tune command can replace these artifacts later."
        )
    )
    parser.add_argument("--dataset", required=True, help="Training dataset CSV exported by the auto-finetune worker.")
    parser.add_argument("--model-dir", required=True, help="Destination auto model directory.")
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--resolution", default=os.getenv("AUTO_FINETUNE_RESOLUTION", "MINUTE_5"))
    parser.add_argument("--base-model-dir", default=os.getenv("KRONOS_MODEL_DIR", r"C:\AI\Models\Kronos\Kronos-base"))
    return parser.parse_args()


def _copy_if_needed(source: Path, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_suffix(destination.suffix + ".tmp")
    if temp_destination.exists():
        temp_destination.unlink()
    shutil.copy2(source, temp_destination)
    temp_destination.replace(destination)


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    model_dir = Path(args.model_dir)
    base_model_dir = Path(args.base_model_dir)

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset does not exist: {dataset_path}")
    if not base_model_dir.is_dir():
        raise FileNotFoundError(f"Base model directory does not exist: {base_model_dir}")

    missing = [name for name in REQUIRED_MODEL_FILES if not (base_model_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Base model is missing required file(s): {', '.join(missing)}")

    df = pd.read_csv(dataset_path, usecols=["timestamps"])
    if df.empty:
        raise ValueError(f"Dataset has no rows: {dataset_path}")

    model_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_MODEL_FILES:
        _copy_if_needed(base_model_dir / name, model_dir / name)

    manifest = {
        "bootstrap_source": str(base_model_dir),
        "dataset": str(dataset_path),
        "dataset_rows": int(len(df)),
        "dataset_start_utc": str(df["timestamps"].iloc[0]),
        "dataset_end_utc": str(df["timestamps"].iloc[-1]),
        "symbol": args.symbol,
        "resolution": args.resolution,
        "note": "Bootstrapped from Kronos-base so auto-model promotion can evaluate real live metrics.",
    }
    (model_dir / "auto_model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Bootstrapped auto model at {model_dir}")
    print(f"Dataset rows: {len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
