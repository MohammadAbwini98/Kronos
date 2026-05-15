from __future__ import annotations


def score_kronos_support(candidate_signal: str, predicted_return: float | None, required_move: float) -> float:
    if predicted_return is None:
        return 0.0
    signal = str(candidate_signal).upper().strip()
    if signal == "BUY":
        if predicted_return >= required_move:
            return 1.0
        if predicted_return > 0.0:
            return 0.5
        if predicted_return <= -required_move:
            return -1.0
        if predicted_return < 0.0:
            return -0.5
        return 0.0
    if predicted_return <= -required_move:
        return 1.0
    if predicted_return < 0.0:
        return 0.5
    if predicted_return >= required_move:
        return -1.0
    if predicted_return > 0.0:
        return -0.5
    return 0.0


__all__ = ["score_kronos_support"]