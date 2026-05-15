from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ModelConfigError(RuntimeError):
    """Raised when optional model configuration cannot be loaded."""


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_config_path(configured_path: str | Path) -> Path:
    source = Path(configured_path)
    if source.is_absolute():
        return source
    cwd_candidate = Path.cwd() / source
    if cwd_candidate.exists():
        return cwd_candidate
    project_candidate = _project_root() / source
    if project_candidate.exists():
        return project_candidate
    parent_candidate = _project_root().parent / source
    if parent_candidate.exists():
        return parent_candidate
    return project_candidate


@dataclass(frozen=True)
class ModelsConfig:
    enabled: bool = False
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def global_config(self) -> dict[str, Any]:
        return dict((self.raw.get("models") or {}).get("global") or {})

    @property
    def ensemble_config(self) -> dict[str, Any]:
        return dict((self.raw.get("models") or {}).get("ensemble") or {})

    @property
    def scorer_config(self) -> dict[str, Any]:
        return dict((self.raw.get("models") or {}).get("scorer") or {})

    @property
    def final_decision_config(self) -> dict[str, Any]:
        return dict((self.raw.get("models") or {}).get("final_decision") or {})

    def section(self, name: str) -> dict[str, Any]:
        return dict((self.raw.get("models") or {}).get(name) or {})


def load_models_config(path: str | Path | None = None) -> ModelsConfig:
    """Load optional AI model config from YAML.

    Missing files are treated as disabled defaults so the current strategy can
    run unchanged on fresh installs.
    """

    configured_path = path or os.getenv("AI_MODELS_CONFIG", "configs/models.example.yaml")
    source = _resolve_config_path(configured_path)

    raw: dict[str, Any] = {}
    if source.exists():
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised when dependency is absent
            raise ModelConfigError("PyYAML is required to read AI model YAML config") from exc
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ModelConfigError(f"Model config must be a mapping: {source}")
        raw = loaded

    models_root = raw.get("models") or {}
    file_enabled = bool(models_root.get("enabled", False)) if isinstance(models_root, dict) else False
    enabled = _env_flag("AI_MODELS_ENABLED", file_enabled)
    return ModelsConfig(enabled=enabled, path=source, raw=raw)
