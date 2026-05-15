from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ModelConfigError, _env_flag, _resolve_config_path


class StrategyBrainConfigError(ModelConfigError):
    """Raised when Strategy Brain YAML configuration cannot be loaded safely."""


_DEFAULT_STRATEGY_BRAIN_CONFIG: dict[str, Any] = {
    "enabled": False,
    "symbol": "GOLD",
    "main_timeframe": "5m",
    "timeframes": {
        "execution": "5m",
        "higher_timeframes": ["15m", "30m", "1h"],
    },
    "indicators": {
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 200,
        "atr_period": 14,
        "rsi_period": 14,
        "adx_period": 14,
        "bb_period": 20,
        "bb_std": 2.0,
        "donchian_period": 20,
        "swing_len": 2,
    },
    "regimes": {
        "persistence_k": 2,
        "persistence_m": 3,
        "trend_adx_min": 18,
        "range_adx_max": 18,
        "atr_extreme_percentile": 95,
    },
    "strategy_thresholds": {
        "trend_min_score": 75,
        "breakout_min_score": 85,
        "breakout_priority_score": 90,
        "mean_reversion_min_score": 75,
        "final_min_score": 75,
    },
    "risk": {
        "risk_per_trade": 0.005,
        "conservative_risk_per_trade": 0.0025,
        "max_risk_per_trade": 0.01,
        "max_daily_loss": 0.02,
        "max_consecutive_losses": 3,
        "loss_cooldown_minutes": 120,
        "signal_cooldown_minutes": 15,
        "max_open_positions_per_symbol": 1,
    },
    "spread_limits": {
        "max_spread_absolute": 3.0,
        "max_spread_atr": 0.15,
    },
    "hard_blocks": {
        "max_spread_absolute": 3.0,
        "max_spread_atr": 0.15,
        "min_expected_move_spread_mult": 2.0,
        "block_garch_extreme": True,
        "require_regime_persistence": True,
    },
    "ai_support": {
        "enabled": True,
        "ai_cannot_generate_signal": True,
        "missing_model_support_value": 0.0,
        "weights": {
            "kronos": 35.0,
            "chronos2": 15.0,
            "timesfm": 15.0,
            "local_models": 15.0,
            "moirai": 10.0,
            "garch": 10.0,
        },
    },
    "dashboard": {
        "enabled": True,
        "history_limit_default": 50,
    },
}


@dataclass(frozen=True)
class StrategyBrainConfig:
    enabled: bool = False
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def strategy_brain(self) -> dict[str, Any]:
        return dict(self.raw.get("strategy_brain") or {})

    @property
    def symbol(self) -> str:
        return str(self.strategy_brain.get("symbol") or "GOLD")

    @property
    def main_timeframe(self) -> str:
        timeframes = self.timeframes
        return str(
            self.strategy_brain.get("main_timeframe")
            or timeframes.get("execution")
            or "5m"
        )

    @property
    def timeframes(self) -> dict[str, Any]:
        return dict(self.strategy_brain.get("timeframes") or {})

    def section(self, name: str) -> dict[str, Any]:
        strategy_brain = self.strategy_brain
        if name == "strategy_thresholds":
            return dict(strategy_brain.get(name) or strategy_brain.get("scoring") or {})
        return dict(strategy_brain.get(name) or {})


def load_strategy_brain_config(path: str | Path | None = None) -> StrategyBrainConfig:
    configured_path = path or os.getenv("STRATEGY_BRAIN_CONFIG", "configs/strategy_brain.example.yaml")
    source = _resolve_config_path(configured_path)

    raw: dict[str, Any] = {}
    if source.exists():
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only when dependency is absent
            raise StrategyBrainConfigError("PyYAML is required to read Strategy Brain YAML config") from exc
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise StrategyBrainConfigError(f"Strategy Brain config must be a mapping: {source}")
        raw = loaded

    section = raw.get("strategy_brain") or {}
    if section and not isinstance(section, dict):
        raise StrategyBrainConfigError(f"strategy_brain section must be a mapping: {source}")

    merged_section = _deep_merge(copy.deepcopy(_DEFAULT_STRATEGY_BRAIN_CONFIG), dict(section))
    if "strategy_thresholds" not in section and isinstance(section.get("scoring"), dict):
        merged_section["strategy_thresholds"] = _deep_merge(
            copy.deepcopy(_DEFAULT_STRATEGY_BRAIN_CONFIG["strategy_thresholds"]),
            dict(section.get("scoring") or {}),
        )

    enabled = _env_flag("STRATEGY_BRAIN_ENABLED", bool(merged_section.get("enabled", False)))
    merged_section["enabled"] = enabled
    merged_raw = dict(raw)
    merged_raw["strategy_brain"] = merged_section
    return StrategyBrainConfig(enabled=enabled, path=source, raw=merged_raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(dict(merged[key]), dict(value))
        else:
            merged[key] = value
    return merged


__all__ = ["StrategyBrainConfig", "StrategyBrainConfigError", "load_strategy_brain_config"]