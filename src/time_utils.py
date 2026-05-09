from __future__ import annotations

import os
from typing import Any

import pandas as pd

DEFAULT_DISPLAY_TIMEZONE = "Asia/Amman"


def display_timezone_name() -> str:
    value = os.getenv("CAPITAL_DISPLAY_TIMEZONE", DEFAULT_DISPLAY_TIMEZONE).strip()
    try:
        pd.Timestamp.now(tz=value)
    except Exception:  # noqa: BLE001
        return DEFAULT_DISPLAY_TIMEZONE
    return value


def display_timezone() -> str:
    return display_timezone_name()


def to_local_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True)
    return timestamp.tz_convert(display_timezone_name())


def format_local_timestamp(value: Any) -> str:
    return to_local_timestamp(value).isoformat()


def format_local_timestamp_for_filename(value: Any) -> str:
    return to_local_timestamp(value).strftime("%Y%m%dT%H%M%S%z")
