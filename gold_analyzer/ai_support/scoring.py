from __future__ import annotations


def clamp_support_value(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(-100.0, min(100.0, float(value)))


def is_soft_veto(value: float | None, *, threshold: float = -60.0) -> bool:
    return clamp_support_value(value) <= threshold