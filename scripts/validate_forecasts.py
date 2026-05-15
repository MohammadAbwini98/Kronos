from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import configure_logging  # noqa: E402
from db import connect  # noqa: E402
from forecast_scoring import direction_from_move_pct, direction_from_prices  # noqa: E402


LOGGER = logging.getLogger(__name__)
DEST_TABLE = "forecast_validation"
SUPPORTED_TIMEFRAME_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _default_destination_schema() -> str:
    env_value = (os.getenv("FORECAST_VALIDATION_SCHEMA") or "").strip()
    if env_value:
        return env_value
    try:
        from db import postgres_schema

        return postgres_schema()
    except Exception:  # noqa: BLE001
        return "gold_analytics"


@dataclass
class ValidationArgs:
    dsn: str | None
    mirror_legacy: bool
    model_key: str | None
    epic: str | None
    timeframe: str | None
    lookback_hours: int
    flat_threshold_pct: float
    trading_cost_pct: float
    min_samples: int
    dry_run: bool


def parse_args() -> ValidationArgs:
    parser = argparse.ArgumentParser(description="Validate matured forecasts against actual candles.")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN/.env values.")
    parser.add_argument(
        "--mirror-legacy",
        action="store_true",
        help="Also write to the legacy search_path forecast_validation table used by dashboard APIs.",
    )
    parser.add_argument("--model-key", default=None, help="Optional model filter.")
    parser.add_argument("--epic", default=None, help="Optional epic filter.")
    parser.add_argument("--timeframe", default=None, help="Optional timeframe filter.")
    parser.add_argument("--lookback-hours", type=int, default=168, help="Limit to recent forecasts by created_at.")
    parser.add_argument("--flat-threshold-pct", type=float, default=0.02)
    parser.add_argument("--trading-cost-pct", type=float, default=0.05, help="Spread/cost threshold in percentage points.")
    parser.add_argument("--min-samples", type=int, default=20, help="Skip groups with fewer matched rows.")
    parser.add_argument("--dry-run", action="store_true", help="Compute metrics without writing to DB.")
    raw = parser.parse_args()
    return ValidationArgs(
        dsn=raw.dsn,
        mirror_legacy=bool(raw.mirror_legacy),
        model_key=raw.model_key,
        epic=raw.epic,
        timeframe=raw.timeframe,
        lookback_hours=max(1, int(raw.lookback_hours)),
        flat_threshold_pct=float(raw.flat_threshold_pct),
        trading_cost_pct=float(raw.trading_cost_pct),
        min_samples=max(1, int(raw.min_samples)),
        dry_run=bool(raw.dry_run),
    )


def _validated_identifier(value: str, label: str) -> str:
    text = (value or "").strip()
    if not IDENTIFIER_RE.match(text):
        raise ValueError(f"Invalid {label}: {value!r}")
    return text


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mean(values: list[float]) -> float | None:
    return None if not values else float(np.mean(values))


def _signal_pnl_pct(predicted_direction: str, realized_move_pct: float, cost_pct: float) -> float:
    if predicted_direction == "UP":
        return realized_move_pct - cost_pct
    if predicted_direction == "DOWN":
        return (-realized_move_pct) - cost_pct
    return -abs(realized_move_pct) - cost_pct


def _max_drawdown_from_returns(returns_pct: list[float]) -> float | None:
    if not returns_pct:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in returns_pct:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return float(max_dd)


def _calibration_curve(probabilities: list[float], outcomes: list[int], bins: int = 10) -> list[dict[str, Any]]:
    if not probabilities or not outcomes:
        return []
    frame = pd.DataFrame({"prob": probabilities, "actual": outcomes})
    frame = frame[(frame["prob"] >= 0.0) & (frame["prob"] <= 1.0)]
    if frame.empty:
        return []
    frame["bucket"] = pd.cut(frame["prob"], bins=bins, include_lowest=True, labels=False)
    result: list[dict[str, Any]] = []
    for bucket, part in frame.groupby("bucket"):
        if part.empty:
            continue
        result.append(
            {
                "bucket": int(bucket),
                "count": int(len(part)),
                "predicted_probability": float(part["prob"].mean()),
                "observed_up_rate": float(part["actual"].mean()),
            }
        )
    return result


def _ensure_validation_table(conn: Any, schema: str, table: str) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.{table} (
            id BIGSERIAL PRIMARY KEY,
            model_key TEXT NOT NULL,
            epic TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            horizon_bar INTEGER NOT NULL,
            evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            n_samples INTEGER,
            direction_accuracy DOUBLE PRECISION,
            mae DOUBLE PRECISION,
            rmse DOUBLE PRECISION,
            mape DOUBLE PRECISION,
            hit_rate_after_spread DOUBLE PRECISION,
            profit_factor_if_traded DOUBLE PRECISION,
            average_return_after_cost DOUBLE PRECISION,
            max_drawdown DOUBLE PRECISION,
            brier_score DOUBLE PRECISION,
            prediction_latency_ms DOUBLE PRECISION,
            signal_frequency DOUBLE PRECISION,
            calibration_curve_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            details_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{table}_model_tf_horizon
        ON {schema}.{table}(model_key, timeframe, horizon_bar, evaluated_at DESC)
        """
    )


def _load_matured_forecasts(conn: Any, args: ValidationArgs) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT
            f.id,
            f.run_id,
            f.model_key,
            f.epic,
            f.timeframe,
            f.forecast_for_ts,
            f.horizon_bar,
            f.predicted_close,
            f.predicted_return,
            f.predicted_direction,
            f.confidence,
            f.created_at,
            fr.latency_ms
        FROM forecasts f
        LEFT JOIN forecast_runs fr ON fr.id = f.run_id
        WHERE (%s::text IS NULL OR f.model_key = %s)
          AND (%s::text IS NULL OR f.epic = %s)
          AND (%s::text IS NULL OR f.timeframe = %s)
          AND f.created_at >= (now() - make_interval(hours => %s::integer))
          AND EXISTS (
              SELECT 1
              FROM ohlcv_candles c
              WHERE (c.epic = f.epic OR c.symbol = f.epic)
                AND c.resolution = f.timeframe
                AND c.timestamp_utc = f.forecast_for_ts
          )
        ORDER BY f.epic, f.timeframe, f.model_key, f.horizon_bar, f.forecast_for_ts
        """,
        (
            args.model_key,
            args.model_key,
            args.epic,
            args.epic,
            args.timeframe,
            args.timeframe,
            int(args.lookback_hours),
        ),
    ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        return frame
    frame["forecast_for_ts"] = pd.to_datetime(frame["forecast_for_ts"], utc=True)
    frame["predicted_close"] = pd.to_numeric(frame["predicted_close"], errors="coerce")
    frame["predicted_return"] = pd.to_numeric(frame["predicted_return"], errors="coerce")
    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce")
    frame["latency_ms"] = pd.to_numeric(frame["latency_ms"], errors="coerce")
    return frame


def _load_actual_candles_for_group(
    conn: Any,
    epic: str,
    timeframe: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    *,
    flat_threshold_pct: float,
) -> pd.DataFrame:
    minutes = SUPPORTED_TIMEFRAME_MINUTES.get(str(timeframe).upper(), 5)
    lookback = pd.Timedelta(minutes=max(1, int(minutes)))
    rows = conn.execute(
        """
        SELECT timestamp_utc, close
        FROM ohlcv_candles
        WHERE (epic = %s OR symbol = %s)
          AND resolution = %s
          AND timestamp_utc BETWEEN %s AND %s
        ORDER BY timestamp_utc ASC
        """,
        (epic, epic, timeframe, (start_ts - lookback).to_pydatetime(), end_ts.to_pydatetime()),
    ).fetchall()
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        return frame
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc", "close"]).sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    frame["prev_close"] = frame["close"].shift(1)
    frame["actual_return_pct"] = ((frame["close"] / frame["prev_close"]) - 1.0) * 100.0
    frame["actual_direction"] = frame["actual_return_pct"].apply(
        lambda value: direction_from_move_pct(float(value), flat_threshold_pct=flat_threshold_pct) if pd.notna(value) else None
    )
    return frame.reset_index(drop=True)


def _predicted_direction(row: pd.Series, flat_threshold_pct: float) -> str | None:
    direction = str(row.get("predicted_direction") or "").upper().strip()
    if direction in {"UP", "DOWN", "FLAT"}:
        return direction

    predicted_close = _safe_float(row.get("predicted_close"))
    prev_close = _safe_float(row.get("prev_close"))
    if predicted_close is not None and prev_close is not None:
        return direction_from_prices(prev_close, predicted_close, flat_threshold_pct=flat_threshold_pct)

    predicted_return = _safe_float(row.get("predicted_return"))
    if predicted_return is not None:
        # predicted_return is usually percent-like in this stack; direction only needs sign and threshold.
        return direction_from_move_pct(predicted_return, flat_threshold_pct=flat_threshold_pct)
    return None


def _expected_move_pct(row: pd.Series) -> float | None:
    predicted_close = _safe_float(row.get("predicted_close"))
    prev_close = _safe_float(row.get("prev_close"))
    if predicted_close is not None and prev_close not in {None, 0.0}:
        return ((predicted_close / prev_close) - 1.0) * 100.0
    predicted_return = _safe_float(row.get("predicted_return"))
    return predicted_return


def _compute_group_metrics(frame: pd.DataFrame, args: ValidationArgs) -> dict[str, Any]:
    work = frame.copy()
    work["predicted_dir"] = work.apply(lambda row: _predicted_direction(row, args.flat_threshold_pct), axis=1)
    work = work.dropna(subset=["close", "prev_close", "actual_return_pct", "predicted_dir"])
    if work.empty:
        return {}

    work["expected_move_pct"] = work.apply(_expected_move_pct, axis=1)
    work["close_error"] = work["predicted_close"] - work["close"]
    work["abs_close_error"] = work["close_error"].abs()
    work["abs_pct_error"] = np.where(work["close"] == 0.0, np.nan, (work["abs_close_error"] / work["close"].abs()) * 100.0)
    work["dir_match"] = work["predicted_dir"] == work["actual_direction"]
    work["is_actionable"] = (
        work["predicted_dir"].isin(["UP", "DOWN"]) & (work["expected_move_pct"].abs() >= float(args.trading_cost_pct))
    )
    work["signal_return_after_cost_pct"] = work.apply(
        lambda row: _signal_pnl_pct(str(row["predicted_dir"]), float(row["actual_return_pct"]), float(args.trading_cost_pct)),
        axis=1,
    )
    close_error_values = [float(v) for v in work["close_error"].tolist() if pd.notna(v)]
    abs_close_error_values = [float(v) for v in work["abs_close_error"].tolist() if pd.notna(v)]

    actionable = work[work["is_actionable"]].copy()
    positive_returns = actionable[actionable["signal_return_after_cost_pct"] > 0]["signal_return_after_cost_pct"].tolist()
    negative_returns = actionable[actionable["signal_return_after_cost_pct"] < 0]["signal_return_after_cost_pct"].tolist()
    gross_profit = float(sum(positive_returns)) if positive_returns else 0.0
    gross_loss = abs(float(sum(negative_returns))) if negative_returns else 0.0
    profit_factor = None if gross_loss == 0 else float(gross_profit / gross_loss)
    avg_return_after_cost = _mean(actionable["signal_return_after_cost_pct"].tolist())
    hit_rate_after_spread = None
    if not actionable.empty:
        hit_rate_after_spread = float((actionable["signal_return_after_cost_pct"] > 0).mean())

    prob_up_values: list[float] = []
    actual_up_values: list[int] = []
    for _, row in work.iterrows():
        conf = _safe_float(row.get("confidence"))
        conf = 0.5 if conf is None else min(1.0, max(0.0, conf))
        pred_dir = str(row.get("predicted_dir"))
        if pred_dir == "UP":
            prob_up = conf
        elif pred_dir == "DOWN":
            prob_up = 1.0 - conf
        else:
            prob_up = 0.5
        prob_up_values.append(float(prob_up))
        actual_up_values.append(1 if str(row.get("actual_direction")) == "UP" else 0)

    brier_score = None
    if prob_up_values:
        brier_score = float(np.mean([(p - y) ** 2 for p, y in zip(prob_up_values, actual_up_values)]))

    sample_days = max(
        1.0,
        (
            (work["forecast_for_ts"].max() - work["forecast_for_ts"].min()).total_seconds()
            / 86400.0
        )
        or 1.0,
    )
    signal_frequency = float(len(actionable) / sample_days)

    return {
        "n_samples": int(len(work)),
        "direction_accuracy": float(work["dir_match"].mean()),
        "mae": _mean(abs_close_error_values),
        "rmse": None if not close_error_values else float(math.sqrt(float(np.mean(np.square(close_error_values))))),
        "mape": _mean([float(v) for v in work["abs_pct_error"].tolist() if math.isfinite(float(v))]),
        "hit_rate_after_spread": hit_rate_after_spread,
        "profit_factor_if_traded": profit_factor,
        "average_return_after_cost": avg_return_after_cost,
        "max_drawdown": _max_drawdown_from_returns(actionable["signal_return_after_cost_pct"].tolist()),
        "brier_score": brier_score,
        "prediction_latency_ms": _mean([float(v) for v in work["latency_ms"].tolist() if pd.notna(v)]),
        "signal_frequency": signal_frequency,
        "calibration_curve": _calibration_curve(prob_up_values, actual_up_values),
        "actionable_samples": int(len(actionable)),
    }


def _insert_validation_row(
    conn: Any,
    *,
    schema: str,
    table: str,
    group_key: tuple[str, str, str, int],
    metrics: dict[str, Any],
    flat_threshold_pct: float,
    trading_cost_pct: float,
) -> None:
    model_key, epic, timeframe, horizon_bar = group_key
    details = {
        "mape": metrics.get("mape"),
        "profit_factor_if_traded": metrics.get("profit_factor_if_traded"),
        "average_return_after_cost": metrics.get("average_return_after_cost"),
        "brier_score": metrics.get("brier_score"),
        "prediction_latency_ms": metrics.get("prediction_latency_ms"),
        "signal_frequency": metrics.get("signal_frequency"),
        "actionable_samples": metrics.get("actionable_samples"),
        "flat_threshold_pct": flat_threshold_pct,
        "trading_cost_pct": trading_cost_pct,
    }
    conn.execute(
        f"""
        INSERT INTO {schema}.{table}(
            model_key, epic, timeframe, horizon_bar, n_samples, direction_accuracy,
            mae, rmse, mape, hit_rate_after_spread, profit_factor_if_traded,
            average_return_after_cost, max_drawdown, brier_score, prediction_latency_ms,
            signal_frequency, calibration_curve_json, details_json
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s
        )
        """,
        (
            model_key,
            epic,
            timeframe,
            int(horizon_bar),
            metrics.get("n_samples"),
            metrics.get("direction_accuracy"),
            metrics.get("mae"),
            metrics.get("rmse"),
            metrics.get("mape"),
            metrics.get("hit_rate_after_spread"),
            metrics.get("profit_factor_if_traded"),
            metrics.get("average_return_after_cost"),
            metrics.get("max_drawdown"),
            metrics.get("brier_score"),
            metrics.get("prediction_latency_ms"),
            metrics.get("signal_frequency"),
            Jsonb(metrics.get("calibration_curve") or []),
            Jsonb(details),
        ),
    )


def _insert_legacy_row(conn: Any, group_key: tuple[str, str, str, int], metrics: dict[str, Any]) -> None:
    model_key, epic, timeframe, horizon_bar = group_key
    conn.execute(
        """
        INSERT INTO forecast_validation(
            model_key, epic, timeframe, horizon_bar, n_samples, direction_accuracy,
            mae, rmse, hit_rate_after_spread, profit_factor, avg_return_after_cost,
            max_drawdown, details_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            model_key,
            epic,
            timeframe,
            int(horizon_bar),
            metrics.get("n_samples"),
            metrics.get("direction_accuracy"),
            metrics.get("mae"),
            metrics.get("rmse"),
            metrics.get("hit_rate_after_spread"),
            metrics.get("profit_factor_if_traded"),
            metrics.get("average_return_after_cost"),
            metrics.get("max_drawdown"),
            Jsonb(
                {
                    "mape": metrics.get("mape"),
                    "brier_score": metrics.get("brier_score"),
                    "prediction_latency_ms": metrics.get("prediction_latency_ms"),
                    "signal_frequency": metrics.get("signal_frequency"),
                    "calibration_curve": metrics.get("calibration_curve") or [],
                }
            ),
        ),
    )


def run_validation(args: ValidationArgs) -> dict[str, Any]:
    schema = _validated_identifier(_default_destination_schema(), "schema")
    table = _validated_identifier(DEST_TABLE, "table")

    with connect(args.dsn) as conn:
        if not args.dry_run:
            _ensure_validation_table(conn, schema, table)

        forecasts = _load_matured_forecasts(conn, args)
        if forecasts.empty:
            return {"groups": 0, "inserted": 0, "skipped": 0, "rows": []}

        grouped_rows: list[dict[str, Any]] = []
        inserted = 0
        skipped = 0

        for (epic, timeframe), group in forecasts.groupby(["epic", "timeframe"], sort=False):
            start_ts = pd.to_datetime(group["forecast_for_ts"].min(), utc=True)
            end_ts = pd.to_datetime(group["forecast_for_ts"].max(), utc=True)
            actuals = _load_actual_candles_for_group(
                conn,
                str(epic),
                str(timeframe),
                start_ts,
                end_ts,
                flat_threshold_pct=args.flat_threshold_pct,
            )
            if actuals.empty:
                continue

            merged = group.merge(actuals, left_on="forecast_for_ts", right_on="timestamp_utc", how="inner")
            if merged.empty:
                continue

            for group_key, chunk in merged.groupby(["model_key", "epic", "timeframe", "horizon_bar"], sort=False):
                metrics = _compute_group_metrics(chunk, args)
                if not metrics:
                    skipped += 1
                    continue
                if int(metrics.get("n_samples") or 0) < args.min_samples:
                    skipped += 1
                    continue

                row_payload = {
                    "model_key": group_key[0],
                    "epic": group_key[1],
                    "timeframe": group_key[2],
                    "horizon_bar": int(group_key[3]),
                    **metrics,
                }
                grouped_rows.append(row_payload)

                if args.dry_run:
                    continue

                _insert_validation_row(
                    conn,
                    schema=schema,
                    table=table,
                    group_key=group_key,
                    metrics=metrics,
                    flat_threshold_pct=args.flat_threshold_pct,
                    trading_cost_pct=args.trading_cost_pct,
                )
                inserted += 1

                if args.mirror_legacy:
                    try:
                        _insert_legacy_row(conn, group_key, metrics)
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("legacy forecast_validation write failed: %s", exc)

        return {
            "groups": int(len(grouped_rows)),
            "inserted": int(inserted),
            "skipped": int(skipped),
            "rows": grouped_rows,
        }


def main() -> None:
    configure_logging(service_name="validate_forecasts")
    args = parse_args()
    summary = run_validation(args)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
