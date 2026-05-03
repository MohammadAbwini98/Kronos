from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pandas as pd

from config import configure_logging, load_settings
from db import connect
from dataset_snapshots import create_dataset_snapshot
from model_registry import register_model_version
from service_runtime import write_heartbeat

LOGGER = logging.getLogger(__name__)


TRAINING_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


def _resolution_minutes(resolution: str) -> int:
    return {
        "MINUTE": 1,
        "MINUTE_5": 5,
        "MINUTE_15": 15,
        "MINUTE_30": 30,
        "HOUR": 60,
        "HOUR_4": 240,
        "DAY": 1440,
        "WEEK": 10080,
    }.get(str(resolution or "").upper(), 5)


def parse_args() -> argparse.Namespace:
    default_resolution = os.getenv(
        "AUTO_FINETUNE_RESOLUTION",
        os.getenv("LIVE_PRICE_RESOLUTION", os.getenv("SIGNAL_RESOLUTION", os.getenv("CAPITAL_DEFAULT_RESOLUTION", "MINUTE_5"))),
    )
    default_poll_minutes = int(os.getenv("AUTO_FINETUNE_INTERVAL_MINUTES", str(_resolution_minutes(default_resolution))))
    parser = argparse.ArgumentParser(description="Automatically fine-tune Kronos using persisted 5-minute OHLC data from PostgreSQL.")
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--resolution", default=default_resolution)
    parser.add_argument("--price-side", default=os.getenv("CAPITAL_DEFAULT_PRICE_SIDE", "mid"))
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--limit", type=int, default=int(os.getenv("AUTO_FINETUNE_DATASET_LIMIT", "50000")))
    parser.add_argument("--min-rows", type=int, default=int(os.getenv("AUTO_FINETUNE_MIN_ROWS", "2000")))
    parser.add_argument("--min-new-rows", type=int, default=int(os.getenv("AUTO_FINETUNE_MIN_NEW_ROWS", "1000")))
    parser.add_argument("--poll-minutes", type=int, default=default_poll_minutes)
    parser.add_argument("--command", default=os.getenv("KRONOS_FINETUNE_COMMAND", ""))
    parser.add_argument("--model-dir", default=os.getenv("KRONOS_AUTO_MODEL_DIR", r"C:\AI\Models\Kronos\Kronos-auto-finetuned"))
    parser.add_argument("--status-file", default="output/auto_finetune_status.json")
    parser.add_argument(
        "--promotion-min-direction-accuracy",
        type=float,
        default=float(os.getenv("AUTO_FINETUNE_PROMOTION_MIN_DIRECTION_ACCURACY", "55.0")),
    )
    parser.add_argument(
        "--promotion-min-matched-candles",
        type=int,
        default=int(os.getenv("AUTO_FINETUNE_PROMOTION_MIN_MATCHED_CANDLES", "20")),
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _heartbeat(status: str, details: dict[str, Any], dsn: str | None) -> None:
    try:
        write_heartbeat("auto_finetune_worker", status, details, dsn)
    except Exception:  # noqa: BLE001
        LOGGER.debug("Unable to write auto-finetune heartbeat", exc_info=True)


def _read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _model_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "config.json").exists() and (path / "model.safetensors").exists()


def _load_finetune_dataset(*, symbol: str, resolution: str, price_side: str, limit: int, dsn: str | None) -> pd.DataFrame:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount, source
            FROM ohlcv_candles
            WHERE symbol = %s AND resolution = %s AND price_side = %s
            ORDER BY timestamp_utc DESC
            LIMIT %s
            """,
            (symbol, resolution, price_side, limit),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=[*TRAINING_COLUMNS, "source"])
    df = pd.DataFrame(rows)
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return df


def _load_websocket_dataset(*, symbol: str, resolution: str, price_side: str, limit: int, dsn: str | None) -> pd.DataFrame:
    df = _load_finetune_dataset(symbol=symbol, resolution=resolution, price_side=price_side, limit=limit, dsn=dsn)
    if df.empty or "source" not in df.columns:
        return df
    return df[df["source"] == "websocket_ohlc"].reset_index(drop=True)


def _dataset_source_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "source" not in df.columns:
        return {}
    counts = df["source"].fillna("unknown").astype(str).value_counts().to_dict()
    return {str(key): int(value) for key, value in counts.items()}


def _promotion_progress_pct(row_count: int, required_rows: int) -> float:
    if required_rows <= 0:
        return 100.0
    return round(min(100.0, (max(0, row_count) / required_rows) * 100.0), 2)


def _latest_live_metrics(*, symbol: str, resolution: str, dsn: str | None) -> dict[str, Any]:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                """
                SELECT
                    MAX(r.generated_at_utc) AS generated_at_utc,
                    COUNT(DISTINCT r.run_id)::int AS run_count,
                    COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                    COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses
                FROM prediction_runs r
                JOIN prediction_outcomes o ON o.run_id = r.run_id
                WHERE r.symbol = %s
                    AND r.resolution = %s
                    AND o.status IN ('WIN', 'LOSS')
                """,
                (symbol, resolution),
            ).fetchone()
    except Exception:  # noqa: BLE001
        LOGGER.debug("Unable to load latest live metrics", exc_info=True)
        row = None
    if not row:
        return {"matched_candles": 0, "direction_accuracy_pct": None, "run_id": None, "generated_at_utc": None}
    wins = int(row.get("wins") or 0)
    losses = int(row.get("losses") or 0)
    matched = wins + losses
    direction_accuracy = None if matched == 0 else (wins / matched) * 100.0
    return {
        "run_id": "validated_runs",
        "run_count": int(row.get("run_count") or 0),
        "generated_at_utc": row.get("generated_at_utc"),
        "matched_candles": matched,
        "direction_accuracy_pct": direction_accuracy,
    }


def _promotion_decision(
    *,
    model_ready: bool,
    metrics: dict[str, Any],
    min_accuracy: float,
    min_matched: int,
    previous_promoted_accuracy: float | None,
) -> tuple[str, str]:
    """
    Pre-flight check before formal candidate evaluation.

    This function must NEVER return 'approved'.  Final approval requires
    running evaluate_promotion(model_version_id) in model_registry, which
    uses candidate-specific shadow evaluations and walk-forward results.
    Using incumbent live-metric thresholds here as an approval gate is a
    confound: incumbent performance says nothing about the new candidate.
    """
    if not model_ready:
        return "not_ready", "model_artifacts_missing"
    matched = int(metrics.get("matched_candles") or 0)
    accuracy = metrics.get("direction_accuracy_pct")
    if matched < min_matched:
        return "pending_review", f"matched_candles_below_threshold ({matched}/{min_matched})"
    if accuracy is None:
        return "pending_evaluation", "candidate_ready_for_evaluation"
    # Even when live metrics look good, we still only flag pending_evaluation.
    # The caller must invoke evaluate_promotion() to formally approve.
    return "pending_evaluation", "candidate_ready_for_evaluation"


def _run_cycle(args: argparse.Namespace, output_dir: Path, status_path: Path) -> None:
    now_utc = pd.Timestamp.now(tz="UTC").isoformat()
    model_dir = Path(args.model_dir)
    dataset_path = output_dir / f"kronos_auto_finetune_{args.symbol}_{args.resolution}.csv"

    previous = _read_status(status_path)
    previous_rows = int(previous.get("last_trained_rows") or 0)
    previous_promoted_accuracy = previous.get("promoted_direction_accuracy_pct")
    try:
        previous_promoted_accuracy = None if previous_promoted_accuracy is None else float(previous_promoted_accuracy)
    except (TypeError, ValueError):
        previous_promoted_accuracy = None

    df = _load_finetune_dataset(
        symbol=args.symbol,
        resolution=args.resolution,
        price_side=args.price_side,
        limit=max(args.limit, args.min_rows),
        dsn=args.postgres_dsn,
    )
    row_count = len(df)
    source_counts = _dataset_source_counts(df)
    websocket_rows = int(source_counts.get("websocket_ohlc", 0))
    historical_rows = max(0, row_count - websocket_rows)
    newest_ts = None if df.empty else df["timestamps"].iloc[-1].isoformat()
    training_dataset_id = previous.get("training_dataset_id")
    evaluation_dataset_id = previous.get("evaluation_dataset_id")
    if not df.empty:
        try:
            # Split dataset: oldest 80% for training, newest 20% for validation holdout.
            # Using the same snapshot for both training and evaluation would leak
            # in-sample data into the promotion decision.
            split_idx = max(1, int(len(df) * 0.8))
            train_df = df.iloc[:split_idx]
            eval_df = df.iloc[split_idx:]
            if not train_df.empty:
                train_snap = create_dataset_snapshot(
                    dataset_role="train",
                    symbol=args.symbol,
                    resolution=args.resolution,
                    price_side=args.price_side,
                    start_timestamp_utc=train_df["timestamps"].iloc[0].isoformat(),
                    end_timestamp_utc=train_df["timestamps"].iloc[-1].isoformat(),
                    feature_set_id="raw-ohlcv-v1",
                    source_filter={},
                    quality_filter={},
                    dsn=args.postgres_dsn,
                )
                training_dataset_id = train_snap["dataset_id"]
            if not eval_df.empty:
                eval_snap = create_dataset_snapshot(
                    dataset_role="validation",
                    symbol=args.symbol,
                    resolution=args.resolution,
                    price_side=args.price_side,
                    start_timestamp_utc=eval_df["timestamps"].iloc[0].isoformat(),
                    end_timestamp_utc=eval_df["timestamps"].iloc[-1].isoformat(),
                    feature_set_id="raw-ohlcv-v1",
                    source_filter={},
                    quality_filter={},
                    dsn=args.postgres_dsn,
                )
                evaluation_dataset_id = eval_snap["dataset_id"]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Unable to register auto-finetune dataset snapshot: %s", exc)
    websocket_df = df[df["source"] == "websocket_ohlc"] if "source" in df.columns else pd.DataFrame()
    newest_websocket_ts = None if websocket_df.empty else websocket_df["timestamps"].iloc[-1].isoformat()
    model_is_ready = _model_ready(model_dir)
    metrics = _latest_live_metrics(symbol=args.symbol, resolution=args.resolution, dsn=args.postgres_dsn)
    promotion_status, promotion_reason = _promotion_decision(
        model_ready=model_is_ready,
        metrics=metrics,
        min_accuracy=args.promotion_min_direction_accuracy,
        min_matched=args.promotion_min_matched_candles,
        previous_promoted_accuracy=previous_promoted_accuracy,
    )

    status: dict[str, Any] = {
        "enabled": True,
        "symbol": args.symbol,
        "resolution": args.resolution,
        "price_side": args.price_side,
        "last_checked_utc": now_utc,
        "dataset_rows": row_count,
        "required_dataset_rows": int(args.min_rows),
        "min_rows": int(args.min_rows),
        "dataset_source_counts": source_counts,
        "websocket_rows": websocket_rows,
        "historical_rows": historical_rows,
        "promotion_progress_pct": _promotion_progress_pct(row_count, int(args.min_rows)),
        "auto_finetune_interval_minutes": int(args.poll_minutes),
        "latest_dataset_timestamp_utc": newest_ts,
        "latest_websocket_timestamp_utc": newest_websocket_ts,
        "active_model_path": str(model_dir) if model_is_ready else None,
        "active_model_ready": model_is_ready,
        "training_dataset_id": training_dataset_id,
        "evaluation_dataset_id": evaluation_dataset_id,
        "candidate_model_version_id": None,
        "finetune_command_configured": bool(args.command),
        "promotion_status": promotion_status,
        "promotion_reason": promotion_reason,
        "promotion_min_direction_accuracy": float(args.promotion_min_direction_accuracy),
        "promotion_min_matched_candles": int(args.promotion_min_matched_candles),
        "promoted_direction_accuracy_pct": previous_promoted_accuracy,
        "latest_live_metrics": metrics,
    }
    if model_is_ready:
        try:
            registered = register_model_version(
                model_name="Kronos-auto-finetuned",
                model_path=str(model_dir),
                symbol=args.symbol,
                resolution=args.resolution,
                lookback=int(args.limit),
                pred_len=int(os.getenv("SIGNAL_PRED_LEN", "12")),
                training_dataset_id=training_dataset_id,
                validation_dataset_id=evaluation_dataset_id,
                # Never auto-approve: final promotion requires evaluate_promotion()
                # which uses candidate-specific shadow and walk-forward evidence.
                promotion_status="pending_evaluation",
                promotion_reason=promotion_reason,
                approval_metrics={"latest_live_metrics": metrics},
                dsn=args.postgres_dsn,
            )
            status["candidate_model_version_id"] = registered["model_version_id"]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Unable to register candidate model version: %s", exc)

    if row_count < args.min_rows:
        status.update(
            {
                "action": "skip",
                "reason": f"not_enough_dataset_rows ({row_count}/{args.min_rows})",
            }
        )
        _write_status(status_path, status)
        return

    if not args.command:
        status.update(
            {
                "action": "skip",
                "reason": "no_finetune_command_configured",
                "hint": "Set KRONOS_FINETUNE_COMMAND with placeholders {dataset} and {model_dir}.",
            }
        )
        _write_status(status_path, status)
        return

    if "{dataset}" not in args.command or "{model_dir}" not in args.command:
        status.update(
            {
                "action": "skip",
                "reason": "invalid_finetune_command_template",
                "hint": "KRONOS_FINETUNE_COMMAND must include {dataset} and {model_dir} placeholders.",
            }
        )
        _write_status(status_path, status)
        return

    if (row_count - previous_rows) < args.min_new_rows and model_is_ready:
        status.update(
            {
                "action": "skip",
                "reason": f"new_rows_below_threshold ({row_count - previous_rows}/{args.min_new_rows})",
                "last_trained_rows": previous_rows,
            }
        )
        _write_status(status_path, status)
        return

    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    training_df = df[TRAINING_COLUMNS].copy()
    training_df.to_csv(dataset_path, index=False)
    rendered = args.command.format(
        dataset=str(dataset_path),
        model_dir=str(model_dir),
        symbol=args.symbol,
        resolution=args.resolution,
    )
    started_utc = pd.Timestamp.now(tz="UTC").isoformat()
    result = subprocess.run(rendered, shell=True, text=True, capture_output=True)
    finished_utc = pd.Timestamp.now(tz="UTC").isoformat()

    model_is_ready = _model_ready(model_dir)
    metrics = _latest_live_metrics(symbol=args.symbol, resolution=args.resolution, dsn=args.postgres_dsn)
    promotion_status, promotion_reason = _promotion_decision(
        model_ready=model_is_ready,
        metrics=metrics,
        min_accuracy=args.promotion_min_direction_accuracy,
        min_matched=args.promotion_min_matched_candles,
        previous_promoted_accuracy=previous_promoted_accuracy,
    )
    promoted_direction_accuracy = previous_promoted_accuracy
    # No longer elevate promoted_direction_accuracy from incumbent metrics here;
    # approval must come through evaluate_promotion() in model_registry.
    output_tail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[-4000:]
    status.update(
        {
            "action": "train",
            "command": rendered,
            "dataset_path": str(dataset_path),
            "dataset_window_utc": {
                "start": df["timestamps"].iloc[0].isoformat(),
                "end": df["timestamps"].iloc[-1].isoformat(),
            },
            "started_at_utc": started_utc,
            "finished_at_utc": finished_utc,
            "exit_code": int(result.returncode),
            "last_output_tail": output_tail,
            "active_model_path": str(model_dir) if model_is_ready else None,
            "active_model_ready": model_is_ready,
            "promotion_status": promotion_status,
            "promotion_reason": promotion_reason,
            "promoted_direction_accuracy_pct": promoted_direction_accuracy,
            "latest_live_metrics": metrics,
            "last_trained_rows": row_count if result.returncode == 0 else previous_rows,
            "reason": "ok" if result.returncode == 0 else "finetune_command_failed",
        }
    )
    _write_status(status_path, status)


def _sleep_with_heartbeat(
    *,
    total_seconds: int,
    heartbeat_status: str,
    heartbeat_details: dict[str, Any],
    dsn: str | None,
    heartbeat_interval_seconds: int = 60,
    sleep_func=time.sleep,
) -> None:
    remaining = max(0, int(total_seconds))
    interval = max(1, int(heartbeat_interval_seconds))
    while remaining > 0:
        chunk = min(interval, remaining)
        sleep_func(chunk)
        remaining -= chunk
        if remaining <= 0:
            break
        details = dict(heartbeat_details)
        details.update(
            {
                "state": "sleeping",
                "seconds_until_next_cycle": remaining,
                "checked_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        )
        _heartbeat(heartbeat_status, details, dsn)


def main() -> None:
    configure_logging(service_name="auto_finetune_worker")
    args = parse_args()
    settings = load_settings(args.env)
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = Path(args.status_file)

    while True:
        heartbeat_status = "OK"
        heartbeat_details: dict[str, Any] = {
            "checked_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "symbol": args.symbol,
            "resolution": args.resolution,
        }
        try:
            _run_cycle(args, output_dir, status_path)
            latest = _read_status(status_path)
            heartbeat_details.update(
                {
                    "action": latest.get("action"),
                    "reason": latest.get("reason"),
                    "dataset_rows": latest.get("dataset_rows"),
                    "required_dataset_rows": latest.get("required_dataset_rows"),
                    "promotion_progress_pct": latest.get("promotion_progress_pct"),
                    "promotion_status": latest.get("promotion_status"),
                }
            )
            LOGGER.info(
                "Auto-finetune cycle complete: action=%s reason=%s promotion=%s",
                latest.get("action"),
                latest.get("reason"),
                latest.get("promotion_status"),
            )
        except Exception as exc:  # noqa: BLE001
            heartbeat_status = "ERROR"
            heartbeat_details["error"] = str(exc)
            LOGGER.exception("Auto-finetune worker cycle crashed")
        _heartbeat(heartbeat_status, heartbeat_details, args.postgres_dsn)
        if args.once:
            return
        _sleep_with_heartbeat(
            total_seconds=max(1, args.poll_minutes) * 60,
            heartbeat_status=heartbeat_status,
            heartbeat_details=heartbeat_details,
            dsn=args.postgres_dsn,
        )


if __name__ == "__main__":
    main()
