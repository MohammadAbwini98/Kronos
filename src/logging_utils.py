from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE_KEYWORDS = {
    "api_key",
    "password",
    "identifier",
    "cst",
    "security_token",
    "token",
    "authorization",
    "postgres_dsn",
    "dsn",
    "secret",
    "credential",
    "x-security-token",
}

_COMMAND_SENSITIVE_FLAGS = {
    "--postgres-dsn",
    "--password",
    "--api-key",
    "--token",
    "--identifier",
}

_MAX_LOG_STR_LEN = 300


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _truncate(value: str, *, max_len: int = _MAX_LOG_STR_LEN) -> str:
    if len(value) <= max_len:
        return value
    return f"{value[: max_len - 12]}...(truncated)"


def _looks_sensitive_key(key: str) -> bool:
    key_l = str(key).lower().replace("_", "-")
    return any(keyword.replace("_", "-") in key_l for keyword in _SENSITIVE_KEYWORDS)


def mask_secret(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def mask_dsn(dsn: str | None) -> str:
    if not dsn:
        return ""
    try:
        parsed = urlsplit(dsn)
        if "@" not in parsed.netloc:
            return _truncate(dsn)
        userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
        if ":" not in userinfo:
            return _truncate(urlunsplit((parsed.scheme, f"{userinfo}:***@{hostinfo}", parsed.path, parsed.query, parsed.fragment)))
        username = userinfo.split(":", 1)[0]
        masked = urlunsplit((parsed.scheme, f"{username}:***@{hostinfo}", parsed.path, parsed.query, parsed.fragment))
        return _truncate(masked)
    except Exception:  # noqa: BLE001
        return mask_secret(dsn)


def _sanitize_text(text: str) -> str:
    masked = text
    masked = re.sub(r"(postgres(?:ql)?://[^:\s]+:)([^@\s]+)(@)", r"\1***\3", masked, flags=re.IGNORECASE)
    masked = re.sub(r"(?i)(x-security-token|cst|authorization)\s*[:=]\s*([^\s,;]+)", r"\1=***", masked)
    masked = re.sub(r"(?i)(password|api_key|token|identifier|secret|credential)\s*[:=]\s*([^\s,;]+)", r"\1=***", masked)
    return _truncate(masked)


def _sanitize_value(value: Any, *, key_hint: str | None = None) -> Any:
    if key_hint and _looks_sensitive_key(key_hint):
        if "dsn" in key_hint.lower():
            return mask_dsn(str(value) if value is not None else None)
        return mask_secret(None if value is None else str(value))

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return _sanitize_text(value)

    if isinstance(value, bytes):
        return _sanitize_text(value.decode("utf-8", errors="replace"))

    if isinstance(value, dict):
        return safe_log_dict(value)

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            pass

    return _truncate(repr(value))


def safe_log_dict(payload: dict) -> dict:
    safe: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        key_text = str(key)
        safe[key_text] = _sanitize_value(value, key_hint=key_text)
    return safe


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _truncate(repr(value))


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {"event": event, **safe_log_dict(fields)}
    logger.log(level, json.dumps(payload, default=_json_default, ensure_ascii=True))


@contextmanager
def timed_step(logger: logging.Logger, event: str, **fields: Any) -> Iterator[None]:
    start = time.perf_counter()
    log_event(logger, logging.INFO, f"{event}.start", **fields)
    try:
        yield
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_event(
            logger,
            logging.ERROR,
            f"{event}.error",
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
            **fields,
        )
        raise
    duration_ms = int((time.perf_counter() - start) * 1000)
    log_event(logger, logging.INFO, f"{event}.completed", duration_ms=duration_ms, **fields)


def safe_command_for_log(cmd: list[str]) -> list[str]:
    if not cmd:
        return []
    masked: list[str] = []
    mask_next = False
    for raw in cmd:
        arg = str(raw)
        lower = arg.lower()
        if mask_next:
            masked.append(mask_secret(arg))
            mask_next = False
            continue

        if lower in _COMMAND_SENSITIVE_FLAGS:
            masked.append(arg)
            mask_next = True
            continue

        if "=" in arg and lower.split("=", 1)[0] in _COMMAND_SENSITIVE_FLAGS:
            flag, _value = arg.split("=", 1)
            masked.append(f"{flag}={mask_secret(_value)}")
            continue

        if re.match(r"(?i)^(postgres_dsn|dsn|password|api_key|token|identifier)=", arg):
            key, value = arg.split("=", 1)
            if "dsn" in key.lower():
                masked.append(f"{key}={mask_dsn(value)}")
            else:
                masked.append(f"{key}={mask_secret(value)}")
            continue

        masked.append(_truncate(_sanitize_text(arg), max_len=200))
    return masked


def output_tail(text: str | None, max_chars: int = 2000) -> str:
    if not text:
        return ""
    tail = str(text)
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
    return _sanitize_text(tail)


def new_correlation_id(prefix: str) -> str:
    safe_prefix = "".join(ch for ch in str(prefix or "id").lower() if ch.isalnum() or ch == "_") or "id"
    day = date.today().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6]
    return f"{safe_prefix}_{day}_{suffix}"
