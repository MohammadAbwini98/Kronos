from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Literal
import json

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


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True)


class _DailyLogFileHandler(logging.FileHandler):
    """Write to logs/log_DDMMYYYY.log and switch files when the day changes."""

    def __init__(self, log_dir: Path, encoding: str = "utf-8") -> None:
        self._log_dir = log_dir
        self._current_day = self._day_token()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(self._path_for_day(self._current_day), mode="a", encoding=encoding)

    @staticmethod
    def _day_token() -> str:
        return time.strftime("%d%m%Y")

    def _path_for_day(self, day_token: str) -> Path:
        return self._log_dir / f"log_{day_token}.log"

    def _rollover_if_needed(self) -> None:
        day_token = self._day_token()
        if day_token == self._current_day:
            return
        self.acquire()
        try:
            day_token = self._day_token()
            if day_token == self._current_day:
                return
            self._current_day = day_token
            self.baseFilename = os.fspath(self._path_for_day(day_token))
            if self.stream:
                self.stream.close()
                self.stream = None
            self.stream = self._open()
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        self._rollover_if_needed()
        super().emit(record)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_log_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        candidate = level.strip().upper()
    else:
        candidate = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return logging._nameToLevel.get(candidate, logging.INFO)


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


def configure_logging(level: int | str | None = None, service_name: str | None = None) -> None:
    resolved_level = _resolve_log_level(level)
    log_dir = Path(os.getenv("CAPITAL_LOG_DIR", "logs"))
    log_json = _env_flag("LOG_JSON", False)
    log_to_console = _env_flag("LOG_TO_CONSOLE", True)
    log_to_file_default = bool(service_name)
    log_to_file = _env_flag("LOG_TO_FILE", log_to_file_default)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    # Remove only handlers managed by this function to avoid duplicates on repeated calls.
    for handler in list(root_logger.handlers):
        if getattr(handler, "_capital_managed", False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass

    handlers: list[logging.Handler] = []

    if log_to_console:
        console_handler = RichHandler(markup=True, rich_tracebacks=True, show_path=False)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(console_handler, "_capital_managed", True)
        handlers.append(console_handler)

    if service_name and log_to_file:
        file_handler = _DailyLogFileHandler(log_dir, encoding="utf-8")
        if log_json:
            file_handler.setFormatter(_JsonLineFormatter())
        else:
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        setattr(file_handler, "_capital_managed", True)
        handlers.append(file_handler)

    if not handlers:
        fallback_handler = logging.StreamHandler()
        fallback_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        setattr(fallback_handler, "_capital_managed", True)
        handlers.append(fallback_handler)

    for handler in handlers:
        handler.setLevel(resolved_level)
        root_logger.addHandler(handler)


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
