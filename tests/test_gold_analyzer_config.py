from __future__ import annotations

from gold_analyzer.config import load_models_config


def test_missing_models_config_defaults_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AI_MODELS_ENABLED", raising=False)

    config = load_models_config(tmp_path / "missing.yaml")

    assert config.enabled is False
    assert config.raw == {}


def test_env_can_enable_models_without_editing_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MODELS_ENABLED", "true")

    config = load_models_config(tmp_path / "missing.yaml")

    assert config.enabled is True


def test_models_example_config_matches_ai_stack_shape(monkeypatch) -> None:
    monkeypatch.delenv("AI_MODELS_ENABLED", raising=False)

    config = load_models_config("configs/models.example.yaml")
    models = config.raw["models"]

    assert config.enabled is False
    assert models["schedule"]["5m"]["models"] == ["kronos", "patchtst", "itransformer", "garch"]
    assert set(models["foundation"]) == {"kronos", "chronos2", "timesfm", "moirai"}
    assert set(models["local"]) == {"patchtst", "itransformer"}
    assert models["volatility"]["garch"]["risk_thresholds"]["extreme_percentile"] == 95
    assert models["ensemble"]["weights"]["kronos"] == 0.30
    assert models["scorer"]["primary"] == "lightgbm"
    assert models["final_decision"]["outputs"] == ["BUY", "SELL", "NO_TRADE"]
    assert config.final_decision_config["min_probability_win"] == 0.62
    assert models["global"]["default_batch_size"] == 8
