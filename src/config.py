from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from rich.logging import RichHandler

load_dotenv()

LIVE_BASE_URL = "https://api-capital.backend-capital.com/api/v1"
DEMO_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"
WS_URL = "wss://api-streaming-capital.backend-capital.com/connect"

SUPPORTED_RESOLUTIONS = {
    "MINUTE",
    "MINUTE_5",
    "MINUTE_15",
    "MINUTE_30",
    "HOUR",
    "HOUR_4",
    "DAY",
    "WEEK",
}
SUPPORTED_PRICE_SIDES = {"bid", "ask", "mid"}
TRADING_ENDPOINT_HINTS = (
    "/positions",
    "/workingorders",
    "/orders",
    "/confirms",
)


class ConfigError(RuntimeError):
    """Raised when runtime configuration is invalid."""


class BridgeSettings(BaseModel):
    env: Literal["demo", "live"] = "demo"
    api_key: str = Field(default="", repr=False)
    identifier: str = Field(default="", repr=False)
    password: str = Field(default="", repr=False)
    use_encrypted_password: bool = False
    default_market_search: str = "ETHUSD"
    default_epic: str = "ETHUSD"
    default_resolution: str = "MINUTE_5"
    default_price_side: Literal["bid", "ask", "mid"] = "mid"
    output_dir: Path = Path("output")

    @field_validator("default_resolution")
    @classmethod
    def validate_default_resolution(cls, value: str) -> str:
        value = value.upper()
        if value not in SUPPORTED_RESOLUTIONS:
            raise ValueError(f"Unsupported resolution: {value}")
        return value

    @property
    def base_url(self) -> str:
        return DEMO_BASE_URL if self.env == "demo" else LIVE_BASE_URL

    def ensure_credentials(self) -> None:
        missing = [
            name
            for name, value in {
                "CAPITAL_API_KEY": self.api_key,
                "CAPITAL_IDENTIFIER": self.identifier,
                "CAPITAL_PASSWORD": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")


class RateLimiter:
    """Small thread-safe limiter for Capital.com's per-second REST limits."""

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._lock = Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self.min_interval_seconds - (now - self._last_call)
            if delay > 0:
                time.sleep(delay)
            self._last_call = time.monotonic()


def load_settings(env_override: str | None = None) -> BridgeSettings:
    env = env_override or os.getenv("CAPITAL_ENV", "demo")
    return BridgeSettings(
        env=env.lower(),
        api_key=os.getenv("CAPITAL_API_KEY", ""),
        identifier=os.getenv("CAPITAL_IDENTIFIER", ""),
        password=os.getenv("CAPITAL_PASSWORD", ""),
        use_encrypted_password=os.getenv("CAPITAL_USE_ENCRYPTED_PASSWORD", "false").lower()
        in {"1", "true", "yes"},
        default_market_search=os.getenv("CAPITAL_DEFAULT_MARKET_SEARCH", "ETHUSD"),
        default_epic=os.getenv("CAPITAL_DEFAULT_EPIC", ""),
        default_resolution=os.getenv("CAPITAL_DEFAULT_RESOLUTION", "MINUTE_5"),
        default_price_side=os.getenv("CAPITAL_DEFAULT_PRICE_SIDE", "mid").lower(),
        output_dir=Path(os.getenv("CAPITAL_OUTPUT_DIR", "output")),
    )


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(markup=True, rich_tracebacks=True, show_path=False)],
    )


def validate_resolution(resolution: str) -> str:
    value = resolution.upper()
    if value not in SUPPORTED_RESOLUTIONS:
        raise ConfigError(
            f"Invalid resolution {resolution!r}. Supported: {', '.join(sorted(SUPPORTED_RESOLUTIONS))}"
        )
    return value


def validate_price_side(price_side: str) -> str:
    value = price_side.lower()
    if value not in SUPPORTED_PRICE_SIDES:
        raise ConfigError(
            f"Invalid price side {price_side!r}. Supported: {', '.join(sorted(SUPPORTED_PRICE_SIDES))}"
        )
    return value


def safe_epic_for_filename(epic: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in epic)


def assert_data_only_path(path: str) -> None:
    lower = path.lower()
    if any(hint in lower for hint in TRADING_ENDPOINT_HINTS):
        raise ConfigError(f"Refusing to call trading endpoint from data-only bridge: {path}")
