"""
Verify a local Kronos-base installation on Windows.

This script loads Kronos and Kronos-Tokenizer from local disk only. It does not
connect to broker APIs, place orders, or perform live trading.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


REPO_DIR = Path(r"C:\AI\Kronos")
MODEL_DIR = Path(r"C:\AI\Models\Kronos\Kronos-base")
TOKENIZER_DIR = Path(r"C:\AI\Models\Kronos\Kronos-Tokenizer-base")


def fail(message: str, exc: BaseException | None = None) -> int:
    print(f"[FAIL] {message}")
    if exc is not None:
        print(f"[FAIL] Root cause: {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
    return 1


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")
    for required_file in ("config.json", "model.safetensors"):
        candidate = path / required_file
        if not candidate.exists():
            raise FileNotFoundError(f"{label} is missing {required_file}: {candidate}")


def run_smoke_test(predictor) -> None:
    import numpy as np
    import pandas as pd

    lookback = 32
    pred_len = 2
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.2, lookback))
    open_ = close + rng.normal(0, 0.05, lookback)
    high = np.maximum(open_, close) + 0.1
    low = np.minimum(open_, close) - 0.1
    volume = rng.integers(1000, 3000, lookback).astype(float)
    amount = volume * close

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
    )
    x_timestamp = pd.Series(pd.date_range("2026-01-01 09:30:00", periods=lookback, freq="5min"))
    y_timestamp = pd.Series(pd.date_range(x_timestamp.iloc[-1] + pd.Timedelta(minutes=5), periods=pred_len, freq="5min"))

    pred_df = predictor.predict(
        df=df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=1,
        verbose=False,
    )
    print("[OK] Synthetic OHLCV forecast smoke test completed.")
    print(f"[OK] Smoke test output shape: {pred_df.shape}")
    print(pred_df.head().to_string())


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Kronos-base installation.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a tiny synthetic OHLCV forecast after loading the model.",
    )
    args = parser.parse_args()

    try:
        if str(REPO_DIR) not in sys.path:
            sys.path.insert(0, str(REPO_DIR))

        require_path(MODEL_DIR, "Kronos-base")
        require_path(TOKENIZER_DIR, "Kronos-Tokenizer-base")
        print(f"[OK] Found local model folder: {MODEL_DIR}")
        print(f"[OK] Found local tokenizer folder: {TOKENIZER_DIR}")

        import torch
        from model import Kronos, KronosPredictor, KronosTokenizer

        print(f"[OK] Imported Kronos classes from local repo: {REPO_DIR}")
        print(f"[OK] torch version: {torch.__version__}")
        print(f"[OK] torch CUDA build: {torch.version.cuda}")

        cuda_available = torch.cuda.is_available()
        device = "cuda:0" if cuda_available else "cpu"
        print(f"[OK] CUDA available: {cuda_available}")
        if cuda_available:
            print(f"[OK] CUDA device 0: {torch.cuda.get_device_name(0)}")
        print(f"[OK] Selected device: {device}")

        tokenizer = KronosTokenizer.from_pretrained(str(TOKENIZER_DIR))
        print("[OK] Loaded KronosTokenizer from local disk.")

        model = Kronos.from_pretrained(str(MODEL_DIR))
        print("[OK] Loaded Kronos-base from local disk.")

        predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
        print("[OK] Instantiated KronosPredictor with max_context=512.")

        if args.smoke_test:
            run_smoke_test(predictor)
        else:
            print("[OK] Smoke test skipped. Use --smoke-test to run a tiny synthetic forecast.")

        print("[SUCCESS] Local Kronos verification completed. No trading actions were performed.")
        return 0
    except Exception as exc:
        return fail("Local Kronos verification failed.", exc)


if __name__ == "__main__":
    raise SystemExit(main())
