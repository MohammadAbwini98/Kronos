from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a configured Kronos fine-tuning command on exported OHLCV data.")
    parser.add_argument("--dataset", required=True, help="CSV produced by main_prepare_finetune_dataset.py.")
    parser.add_argument("--command", default=None, help="Explicit fine-tuning command. Use {dataset} as a placeholder.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without running it.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = Path(args.dataset)
    if not dataset.exists():
        raise FileNotFoundError(dataset)
    if not args.command:
        print("Dataset is ready for Kronos fine-tuning experiments.")
        print("No command was supplied, so no model training was started.")
        print("Pass --command \"<your Kronos training command> --data {dataset}\" when your local training script is configured.")
        return
    command = args.command.format(dataset=str(dataset))
    print(command)
    if args.dry_run:
        return
    result = subprocess.run(command, shell=True, text=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
