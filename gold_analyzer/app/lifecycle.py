from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from gold_analyzer.config import ModelsConfig, load_models_config
from gold_analyzer.data.candles import load_recent_candles
from gold_analyzer.forecasting.ensemble import EnsembleBuilder
from gold_analyzer.forecasting.pipeline import ForecastingPipeline
from gold_analyzer.models.base import ForecastModel
from gold_analyzer.models.foundation import Chronos2Adapter, KronosAdapter, MoiraiAdapter, TimesFMAdapter
from gold_analyzer.models.local.placeholders import ITransformerAdapter, PatchTSTAdapter
from gold_analyzer.models.volatility import GarchAdapter


def load_default_models(models_config: ModelsConfig | None = None) -> list[ForecastModel]:
    config = models_config or load_models_config()
    if not config.enabled:
        return []

    models_root = config.raw.get("models") if isinstance(config.raw, dict) else {}
    if not isinstance(models_root, dict):
        models_root = {}

    loaded: list[ForecastModel] = []

    foundation = models_root.get("foundation") if isinstance(models_root.get("foundation"), dict) else {}
    kronos_cfg = foundation.get("kronos") if isinstance(foundation.get("kronos"), dict) else {}
    if bool(kronos_cfg.get("enabled", False)):
        loaded.append(
            KronosAdapter(
                model_path=_resolve_project_path(kronos_cfg.get("model_path")),
                tokenizer_path=_resolve_project_path(kronos_cfg.get("tokenizer_path")),
                device=str(kronos_cfg.get("device", "auto")),
            )
        )
    chronos_cfg = foundation.get("chronos2") if isinstance(foundation.get("chronos2"), dict) else {}
    if bool(chronos_cfg.get("enabled", False)):
        loaded.append(
            Chronos2Adapter(
                model_path=_resolve_project_path(chronos_cfg.get("model_path")),
                device=str(chronos_cfg.get("device", "auto")),
            )
        )
    timesfm_cfg = foundation.get("timesfm") if isinstance(foundation.get("timesfm"), dict) else {}
    if bool(timesfm_cfg.get("enabled", False)):
        loaded.append(
            TimesFMAdapter(
                model_path=_resolve_project_path(timesfm_cfg.get("model_path")),
                device=str(timesfm_cfg.get("device", "auto")),
            )
        )
    moirai_cfg = foundation.get("moirai") if isinstance(foundation.get("moirai"), dict) else {}
    if bool(moirai_cfg.get("enabled", False)):
        loaded.append(
            MoiraiAdapter(
                model_path=_resolve_project_path(moirai_cfg.get("model_path")),
                device=str(moirai_cfg.get("device", "auto")),
            )
        )

    volatility = models_root.get("volatility") if isinstance(models_root.get("volatility"), dict) else {}
    garch_cfg = volatility.get("garch") if isinstance(volatility.get("garch"), dict) else {}
    if bool(garch_cfg.get("enabled", False)):
        loaded.append(GarchAdapter(window_bars=int(garch_cfg.get("window_bars", 1000))))

    local = models_root.get("local") if isinstance(models_root.get("local"), dict) else {}
    patchtst_cfg = local.get("patchtst") if isinstance(local.get("patchtst"), dict) else {}
    if bool(patchtst_cfg.get("enabled", False)):
        loaded.append(PatchTSTAdapter(artifact_path=_resolve_project_path(patchtst_cfg.get("artifact_path"))))
    itransformer_cfg = local.get("itransformer") if isinstance(local.get("itransformer"), dict) else {}
    if bool(itransformer_cfg.get("enabled", False)):
        loaded.append(ITransformerAdapter(artifact_path=_resolve_project_path(itransformer_cfg.get("artifact_path"))))

    return loaded


def create_pipeline(
    *,
    dsn: str | None = None,
    models: Iterable[ForecastModel] | None = None,
    models_config: ModelsConfig | None = None,
    persist: bool = False,
) -> ForecastingPipeline:
    config = models_config or load_models_config()
    selected_models = list(models) if models is not None else load_default_models(config)
    forecast_repository = regime_repository = signal_score_repository = None
    if persist:
        from gold_analyzer.db.repositories import ForecastRepository, SignalScoreRepository, ValidationRepository

        forecast_repository = ForecastRepository(dsn=dsn)
        regime_repository = ValidationRepository(dsn=dsn)
        signal_score_repository = SignalScoreRepository(dsn=dsn)
    return ForecastingPipeline(
        data_loader=lambda epic, timeframe, limit: load_recent_candles(epic=epic, timeframe=timeframe, limit=limit, dsn=dsn),
        models=selected_models,
        model_registry=ConfiguredModelRegistry(models=selected_models, schedule=config.section("schedule")),
        ensemble_builder=EnsembleBuilder(weights=_weights(config.ensemble_config)),
        forecast_repository=forecast_repository,
        regime_repository=regime_repository,
        signal_score_repository=signal_score_repository,
    )


class ConfiguredModelRegistry:
    def __init__(self, *, models: Iterable[ForecastModel], schedule: dict[str, Any]) -> None:
        self._models_by_key = {str(model.model_key).lower(): model for model in models}
        self._schedule = schedule if isinstance(schedule, dict) else {}

    def enabled_models(self, *, timeframe: str) -> list[ForecastModel]:
        schedule = _schedule_entry(self._schedule, timeframe)
        if not schedule:
            return list(self._models_by_key.values())
        if not bool(schedule.get("run_models", True)):
            return []
        configured_keys = schedule.get("models")
        if not isinstance(configured_keys, list):
            return list(self._models_by_key.values())
        selected: list[ForecastModel] = []
        for key in configured_keys:
            model = self._models_by_key.get(str(key).lower())
            if model is not None:
                selected.append(model)
        return selected


def _schedule_entry(schedule: dict[str, Any], timeframe: str) -> dict[str, Any]:
    normalized = str(timeframe or "").upper()
    for key, value in schedule.items():
        if not isinstance(value, dict):
            continue
        if str(value.get("resolution", "")).upper() == normalized:
            return value
    aliases = {
        "MINUTE": "1m",
        "MINUTE_5": "5m",
        "MINUTE_15": "15m",
        "MINUTE_30": "30m",
        "HOUR": "1h",
        "HOUR_4": "4h",
        "DAY": "1d",
    }
    alias = aliases.get(normalized)
    value = schedule.get(alias) if alias else None
    return value if isinstance(value, dict) else {}


def _weights(config: dict[str, Any]) -> dict[str, float]:
    raw = config.get("weights") if isinstance(config, dict) else {}
    if not isinstance(raw, dict):
        return {}
    weights: dict[str, float] = {}
    for key, value in raw.items():
        try:
            weights[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return weights


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_project_path(value: str | Path | None) -> Path | str | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value).strip())
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    project_candidate = _project_root() / path
    if project_candidate.exists():
        return project_candidate
    if str(value).startswith(".") or "\\" in str(value):
        return project_candidate
    return str(value)
