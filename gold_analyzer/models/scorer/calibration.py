from __future__ import annotations


def clamp_probability(value: float | None, default: float = 0.5) -> float:
    if value is None:
        return default
    return max(0.0, min(1.0, float(value)))


def calibrate_probability(value: float | None, *, floor: float = 0.05, ceiling: float = 0.95) -> float:
    probability = clamp_probability(value)
    return max(float(floor), min(float(ceiling), probability))
