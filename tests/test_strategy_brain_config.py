from __future__ import annotations

from pathlib import Path

from gold_analyzer.config import load_strategy_brain_config


def test_strategy_brain_config_loader_returns_safe_defaults_for_missing_file(tmp_path: Path) -> None:
    config = load_strategy_brain_config(tmp_path / "missing-strategy-brain.yaml")

    assert config.enabled is False
    assert config.symbol == "GOLD"
    assert config.main_timeframe == "5m"
    assert config.timeframes["execution"] == "5m"
    assert config.section("risk")["signal_cooldown_minutes"] == 15
    assert config.section("spread_limits")["max_spread_atr"] == 0.15


def test_strategy_brain_config_loader_merges_partial_yaml_with_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "strategy_brain.yaml"
    config_path.write_text(
        """
strategy_brain:
  enabled: true
  symbol: SILVER
  risk:
    risk_per_trade: 0.0075
  dashboard:
    history_limit_default: 25
""".strip(),
        encoding="utf-8",
    )

    config = load_strategy_brain_config(config_path)

    assert config.enabled is True
    assert config.symbol == "SILVER"
    assert config.section("risk")["risk_per_trade"] == 0.0075
    assert config.section("risk")["loss_cooldown_minutes"] == 120
    assert config.section("dashboard")["history_limit_default"] == 25
    assert config.section("spread_limits")["max_spread_absolute"] == 3.0


def test_strategy_brain_example_config_contains_required_sections() -> None:
    config_text = Path("configs/strategy_brain.example.yaml").read_text(encoding="utf-8")

    for expected in (
        "timeframes:",
        "strategy_thresholds:",
        "spread_limits:",
        "signal_cooldown_minutes:",
        "weights:",
        "dashboard:",
    ):
        assert expected in config_text