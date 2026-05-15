from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any

from gold_analyzer.models.base import ForecastModel, ForecastRequest, ForecastResult


class _LocalArtifactAdapter(ForecastModel):
    model_key: str
    display_name: str

    def __init__(
        self,
        *,
        model_key: str,
        display_name: str,
        artifact_path: str | Path | None,
        model_version: str,
    ) -> None:
        self.model_key = model_key
        self.display_name = display_name
        self.artifact_path = Path(artifact_path) if artifact_path else None
        self.model_version = model_version

    def predict(self, request: ForecastRequest) -> ForecastResult:
        started = time.perf_counter()
        raw: dict[str, Any] = {"artifact_path": str(self.artifact_path) if self.artifact_path else None}
        if self.artifact_path is None:
            return self._skip(request, started, f"{self.display_name} artifact_path is not configured.", raw)
        if not self.artifact_path.exists():
            return self._skip(request, started, f"{self.display_name} artifact_path does not exist: {self.artifact_path}", raw)
        if not _module_available("torch"):
            return self._skip(request, started, f"{self.display_name} optional dependency missing: torch.", raw)
        return self._skip(
            request,
            started,
            f"{self.display_name} artifact is present, but this repository has no supported live inference entry point for it yet.",
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


class PatchTSTAdapter(_LocalArtifactAdapter):
    def __init__(
        self,
        *,
        artifact_path: str | Path | None = None,
        model_version: str = "patchtst-not-ready",
    ) -> None:
        super().__init__(
            model_key="patchtst",
            display_name="PatchTST",
            artifact_path=artifact_path,
            model_version=model_version,
        )


class ITransformerAdapter(_LocalArtifactAdapter):
    def __init__(
        self,
        *,
        artifact_path: str | Path | None = None,
        model_version: str = "itransformer-not-ready",
    ) -> None:
        super().__init__(
            model_key="itransformer",
            display_name="iTransformer",
            artifact_path=artifact_path,
            model_version=model_version,
        )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False
