from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config
import db


def test_load_settings_accepts_capital_email_alias(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_IDENTIFIER", raising=False)
    monkeypatch.setenv("CAPITAL_EMAIL", "user@example.test")

    settings = config.load_settings("demo")

    assert settings.identifier == "user@example.test"


def test_trade_execution_settings_accepts_capital_email_alias(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_IDENTIFIER", raising=False)
    monkeypatch.setenv("CAPITAL_EMAIL", "trader@example.test")

    settings = config.load_trade_execution_settings()

    assert settings.identifier == "trader@example.test"


def test_postgres_dsn_can_be_built_from_db_component_env(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "")
    monkeypatch.setenv("DB_HOST", "db.local")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "goldbot")
    monkeypatch.setenv("DB_USER", "gold_user")
    monkeypatch.setenv("DB_PASSWORD", "gold pass")

    with patch.object(db, "load_dotenv_if_present", return_value=None):
        dsn = db.postgres_dsn()

    assert dsn == "postgresql://gold_user:gold%20pass@db.local:5433/goldbot"


def test_env_example_contains_phase0_secret_placeholders_only() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    for required in [
        "CAPITAL_API_KEY=",
        "CAPITAL_EMAIL=",
        "CAPITAL_PASSWORD=",
        "CAPITAL_ACCOUNT_ID=",
        "DB_HOST=localhost",
        "DB_PORT=5432",
        "DB_NAME=goldbot",
        "DB_USER=",
        "DB_PASSWORD=",
        "TELEGRAM_BOT_TOKEN=",
        "TELEGRAM_CHAT_ID=",
    ]:
        assert required in text
    assert "capital_kronos:capital_kronos" not in text
    assert "postgresql://USER:PASSWORD" not in text
