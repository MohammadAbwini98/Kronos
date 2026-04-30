from __future__ import annotations

import os
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

DEFAULT_DISPLAY_TIMEZONE = "Asia/Amman"


def display_timezone_name() -> str:
    return os.getenv("CAPITAL_DISPLAY_TIMEZONE", DEFAULT_DISPLAY_TIMEZONE)


def display_timezone() -> ZoneInfo:
    return ZoneInfo(display_timezone_name())


def to_local_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True)
    return timestamp.tz_convert(display_timezone())


def format_local_timestamp(value: Any) -> str:
    return to_local_timestamp(value).isoformat()


def format_local_timestamp_for_filename(value: Any) -> str:
    return to_local_timestamp(value).strftime("%Y%m%dT%H%M%S%z")
