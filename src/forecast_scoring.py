from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SCORING_VERSION = "v1"
DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION = "signal_trade_v1"
DEFAULT_FLAT_THRESHOLD_PCT = 0.02
DEFAULT_COST_THRESHOLD_PCT = 0.05


def direction_from_move_pct(move_pct: float, flat_threshold_pct: float = 0.02) -> str:
    if not math.isfinite(float(move_pct)):
        return "FLAT"
    if abs(float(move_pct)) < flat_threshold_pct:
        return "FLAT"
    return "UP" if float(move_pct) > 0 else "DOWN"


def direction_from_prices(anchor_close: float, close: float, flat_threshold_pct: float = 0.02) -> str:
    anchor = float(anchor_close)
    value = float(close)
    if not math.isfinite(anchor) or not math.isfinite(value) or anchor == 0:
        return "FLAT"
    move_pct = ((value / anchor) - 1.0) * 100.0
    return direction_from_move_pct(move_pct, flat_threshold_pct)


def move_pct_from_prices(anchor_close: float | None, close: float | None) -> float | None:
    if anchor_close is None or close is None:
        return None
    anchor = float(anchor_close)
    value = float(close)
    if not math.isfinite(anchor) or not math.isfinite(value) or anchor == 0:
        return None
    return ((value / anchor) - 1.0) * 100.0


def _clean_close_frame(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if "timestamps" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{label} requires timestamps and close columns")
    clean = df[["timestamps", "close"]].copy()
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    clean["close"] = pd.to_numeric(clean["close"], errors="coerce")
    clean = clean.dropna(subset=["timestamps", "close"])
    clean = clean.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return clean


def _clean_ohlc_frame(df: pd.DataFrame, label: str) -> pd.DataFrame:
    if "timestamps" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{label} requires timestamps and close columns")
    clean = df.copy()
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    for column in ("open", "high", "low", "close"):
        if column not in clean.columns:
            clean[column] = clean["close"]
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean[["timestamps", "open", "high", "low", "close"]]
    clean = clean.dropna(subset=["timestamps", "open", "high", "low", "close"])
    clean = clean.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return clean


def _safe_pct_error(error: float, actual_close: float) -> float | None:
    if actual_close == 0:
        return None
    return (error / actual_close) * 100.0


def _mean(values: list[float]) -> float | None:
    return None if not values else float(np.mean(values))


def score_forecast_against_actuals(
    forecast_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    *,
    last_input_close: float | None = None,
    flat_threshold_pct: float = 0.02,
    cost_threshold_pct: float = 0.05,
) -> dict[str, Any]:
    """Score forecast candles against actual candles using one anchoring model.

    Forecast direction is measured from the previous forecast close, with the
    first horizon anchored to last_input_close when it is available. Actual
    direction is measured from the previous actual close, with the first horizon
    anchored to last_input_close when it is available.
    """
    forecast = _clean_close_frame(forecast_df, "forecast")
    actual = _clean_close_frame(actual_df, "actual")
    actual_by_ts = {row["timestamps"].isoformat(): float(row["close"]) for _, row in actual.iterrows()}

    forecast_anchor = None if last_input_close is None else float(last_input_close)
    actual_anchor = None if last_input_close is None else float(last_input_close)

    rows: list[dict[str, Any]] = []
    wins = losses = missing_actual = direction_pending = 0
    errors: list[float] = []
    abs_errors: list[float] = []
    pct_errors: list[float] = []
    expected_moves: list[float] = []
    realized_moves: list[float] = []
    movement_after_cost: list[float] = []

    for index, forecast_row in forecast.iterrows():
        ts = forecast_row["timestamps"].isoformat()
        forecast_close = float(forecast_row["close"])
        row_forecast_anchor = forecast_anchor
        row_actual_anchor = actual_anchor
        expected_move_pct = move_pct_from_prices(row_forecast_anchor, forecast_close)
        predicted_direction = (
            None
            if expected_move_pct is None
            else direction_from_move_pct(expected_move_pct, flat_threshold_pct)
        )
        actual_close = actual_by_ts.get(ts)
        actual_direction = None
        realized_move_pct = None
        close_error = None
        close_error_pct = None
        status = "PENDING"
        after_cost = None

        if actual_close is None:
            missing_actual += 1
        else:
            realized_move_pct = move_pct_from_prices(row_actual_anchor, actual_close)
            actual_direction = (
                None
                if realized_move_pct is None
                else direction_from_move_pct(realized_move_pct, flat_threshold_pct)
            )
            close_error = forecast_close - actual_close
            close_error_pct = _safe_pct_error(close_error, actual_close)
            errors.append(close_error)
            abs_errors.append(abs(close_error))
            if close_error_pct is not None:
                pct_errors.append(abs(close_error_pct))
            if expected_move_pct is not None:
                expected_moves.append(abs(expected_move_pct))
            if realized_move_pct is not None:
                realized_moves.append(abs(realized_move_pct))
            if predicted_direction is None or actual_direction is None:
                direction_pending += 1
            else:
                signed_realized = realized_move_pct if predicted_direction == "UP" else -realized_move_pct
                if predicted_direction == "FLAT":
                    signed_realized = -abs(realized_move_pct)
                after_cost = signed_realized - cost_threshold_pct
                movement_after_cost.append(after_cost)
                status = "WIN" if predicted_direction == actual_direction else "LOSS"
                if status == "WIN":
                    wins += 1
                else:
                    losses += 1
            actual_anchor = actual_close

        rows.append(
            {
                "horizon_index": int(index) + 1,
                "timestamp_utc": ts,
                "forecast_close": forecast_close,
                "actual_close": actual_close,
                "forecast_anchor_close": row_forecast_anchor,
                "actual_anchor_close": row_actual_anchor,
                "expected_move_pct": expected_move_pct,
                "realized_move_pct": realized_move_pct,
                "predicted_direction": predicted_direction,
                "actual_direction": actual_direction,
                "close_error": close_error,
                "close_error_pct": close_error_pct,
                "movement_after_cost_pct": after_cost,
                "status": status,
            }
        )
        forecast_anchor = forecast_close

    validated = wins + losses
    total_rows = int(len(forecast))
    matched_candles = total_rows - missing_actual
    summary = {
        "total_rows": total_rows,
        "matched_candles": matched_candles,
        "missing_actual_candles": missing_actual,
        "direction_pending": direction_pending,
        "pending": missing_actual + direction_pending,
        "validated": validated,
        "wins": wins,
        "losses": losses,
        "status": "PENDING" if validated == 0 else ("WIN" if wins >= losses else "LOSS"),
        "direction_accuracy_pct": None if validated == 0 else (wins / validated) * 100.0,
        "direction_matches": wins,
        "direction_comparable_candles": validated,
        "mae": _mean(abs_errors),
        "rmse": None if not errors else float(math.sqrt(float(np.mean(np.square(errors))))),
        "mape_pct": _mean(pct_errors),
        "average_forecast_error": _mean(errors),
        "max_abs_error": None if not abs_errors else float(max(abs_errors)),
        "max_abs_percentage_error": None if not pct_errors else float(max(pct_errors)),
        "expected_movement_pct": _mean(expected_moves),
        "realized_movement_pct": _mean(realized_moves),
        "average_movement_after_cost_pct": _mean(movement_after_cost),
    }
    return {"summary": summary, "rows": rows}


def _signal_final_move_pct(signal: str, entry_price: float, close: float) -> float | None:
    move_pct = move_pct_from_prices(entry_price, close)
    if move_pct is None:
        return None
    signal_text = _trade_direction(signal)
    if signal_text is None:
        return None
    if signal_text == "SELL":
        return -move_pct
    return move_pct


def _trade_direction(signal: str | None) -> str | None:
    signal_text = str(signal or "").upper().strip()
    if signal_text in {"BUY", "LONG"}:
        return "BUY"
    if signal_text in {"SELL", "SHORT"}:
        return "SELL"
    return None


def score_trade_signal_outcome(
    *,
    signal: str,
    entry_price: float,
    tp_price: float,
    sl_price: float,
    actual_df: pd.DataFrame,
    cost_threshold_pct: float = DEFAULT_COST_THRESHOLD_PCT,
    forecast_end_timestamp_utc: Any | None = None,
    policy_version: str = DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
) -> dict[str, Any]:
    """Score the trade signal outcome using TP/SL and final-close fallback.

    Forecast accuracy remains per-horizon direction scoring. This function is
    intentionally trade-specific: actionable signals use TP/SL first-touch,
    HOLD signals are not counted as WIN/LOSS, and ambiguous same-candle TP/SL
    touches are excluded from win-rate by returning AMBIGUOUS.
    """
    signal_text = str(signal or "HOLD").upper().strip()
    trade_direction = _trade_direction(signal_text)
    actionable = trade_direction is not None
    actual = _clean_ohlc_frame(actual_df, "actual")
    result = {
        "policy_version": policy_version,
        "signal": signal_text,
        "status": "PENDING",
        "reason": "No actual candles are available for the signal window.",
        "hit_timestamp_utc": None,
        "exit_price": None,
        "realized_move_pct": None,
        "movement_after_cost_pct": None,
        "validated_candles": int(len(actual)),
        "hold_quality": None,
        "ambiguous": False,
    }
    if actual.empty:
        return result

    entry = float(entry_price)
    tp = float(tp_price)
    sl = float(sl_price)
    cost = float(cost_threshold_pct)
    forecast_end = None if forecast_end_timestamp_utc is None else pd.to_datetime(forecast_end_timestamp_utc, utc=True)
    complete = forecast_end is None or pd.Timestamp(actual["timestamps"].max()) >= forecast_end
    final_row = actual.iloc[-1]
    final_close = float(final_row["close"])
    final_move_pct = _signal_final_move_pct(signal_text, entry, final_close)
    movement_after_cost = None if final_move_pct is None else float(final_move_pct) - cost

    if not actionable:
        if not complete:
            result.update(
                {
                    "reason": "HOLD signal is waiting for the forecast window to complete.",
                    "realized_move_pct": final_move_pct,
                    "movement_after_cost_pct": movement_after_cost,
                }
            )
            return result
        missed = final_move_pct is not None and abs(float(final_move_pct)) >= cost
        result.update(
            {
                "status": "MISSED_MOVE" if missed else "GOOD_HOLD",
                "reason": (
                    "HOLD missed a move beyond the cost threshold."
                    if missed
                    else "HOLD avoided trading a move inside the cost threshold."
                ),
                "hit_timestamp_utc": pd.Timestamp(final_row["timestamps"]).isoformat(),
                "exit_price": final_close,
                "realized_move_pct": final_move_pct,
                "movement_after_cost_pct": movement_after_cost,
                "hold_quality": "MISSED_MOVE" if missed else "GOOD_HOLD",
            }
        )
        return result

    for _, row in actual.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        timestamp = pd.Timestamp(row["timestamps"]).isoformat()
        if trade_direction == "BUY":
            tp_hit = high >= tp
            sl_hit = low <= sl
            win_price = tp
            loss_price = sl
        else:
            tp_hit = low <= tp
            sl_hit = high >= sl
            win_price = tp
            loss_price = sl
        if tp_hit and sl_hit:
            result.update(
                {
                    "status": "AMBIGUOUS",
                    "reason": "TP and SL were both touched in the same candle; intrabar order is unknown.",
                    "hit_timestamp_utc": timestamp,
                    "realized_move_pct": final_move_pct,
                    "movement_after_cost_pct": movement_after_cost,
                    "ambiguous": True,
                }
            )
            return result
        if tp_hit or sl_hit:
            won = bool(tp_hit)
            exit_price = win_price if won else loss_price
            realized_move_pct = _signal_final_move_pct(signal_text, entry, float(exit_price))
            result.update(
                {
                    "status": "WIN" if won else "LOSS",
                    "reason": "Take-profit was touched first." if won else "Stop-loss was touched first.",
                    "hit_timestamp_utc": timestamp,
                    "exit_price": exit_price,
                    "realized_move_pct": realized_move_pct,
                    "movement_after_cost_pct": None if realized_move_pct is None else float(realized_move_pct) - cost,
                }
            )
            return result

    if not complete:
        result.update(
            {
                "reason": "Signal is still open; neither TP nor SL has been touched yet.",
                "exit_price": final_close,
                "realized_move_pct": final_move_pct,
                "movement_after_cost_pct": movement_after_cost,
            }
        )
        return result

    status = "EXPIRED"
    reason = "Signal expired without touching TP or SL and ended inside the cost threshold."
    if movement_after_cost is not None and movement_after_cost > 0:
        status = "WIN"
        reason = "Signal expired without touching TP/SL but final close cleared cost in the signal direction."
    elif final_move_pct is not None and final_move_pct < -cost:
        status = "LOSS"
        reason = "Signal expired without touching TP/SL and final close moved against the signal beyond cost."
    result.update(
        {
            "status": status,
            "reason": reason,
            "hit_timestamp_utc": pd.Timestamp(final_row["timestamps"]).isoformat(),
            "exit_price": final_close,
            "realized_move_pct": final_move_pct,
            "movement_after_cost_pct": movement_after_cost,
        }
    )
    return result


def signal_status_from_counts(wins: int, losses: int) -> str:
    validated = int(wins) + int(losses)
    if validated <= 0:
        return "PENDING"
    return "WIN" if int(wins) >= int(losses) else "LOSS"


def score_signal_quality(
    *,
    signal: str,
    confidence: float,
    expected_move_pct: float,
    cost_threshold_pct: float,
    scoring_summary: dict[str, Any],
    trade_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal_text = str(signal or "HOLD").upper().strip()
    actionable = _trade_direction(signal_text) is not None
    realized_move_pct = scoring_summary.get("realized_movement_pct")
    status = str((trade_outcome or {}).get("status") or scoring_summary.get("status") or "PENDING").upper()
    movement_after_cost_pct = scoring_summary.get("average_movement_after_cost_pct")
    if trade_outcome is not None:
        realized_move_pct = trade_outcome.get("realized_move_pct")
        movement_after_cost_pct = trade_outcome.get("movement_after_cost_pct")
    false_positive = None
    hold_quality = None
    if actionable and status in {"WIN", "LOSS"}:
        false_positive = status == "LOSS"
    if trade_outcome is not None and trade_outcome.get("hold_quality"):
        hold_quality = trade_outcome.get("hold_quality")
    elif not actionable and realized_move_pct is not None:
        hold_quality = "GOOD_HOLD" if abs(float(realized_move_pct)) < float(cost_threshold_pct) else "MISSED_MOVE"
    precision_bucket = None
    if actionable:
        accuracy = scoring_summary.get("direction_accuracy_pct")
        if accuracy is None:
            precision_bucket = "PENDING"
        elif float(accuracy) >= 60.0:
            precision_bucket = "HIGH"
        elif float(accuracy) >= 50.0:
            precision_bucket = "MEDIUM"
        else:
            precision_bucket = "LOW"
    return {
        "signal": signal_text,
        "status": status,
        "actionable": actionable,
        "confidence": float(confidence),
        "expected_move_pct": float(expected_move_pct),
        "realized_move_pct": realized_move_pct,
        "cost_threshold_pct": float(cost_threshold_pct),
        "movement_after_cost_pct": movement_after_cost_pct,
        "precision_bucket": precision_bucket,
        "false_positive": false_positive,
        "hold_quality": hold_quality,
        "outcome_policy_version": (trade_outcome or {}).get("policy_version"),
        "outcome_reason": (trade_outcome or {}).get("reason"),
        "outcome_hit_timestamp_utc": (trade_outcome or {}).get("hit_timestamp_utc"),
    }
