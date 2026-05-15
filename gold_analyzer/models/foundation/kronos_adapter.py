from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

import pandas as pd

from gold_analyzer.models.base import ForecastModel, ForecastRequest, ForecastResult


class KronosAdapter(ForecastModel):
    model_key = "kronos"

    def __init__(
        self,
        *,
        model_path: str | Path | None,
        tokenizer_path: str | Path | None = None,
        model_version: str = "kronos-placeholder-v1",
        device: str = "auto",
    ) -> None:
        self.model_path = Path(model_path) if model_path else None
        self.tokenizer_path = Path(tokenizer_path) if tokenizer_path else None
        self.model_version = model_version
        self.device = device

    def predict(self, request: ForecastRequest) -> ForecastResult:
        started = time.perf_counter()
        prepared = self._prepare_ohlcv(request.candles)
        raw: dict[str, Any] = {
            "device": self.device,
            "input_rows": int(len(prepared)),
            "columns": list(prepared.columns),
            "model_path": str(self.model_path) if self.model_path else None,
            "tokenizer_path": str(self.tokenizer_path) if self.tokenizer_path else None,
        }
        if self.model_path is None:
            return self._skip(request, started, "Kronos model_path is not configured.", raw)
        if not self.model_path.exists():
            return self._skip(request, started, f"Kronos model_path does not exist: {self.model_path}", raw)
        missing = [name for name in ("config.json", "model.safetensors") if not (self.model_path / name).exists()]
        if missing:
            return self._skip(request, started, f"Kronos model files missing: {', '.join(missing)}", raw)
        if not _module_available("model.kronos") and not _module_available("kronos"):
            return self._skip(request, started, "Kronos Python package is not importable in this environment.", raw)
        return self._skip(
            request,
            started,
            "Kronos adapter scaffold is ready, but heavy inference is intentionally not enabled yet.",
            raw,
        )

    def _skip(
        self,
        request: ForecastRequest,
        started: float,
        reason: str,
        raw: dict[str, Any],
    ) -> ForecastResult:
        return ForecastResult.skipped(
            model_key=self.model_key,
            model_version=self.model_version,
            epic=request.epic,
            timeframe=request.timeframe,
            reason=reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw=raw,
        )

    @staticmethod
    def _prepare_ohlcv(candles: pd.DataFrame) -> pd.DataFrame:
        required = ["timestamps", "open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in candles.columns]
        if missing:
            raise ValueError(f"Kronos input missing columns: {', '.join(missing)}")
        frame = candles[required].copy()
        frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True)
        for column in required[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[required[1:]].isna().any().any():
            raise ValueError("Kronos OHLCV input contains null numeric values")
        return frame.sort_values("timestamps").reset_index(drop=True)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False
