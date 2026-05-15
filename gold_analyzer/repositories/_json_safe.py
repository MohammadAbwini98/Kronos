from __future__ import annotations

import math
from typing import Any

import pandas as pd


def finite_or_none(value: Any) -> float | None:
    scalar = _scalar(value)
    if scalar is None:
        return None
    try:
        number = float(scalar)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def int_or_none(value: Any) -> int | None:
    scalar = _scalar(value)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except (TypeError, ValueError):
        return None


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_json(item) for item in value]
    scalar = _scalar(value)
    if scalar is None:
        return None
    if isinstance(scalar, float) and not math.isfinite(scalar):
        return None
    return scalar


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


__all__ = ["finite_or_none", "int_or_none", "sanitize_json"]