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


class TradeExecutionSettings(BaseModel):
    api_base_url: str = DEMO_BASE_URL
    api_key: str = Field(default="", repr=False)
    identifier: str = Field(default="", repr=False)
    password: str = Field(default="", repr=False)
    demo_account_name: str = "DEMOAI"
    auto_execute_signals: bool = False
    default_trade_size: float = 0.05
    max_concurrent_open_trades: int = 1
    max_daily_trades: int = 10
    max_daily_loss: float = 0.0
    min_confidence: float = 0.55
    min_validation_score: float = 55.0
    max_validation_age_seconds: int = 1800
    min_expected_move_pct: float = 0.02
    max_spread_pct: float = 0.08
    estimated_fee_pct: float = 0.0
    estimated_slippage_pct: float = 0.02
    execution_safety_margin_pct: float = 0.02
    allow_missing_spread_demo_fallback: bool = False
    require_valid_volume_regime: bool = False
    price_tolerance: float = 0.1
    stale_signal_minutes: int = 30
    capital_eth_epic: str = "ETHUSD"
    queue_concurrency: int = 1

    @property
    def normalized_base_url(self) -> str:
        return self.api_base_url.rstrip("/")

    def ensure_demo_base_url(self) -> None:
        if self.normalized_base_url != DEMO_BASE_URL:
            raise ConfigError(
                "Capital.com trade execution is demo-only. "
                f"Refusing configured base URL {self.normalized_base_url!r}; expected {DEMO_BASE_URL!r}."
            )

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
            raise ConfigError(f"Missing required Capital.com execution variables: {', '.join(missing)}")


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
    """Write to logs/log_DDMMYYYY.log, rotating by day and optional size."""

    def __init__(
        self,
        log_dir: Path,
        encoding: str = "utf-8",
        max_bytes: int = 0,
        backup_count: int = 0,
        name_suffix: str | None = None,
    ) -> None:
        self._log_dir = log_dir
        self._current_day = self._day_token()
        self._max_bytes = max(0, int(max_bytes or 0))
        self._backup_count = max(0, int(backup_count or 0))
        self._name_suffix = self._safe_name_suffix(name_suffix)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(self._path_for_day(self._current_day), mode="a", encoding=encoding)

    @staticmethod
    def _day_token() -> str:
        return time.strftime("%d%m%Y")

    @staticmethod
    def _safe_name_suffix(value: str | None) -> str:
        if not value:
            return ""
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
        return safe.strip("_")

    def _path_for_day(self, day_token: str) -> Path:
        suffix = f"_{self._name_suffix}" if self._name_suffix else ""
        return self._log_dir / f"log_{day_token}{suffix}.log"

    def _rollover_day_if_needed(self) -> None:
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

    def _rollover_size_if_needed(self) -> None:
        if self._max_bytes <= 0:
            return
        try:
            current_size = Path(self.baseFilename).stat().st_size
        except OSError:
            return
        if current_size < self._max_bytes:
            return
        self.acquire()
        try:
            try:
                current_size = Path(self.baseFilename).stat().st_size
            except OSError:
                return
            if current_size < self._max_bytes:
                return
            if self.stream:
                self.stream.close()
                self.stream = None
            base_path = Path(self.baseFilename)
            try:
                if self._backup_count > 0:
                    oldest = base_path.with_name(f"{base_path.name}.{self._backup_count}")
                    if oldest.exists():
                        oldest.unlink()
                    for index in range(self._backup_count - 1, 0, -1):
                        source = base_path.with_name(f"{base_path.name}.{index}")
                        target = base_path.with_name(f"{base_path.name}.{index + 1}")
                        if source.exists():
                            os.replace(source, target)
                    if base_path.exists():
                        os.replace(base_path, base_path.with_name(f"{base_path.name}.1"))
                elif base_path.exists():
                    base_path.write_text("", encoding=self.encoding or "utf-8")
            except OSError:
                # Multiple dashboard workers may still hold older shared log files on Windows.
                # Logging should never stop migrations, workers, or request handling.
                pass
            finally:
                self.stream = self._open()
        finally:
            self.release()

    def _rollover_if_needed(self) -> None:
        self._rollover_day_if_needed()
        self._rollover_size_if_needed()

    def emit(self, record: logging.LogRecord) -> None:
        self._rollover_if_needed()
        super().emit(record)


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


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


def load_trade_execution_settings() -> TradeExecutionSettings:
    settings = TradeExecutionSettings(
        api_base_url=os.getenv("CAPITAL_API_BASE_URL", DEMO_BASE_URL),
        api_key=os.getenv("CAPITAL_API_KEY", ""),
        identifier=os.getenv("CAPITAL_IDENTIFIER", ""),
        password=os.getenv("CAPITAL_PASSWORD", ""),
        demo_account_name=os.getenv("CAPITAL_DEMO_ACCOUNT_NAME", "DEMOAI").strip() or "DEMOAI",
        auto_execute_signals=_env_flag("AUTO_EXECUTE_SIGNALS", False),
        default_trade_size=_env_float("DEFAULT_TRADE_SIZE", 0.05),
        max_concurrent_open_trades=max(1, _env_int("MAX_CONCURRENT_OPEN_TRADES", 1)),
        max_daily_trades=max(0, _env_int("MAX_DAILY_TRADES", 10)),
        max_daily_loss=max(0.0, _env_float("MAX_DAILY_LOSS", 0.0)),
        min_confidence=_env_float("MIN_TRADE_CONFIDENCE", _env_float("SIGNAL_MIN_CONFIDENCE", 0.55)),
        min_validation_score=_env_float("MIN_TRADE_VALIDATION_SCORE", _env_float("SIGNAL_SCORE_ACTIONABLE_THRESHOLD", 55.0)),
        max_validation_age_seconds=max(1, _env_int("TRADE_VALIDATION_MAX_AGE_SECONDS", 1800)),
        min_expected_move_pct=max(0.0, _env_float("TRADE_MIN_EXPECTED_MOVE_PCT", _env_float("SIGNAL_FLAT_THRESHOLD_PCT", 0.02))),
        max_spread_pct=max(0.0, _env_float("TRADE_MAX_SPREAD_PCT", _env_float("SIGNAL_MAX_SPREAD_PCT", 0.08))),
        estimated_fee_pct=max(0.0, _env_float("TRADE_ESTIMATED_FEE_PCT", 0.0)),
        estimated_slippage_pct=max(0.0, _env_float("TRADE_ESTIMATED_SLIPPAGE_PCT", 0.02)),
        execution_safety_margin_pct=max(0.0, _env_float("TRADE_SAFETY_MARGIN_PCT", 0.02)),
        allow_missing_spread_demo_fallback=_env_flag("TRADE_ALLOW_MISSING_SPREAD_DEMO_FALLBACK", False),
        require_valid_volume_regime=_env_flag("TRADE_REQUIRE_VALID_VOLUME_REGIME", False),
        price_tolerance=max(0.0, _env_float("TRADE_PRICE_TOLERANCE", 0.1)),
        stale_signal_minutes=max(1, _env_int("TRADE_SIGNAL_STALE_MINUTES", 30)),
        capital_eth_epic=os.getenv("CAPITAL_ETH_EPIC", os.getenv("CAPITAL_DEFAULT_EPIC", "ETHUSD")).strip() or "ETHUSD",
        queue_concurrency=max(1, min(_env_int("TRADE_EXECUTION_QUEUE_CONCURRENCY", 1), 3)),
    )
    settings.ensure_demo_base_url()
    return settings


def log_trade_execution_startup(settings: TradeExecutionSettings, logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger(__name__)
    target.info(
        "Capital demo execution config: base_url=%s demo_account=%s auto_execute=%s "
        "default_size=%s max_open=%s max_daily_trades=%s max_daily_loss=%s "
        "min_confidence=%s min_validation_score=%s max_validation_age_seconds=%s "
        "max_spread_pct=%s estimated_fee_pct=%s estimated_slippage_pct=%s safety_margin_pct=%s "
        "price_tolerance=%s stale_minutes=%s",
        settings.normalized_base_url,
        settings.demo_account_name,
        settings.auto_execute_signals,
        settings.default_trade_size,
        settings.max_concurrent_open_trades,
        settings.max_daily_trades,
        settings.max_daily_loss,
        settings.min_confidence,
        settings.min_validation_score,
        settings.max_validation_age_seconds,
        settings.max_spread_pct,
        settings.estimated_fee_pct,
        settings.estimated_slippage_pct,
        settings.execution_safety_margin_pct,
        settings.price_tolerance,
        settings.stale_signal_minutes,
    )


def configure_logging(level: int | str | None = None, service_name: str | None = None) -> None:
    resolved_level = _resolve_log_level(level)
    log_dir = Path(os.getenv("CAPITAL_LOG_DIR", "logs"))
    log_json = _env_flag("LOG_JSON", False)
    log_to_console = _env_flag("LOG_TO_CONSOLE", True)
    log_to_file_default = bool(service_name)
    log_to_file = _env_flag("LOG_TO_FILE", log_to_file_default)
    log_max_bytes = max(0, _env_int("CAPITAL_LOG_MAX_BYTES", 0))
    log_backup_count = max(0, _env_int("CAPITAL_LOG_BACKUP_COUNT", 0))

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
        file_handler = _DailyLogFileHandler(
            log_dir,
            encoding="utf-8",
            max_bytes=log_max_bytes,
            backup_count=log_backup_count,
            name_suffix=service_name,
        )
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
