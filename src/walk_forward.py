from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect
from forecast_scoring import score_forecast_against_actuals


def _experiment_id(config: dict[str, Any]) -> str:
    token = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(config, sort_keys=True, default=str)).hex[:16]
    return f"wf-{token}"


def _cache_key(*, experiment_id: str, input_end: Any, pred_len: int, baseline: str) -> str:
    raw = f"{experiment_id}:{pd.to_datetime(input_end, utc=True).isoformat()}:{pred_len}:{baseline}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_candles(
    *,
    symbol: str,
    resolution: str,
    price_side: str,
    start_timestamp_utc: str,
    end_timestamp_utc: str,
    dsn: str | None,
) -> pd.DataFrame:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount
            FROM ohlcv_candles
            WHERE symbol = %s
              AND resolution = %s
              AND price_side = %s
              AND timestamp_utc >= %s
              AND timestamp_utc <= %s
            ORDER BY timestamp_utc ASC
            """,
            (symbol, resolution, price_side, start_timestamp_utc, end_timestamp_utc),
        ).fetchall()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    return df


def _baseline_forecast(input_window: pd.DataFrame, actual_window: pd.DataFrame, method: str) -> pd.DataFrame:
    forecast = actual_window[["timestamps", "open", "high", "low", "close", "volume", "amount"]].copy()
    last_close = float(input_window["close"].iloc[-1])
    method_text = str(method or "naive")
    if method_text == "moving_average":
        close = float(input_window["close"].tail(min(12, len(input_window))).mean())
    elif method_text == "drift" and len(input_window) >= 2:
        drift = float(input_window["close"].iloc[-1]) - float(input_window["close"].iloc[-2])
        close_values = [last_close + drift * (idx + 1) for idx in range(len(forecast))]
        forecast["close"] = close_values
        forecast["open"] = close_values
        forecast["high"] = close_values
        forecast["low"] = close_values
        return forecast
    else:
        close = last_close
    forecast["close"] = close
    forecast["open"] = close
    forecast["high"] = close
    forecast["low"] = close
    return forecast


def create_walk_forward_experiment(
    *,
    symbol: str,
    resolution: str,
    start_timestamp_utc: str,
    end_timestamp_utc: str,
    lookback: int,
    pred_len: int,
    stride: int,
    price_side: str = "mid",
    model_version_id: str | None = None,
    feature_set_id: str | None = "raw-ohlcv-v1",
    baselines: list[str] | None = None,
    output_dir: str | Path = "output/walk_forward",
    dsn: str | None = None,
) -> dict[str, Any]:
    baseline_methods = baselines or ["naive"]
    config = {
        "symbol": symbol,
        "resolution": resolution,
        "price_side": price_side,
        "model_version_id": model_version_id,
        "feature_set_id": feature_set_id,
        "start_timestamp_utc": pd.to_datetime(start_timestamp_utc, utc=True).isoformat(),
        "end_timestamp_utc": pd.to_datetime(end_timestamp_utc, utc=True).isoformat(),
        "lookback": int(lookback),
        "pred_len": int(pred_len),
        "stride": int(stride),
        "baselines": baseline_methods,
    }
    experiment_id = _experiment_id(config)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / f"{experiment_id}.json"
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO walk_forward_experiments(
                experiment_id, symbol, resolution, price_side, model_version_id, baseline_method,
                feature_set_id, start_timestamp_utc, end_timestamp_utc, lookback, pred_len,
                stride, status, parameters, artifact_path, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, now())
            ON CONFLICT(experiment_id) DO UPDATE SET
                status = 'PENDING',
                parameters = EXCLUDED.parameters,
                artifact_path = EXCLUDED.artifact_path,
                updated_at = now()
            """,
            (
                experiment_id,
                symbol,
                resolution,
                price_side,
                model_version_id,
                ",".join(baseline_methods),
                feature_set_id,
                config["start_timestamp_utc"],
                config["end_timestamp_utc"],
                int(lookback),
                int(pred_len),
                int(stride),
                Jsonb(config),
                str(artifact_path),
            ),
        )
    return {"experiment_id": experiment_id, "status": "PENDING", "artifact_path": str(artifact_path)}


def _query_candidate_window_metrics(
    *,
    model_version_id: str,
    symbol: str,
    resolution: str,
    input_end_utc: pd.Timestamp,
    forecast_start_utc: pd.Timestamp,
    dsn: str | None,
) -> dict[str, Any] | None:
    """
    Look up a stored prediction run for *model_version_id* that covers the given
    walk-forward window and return its direction metrics, or None if not found.

    Matching uses a ±30-minute tolerance on both timestamp boundaries to
    accommodate prediction-cycle timing jitter.
    """
    tol = pd.Timedelta("30min")
    with connect(dsn) as conn:
        run_row = conn.execute(
            """
            SELECT run_id
            FROM prediction_runs
            WHERE model_version_id = %s
              AND symbol = %s
              AND resolution = %s
              AND input_end_timestamp_utc BETWEEN %s AND %s
              AND forecast_start_timestamp_utc BETWEEN %s AND %s
            ORDER BY generated_at_utc DESC
            LIMIT 1
            """,
            (
                model_version_id,
                symbol,
                resolution,
                (input_end_utc - tol).isoformat(),
                (input_end_utc + tol).isoformat(),
                (forecast_start_utc - tol).isoformat(),
                (forecast_start_utc + tol).isoformat(),
            ),
        ).fetchone()
        if not run_row:
            return None
        run_id = run_row["run_id"]
        outcome_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses
            FROM prediction_outcomes
            WHERE run_id = %s
              AND status IN ('WIN', 'LOSS')
            """,
            (run_id,),
        ).fetchone()
    wins = int((outcome_row or {}).get("wins") or 0)
    losses = int((outcome_row or {}).get("losses") or 0)
    matched = wins + losses
    return {
        "run_id": run_id,
        "wins": wins,
        "losses": losses,
        "direction_accuracy_pct": None if matched == 0 else (wins / matched) * 100.0,
    }


def run_walk_forward_experiment(experiment_id: str, *, dsn: str | None = None) -> dict[str, Any]:
    with connect(dsn) as conn:
        experiment = conn.execute("SELECT * FROM walk_forward_experiments WHERE experiment_id = %s", (experiment_id,)).fetchone()
    if not experiment:
        raise ValueError(f"Walk-forward experiment not found: {experiment_id}")
    params = dict(experiment.get("parameters") or {})
    baselines = params.get("baselines") or [experiment.get("baseline_method") or "naive"]
    model_version_id: str | None = experiment.get("model_version_id") or params.get("model_version_id")
    candles = _load_candles(
        symbol=experiment["symbol"],
        resolution=experiment["resolution"],
        price_side=experiment["price_side"],
        start_timestamp_utc=experiment["start_timestamp_utc"],
        end_timestamp_utc=experiment["end_timestamp_utc"],
        dsn=dsn,
    )
    lookback = int(experiment["lookback"])
    pred_len = int(experiment["pred_len"])
    stride = max(1, int(experiment["stride"]))
    completed = 0
    wins = losses = 0
    mape_values: list[float] = []
    results: list[dict[str, Any]] = []
    # Candidate tracking
    candidate_windows_covered = 0
    candidate_beats_baseline = 0
    for start in range(0, max(0, len(candles) - lookback - pred_len + 1), stride):
        input_window = candles.iloc[start : start + lookback].copy()
        actual_window = candles.iloc[start + lookback : start + lookback + pred_len].copy()
        if len(input_window) < lookback or len(actual_window) < pred_len:
            continue
        input_end = input_window["timestamps"].iloc[-1]
        forecast_start = actual_window["timestamps"].iloc[0]
        for baseline in baselines:
            cache_key = _cache_key(experiment_id=experiment_id, input_end=input_end, pred_len=pred_len, baseline=baseline)
            forecast = _baseline_forecast(input_window, actual_window, str(baseline))
            score = score_forecast_against_actuals(
                forecast,
                actual_window,
                last_input_close=float(input_window["close"].iloc[-1]),
            )
            summary = score["summary"]
            wins += int(summary["wins"])
            losses += int(summary["losses"])
            if summary.get("mape_pct") is not None:
                mape_values.append(float(summary["mape_pct"]))
            baseline_accuracy = None if (summary["wins"] + summary["losses"]) == 0 else (
                summary["wins"] / (summary["wins"] + summary["losses"]) * 100.0
            )
            # --- Candidate evaluation for this window ---
            candidate_metrics: dict[str, Any] | None = None
            if model_version_id and str(baseline) == baselines[0]:
                # Only query candidate once per window (not once per baseline)
                candidate_metrics = _query_candidate_window_metrics(
                    model_version_id=model_version_id,
                    symbol=experiment["symbol"],
                    resolution=experiment["resolution"],
                    input_end_utc=input_end,
                    forecast_start_utc=forecast_start,
                    dsn=dsn,
                )
                if candidate_metrics is not None:
                    candidate_windows_covered += 1
                    cand_acc = candidate_metrics.get("direction_accuracy_pct")
                    if cand_acc is not None and baseline_accuracy is not None and cand_acc > baseline_accuracy:
                        candidate_beats_baseline += 1

            metrics = {"baseline": baseline, **summary}
            if candidate_metrics is not None:
                metrics["candidate"] = candidate_metrics
            row_payload = {
                "window_start_timestamp_utc": input_window["timestamps"].iloc[0].isoformat(),
                "input_end_timestamp_utc": input_end.isoformat(),
                "forecast_start_timestamp_utc": forecast_start.isoformat(),
                "forecast_end_timestamp_utc": actual_window["timestamps"].iloc[-1].isoformat(),
                "metrics": metrics,
                "data_quality": {"rows": int(len(input_window))},
                "cache_key": cache_key,
            }
            with connect(dsn) as conn:
                conn.execute(
                    """
                    INSERT INTO walk_forward_results(
                        experiment_id, window_start_timestamp_utc, input_end_timestamp_utc,
                        forecast_start_timestamp_utc, forecast_end_timestamp_utc,
                        metrics, data_quality, cache_key
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(experiment_id, cache_key) DO UPDATE SET
                        metrics = EXCLUDED.metrics,
                        data_quality = EXCLUDED.data_quality
                    """,
                    (
                        experiment_id,
                        row_payload["window_start_timestamp_utc"],
                        row_payload["input_end_timestamp_utc"],
                        row_payload["forecast_start_timestamp_utc"],
                        row_payload["forecast_end_timestamp_utc"],
                        Jsonb(metrics),
                        Jsonb(row_payload["data_quality"]),
                        cache_key,
                    ),
                )
            results.append(row_payload)
            completed += 1
    samples = wins + losses
    # beats_naive_rate_pct: how often candidate beat the primary baseline, among covered windows
    beats_naive_rate_pct: float | None = None
    if model_version_id and candidate_windows_covered > 0:
        beats_naive_rate_pct = (candidate_beats_baseline / candidate_windows_covered) * 100.0
    # If model_version_id was requested but no candidate runs were found, mark BASELINE_ONLY
    final_status = "COMPLETED"
    if model_version_id and candidate_windows_covered == 0:
        final_status = "BASELINE_ONLY"
    summary = {
        "direction_accuracy_pct": None if samples == 0 else (wins / samples) * 100.0,
        "mape_pct": None if not mape_values else sum(mape_values) / len(mape_values),
        "beats_naive_rate_pct": beats_naive_rate_pct,
        "candidate_windows_covered": candidate_windows_covered,
        "windows_completed": completed,
        "wins": wins,
        "losses": losses,
    }
    artifact_path = Path(experiment.get("artifact_path") or f"output/walk_forward/{experiment_id}.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps({"experiment_id": experiment_id, "summary": summary, "results": results}, indent=2, default=str), encoding="utf-8")
    with connect(dsn) as conn:
        conn.execute(
            "UPDATE walk_forward_experiments SET status = %s, artifact_path = %s, updated_at = now() WHERE experiment_id = %s",
            (final_status, str(artifact_path), experiment_id),
        )
    return {"experiment_id": experiment_id, "status": final_status, "windows_completed": completed, "metrics": summary}


def get_walk_forward_experiment(experiment_id: str, *, dsn: str | None = None) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        experiment = conn.execute("SELECT * FROM walk_forward_experiments WHERE experiment_id = %s", (experiment_id,)).fetchone()
        if not experiment:
            return None
        rows = conn.execute(
            """
            SELECT metrics
            FROM walk_forward_results
            WHERE experiment_id = %s
            ORDER BY forecast_start_timestamp_utc
            """,
            (experiment_id,),
        ).fetchall()
    wins = sum(int((row.get("metrics") or {}).get("wins") or 0) for row in rows)
    losses = sum(int((row.get("metrics") or {}).get("losses") or 0) for row in rows)
    samples = wins + losses
    mape_values = [float((row.get("metrics") or {}).get("mape_pct")) for row in rows if (row.get("metrics") or {}).get("mape_pct") is not None]
    return {
        "experiment_id": experiment_id,
        "status": experiment["status"],
        "windows_total": len(rows),
        "windows_completed": len(rows),
        "metrics": {
            "direction_accuracy_pct": None if samples == 0 else (wins / samples) * 100.0,
            "mape_pct": None if not mape_values else sum(mape_values) / len(mape_values),
            "beats_naive_rate_pct": None,
        },
    }
