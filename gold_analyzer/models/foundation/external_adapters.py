from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

from gold_analyzer.models.base import ForecastModel, ForecastRequest, ForecastResult


class ExternalFoundationAdapter(ForecastModel):
    """Readiness adapter for optional foundation forecasting models.

    These models are intentionally optional: the repository can record that an
    adapter is configured, missing artifacts, missing Python packages, or not
    supported by the local runtime without breaking the live Kronos path.
    """

    model_key: str

    def __init__(
        self,
        *,
        model_key: str,
        display_name: str,
        model_path: str | Path | None,
        required_modules: tuple[str, ...],
        model_version: str | None = None,
        device: str = "auto",
    ) -> None:
        self.model_key = model_key
        self.display_name = display_name
        self.model_path = Path(model_path) if model_path else None
        self.required_modules = required_modules
        self.model_version = model_version or f"{model_key}-not-ready"
        self.device = device

    def predict(self, request: ForecastRequest) -> ForecastResult:
        started = time.perf_counter()
        raw: dict[str, Any] = {
            "device": self.device,
            "model_path": str(self.model_path) if self.model_path else None,
            "required_modules": list(self.required_modules),
        }
        if self.model_path is None:
            return self._skip(request, started, f"{self.display_name} model_path is not configured.", raw)
        if _looks_like_local_path(self.model_path) and not self.model_path.exists():
            return self._skip(request, started, f"{self.display_name} model_path does not exist: {self.model_path}", raw)
        missing_modules = [name for name in self.required_modules if not _module_available(name)]
        if missing_modules:
            return self._skip(
                request,
                started,
                f"{self.display_name} optional dependency missing: {', '.join(missing_modules)}.",
                raw,
            )
        return self._skip(
            request,
            started,
            f"{self.display_name} runtime package is present, but this repository has no supported live inference adapter for it yet.",
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


class Chronos2Adapter(ExternalFoundationAdapter):
    def __init__(self, *, model_path: str | Path | None, model_version: str | None = None, device: str = "auto") -> None:
        super().__init__(
            model_key="chronos2",
            display_name="Chronos-2",
            model_path=model_path,
            required_modules=("transformers",),
            model_version=model_version,
            device=device,
        )


class TimesFMAdapter(ExternalFoundationAdapter):
    def __init__(self, *, model_path: str | Path | None, model_version: str | None = None, device: str = "auto") -> None:
        super().__init__(
            model_key="timesfm",
            display_name="TimesFM",
            model_path=model_path,
            required_modules=("timesfm",),
            model_version=model_version,
            device=device,
        )


class MoiraiAdapter(ExternalFoundationAdapter):
    def __init__(self, *, model_path: str | Path | None, model_version: str | None = None, device: str = "auto") -> None:
        super().__init__(
            model_key="moirai",
            display_name="Moirai",
            model_path=model_path,
            required_modules=("uni2ts",),
            model_version=model_version,
            device=device,
        )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _looks_like_local_path(path: Path) -> bool:
    text = str(path)
    return path.is_absolute() or text.startswith(".") or "\\" in text or path.drive != ""
