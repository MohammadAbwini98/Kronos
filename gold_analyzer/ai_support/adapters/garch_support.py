from __future__ import annotations


def score_garch_support(risk_state: str | None) -> float:
    normalized = str(risk_state or "").upper().strip()
    return {
        "LOW": 0.5,
        "NORMAL": 1.0,
        "HIGH": -0.5,
        "EXTREME": -1.0,
    }.get(normalized, 0.0)


__all__ = ["score_garch_support"]