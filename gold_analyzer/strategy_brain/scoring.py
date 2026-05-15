from __future__ import annotations


def clamp_score(value: float | None, *, lower: float = 0.0, upper: float = 100.0) -> float | None:
    if value is None:
        return None
    return max(lower, min(upper, float(value)))


def combine_weighted_scores(components: dict[str, float | None]) -> float | None:
    values = [clamp_score(value) for value in components.values() if value is not None]
    if not values:
        return None
    return sum(values) / len(values)