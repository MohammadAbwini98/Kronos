from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
import time

import pandas as pd

from candle_context import resolution_to_timedelta
from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from data_quality import analyze_ohlcv_quality, grade_meets_minimum, persist_prediction_run_quality
from db import connect
from logging_utils import log_event, new_correlation_id, output_tail, safe_command_for_log
from prediction_input_quality import evaluate_strict_input_policy, resolve_feature_experiment
from prediction_store import (
    PREDICTION_COLUMNS,
    persist_prediction_input_rejection,
    run_id_from_metadata_path,
    save_shadow_prediction,
    upsert_instrument,
    upsert_ohlcv_df,
)
from subprocess_utils import run_logged_subprocess
from time_utils import format_local_timestamp


LOGGER = logging.getLogger(__name__)


SIGNAL_VALIDATION_LINE_RE = re.compile(
    r"SIGNAL_VALIDATION:run_id=(?P<run_id>[^,]+),final_signal=(?P<final_signal>[^,]+),"
    r"total_score=(?P<total_score>[^,]+),blocked=(?P<blocked>[^\s,]+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch latest Capital.com candles and generate a current/future Kronos forecast.")
    parser.add_argument("--market", default="ETHUSD")
    parser.add_argument("--epic", default=None)
    parser.add_argument("--resolution", default="MINUTE_5")
    parser.add_argument("--max", type=int, default=512, dest="max_points")
    parser.add_argument("--lookback", type=int, default=512)
    parser.add_argument("--pred-len", type=int, default=12)
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"])
    parser.add_argument("--env", default="demo", choices=["demo", "live"])
    parser.add_argument(
        "--feature-set",
        default="ohlcv_only",
        choices=[
            "auto",
            "ohlc",
            "ohlcv",
            "ohlcva",
            "ohlcv_only",
            "ohlcva_derived_amount",
            "ohlcv_with_regime_context",
            "multi_timeframe_validation_only",
        ],
    )
    parser.add_argument("--repair-ohlc", action="store_true", help="Repair forecast high/low if raw Kronos output violates OHLC envelope.")
    parser.add_argument("--kronos-python", default=sys.executable)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--disable-shadow-model", action="store_true", help="Skip candidate-model shadow prediction.")
    return parser.parse_args()


def _flag_enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _shadow_model_enabled() -> bool:
    shadow_value = os.getenv("ENABLE_SHADOW_MODEL")
    if shadow_value is not None:
        return shadow_value.strip().lower() in {"1", "true", "yes", "on"}
    auto_finetune_value = os.getenv("ENABLE_AUTO_FINETUNE")
    if auto_finetune_value is not None:
        return auto_finetune_value.strip().lower() in {"1", "true", "yes", "on"}
    return True


def _model_ready(path: Path) -> bool:
    return path.is_dir() and (path / "config.json").exists() and (path / "model.safetensors").exists()


def _shadow_candidate_model(output_dir: Path) -> dict[str, str] | None:
    status_path = output_dir / "auto_finetune_status.json"
    if not status_path.exists():
        return None
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    promotion_status = str(payload.get("promotion_status") or "").strip().lower()
    # Shadow runs during both "pending_review" (accumulating matches) and
    # "pending_evaluation" (model trained, awaiting evaluate_promotion()).
    # "not_ready" and "approved" do not run shadow.
    if promotion_status not in ("pending_review", "pending_evaluation"):
        return None
    candidate = payload.get("active_model_path")
    if not candidate:
        return None
    model_dir = Path(str(candidate))
    if not _model_ready(model_dir):
        return None
    return {
        "model_dir": str(model_dir),
        "model_version_id": payload.get("candidate_model_version_id") or payload.get("model_version_id") or model_dir.name,
    }


def _run_shadow_prediction(
    *,
    base_cmd: list[str],
    active_metadata: Path,
    output_dir: Path,
    model_dir: Path,
    shadow_model_version_id: str | None,
    dsn: str | None,
    prediction_request_id: str,
    resolution: str,
    symbol: str,
    epic: str,
) -> bool:
    active_run_id = run_id_from_metadata_path(active_metadata)
    stamp = active_metadata.stem.replace("forecast_metadata_", "", 1)
    shadow_forecast = output_dir / f"shadow_kronos_forecast_{stamp}.csv"
    shadow_metadata = output_dir / f"shadow_forecast_metadata_{stamp}.json"
    shadow_input = output_dir / f"shadow_kronos_input_{stamp}.csv"
    shadow_validation = output_dir / f"shadow_kronos_forecast_validation_{stamp}.json"
    cmd = [
        *base_cmd,
        "--model-dir",
        str(model_dir),
        "--model-name",
        "Kronos-auto-shadow",
        "--output",
        str(shadow_forecast),
        "--metadata-output",
        str(shadow_metadata),
        "--input-copy-output",
        str(shadow_input),
        "--validation-report",
        str(shadow_validation),
        "--no-save-prediction-db",
    ]
    log_event(
        LOGGER,
        logging.INFO,
        "forecast_latest.shadow.start",
        prediction_request_id=prediction_request_id,
        symbol=symbol,
        epic=epic,
        resolution=resolution,
        shadow_model_version_id=shadow_model_version_id,
        command=safe_command_for_log(cmd),
    )
    result = run_logged_subprocess(
        cmd,
        logger=LOGGER,
        event_prefix="forecast_latest.shadow.subprocess",
        cwd=Path.cwd(),
        context={
            "prediction_request_id": prediction_request_id,
            "symbol": symbol,
            "epic": epic,
            "resolution": resolution,
            "shadow_model_version_id": shadow_model_version_id,
        },
    )
    if result.returncode != 0:
        print(f"Shadow model prediction failed with exit code {result.returncode}.")
        log_event(
            LOGGER,
            logging.ERROR,
            "forecast_latest.shadow.completed",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            shadow_model_version_id=shadow_model_version_id,
            status="failed",
            subprocess_returncode=int(result.returncode),
            subprocess_output_tail=output_tail((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")),
        )
        return False
    save_shadow_prediction(
        active_run_id=active_run_id,
        metadata_path=shadow_metadata,
        dsn=dsn,
        shadow_model_version_id=shadow_model_version_id,
        prediction_request_id=prediction_request_id,
    )
    print(f"Shadow model signal recorded for active run {active_run_id}.")
    log_event(
        LOGGER,
        logging.INFO,
        "forecast_latest.shadow.completed",
        prediction_request_id=prediction_request_id,
        symbol=symbol,
        epic=epic,
        resolution=resolution,
        shadow_model_version_id=shadow_model_version_id,
        status="success",
        active_run_id=active_run_id,
    )
    return True


def _extract_signal_validation_summary(output_text: str) -> dict[str, object] | None:
    if not output_text:
        return None
    match = SIGNAL_VALIDATION_LINE_RE.search(output_text)
    if not match:
        return None

    total_score_raw = str(match.group("total_score")).strip()
    try:
        total_score = float(total_score_raw)
    except Exception:  # noqa: BLE001
        total_score = 0.0

    blocked_raw = str(match.group("blocked")).strip().lower()
    blocked = blocked_raw in {"1", "true", "yes", "on"}

    return {
        "run_id": str(match.group("run_id")).strip(),
        "final_signal": str(match.group("final_signal")).strip(),
        "total_score": total_score,
        "blocked": blocked,
    }


def _closed_candles_only(df: pd.DataFrame, resolution: str, now_utc: pd.Timestamp | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    current = now_utc or pd.Timestamp.now(tz="UTC")
    cutoff = current - resolution_to_timedelta(resolution)
    closed = df[df["timestamps"] <= cutoff].copy()
    if closed.empty:
        return df
    return closed.reset_index(drop=True)


def _latest_websocket_candle_timestamp(*, symbol: str, resolution: str, dsn: str | None) -> pd.Timestamp | None:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                """
                SELECT timestamp_utc
                FROM ohlcv_candles
                WHERE symbol = %s AND resolution = %s AND source = 'websocket_ohlc'
                ORDER BY timestamp_utc DESC, updated_at DESC
                LIMIT 1
                """,
                (symbol, resolution),
            ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row or row.get("timestamp_utc") is None:
        return None
    return pd.to_datetime(row["timestamp_utc"], utc=True)


def _complete_input_from_stored_candles(
    df: pd.DataFrame,
    *,
    symbol: str,
    epic: str,
    resolution: str,
    price_side: str,
    lookback: int,
    dsn: str | None,
) -> tuple[pd.DataFrame, int]:
    if df.empty or not dsn:
        return df, 0

    clean = df.copy()
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    if "source" not in clean.columns:
        clean["source"] = "latest_fetch"
    clean = clean.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    minutes = max(1, int(resolution_to_timedelta(resolution).total_seconds() // 60))
    expected = pd.date_range(
        start=clean["timestamps"].iloc[0],
        end=clean["timestamps"].iloc[-1],
        freq=f"{minutes}min",
    )
    existing = set(clean["timestamps"])
    missing = [timestamp for timestamp in expected if timestamp not in existing]
    if not missing:
        return clean.tail(int(lookback)).reset_index(drop=True), 0

    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount, source
            FROM ohlcv_candles
            WHERE symbol = %s
              AND epic = %s
              AND resolution = %s
              AND price_side = %s
              AND timestamp_utc >= %s
              AND timestamp_utc <= %s
            ORDER BY timestamp_utc
            """,
            (symbol, epic, resolution, price_side, missing[0].isoformat(), missing[-1].isoformat()),
        ).fetchall()

    stored = pd.DataFrame(rows)
    if stored.empty:
        return clean.tail(int(lookback)).reset_index(drop=True), 0
    stored["timestamps"] = pd.to_datetime(stored["timestamps"], utc=True)
    if "source" not in stored.columns:
        stored["source"] = "stored_gap_fill"
    else:
        stored["source"] = stored["source"].fillna("stored_gap_fill")
    stored = stored[stored["timestamps"].isin(missing)]
    if stored.empty:
        return clean.tail(int(lookback)).reset_index(drop=True), 0
    combined = pd.concat([stored, clean], ignore_index=True)
    combined["timestamps"] = pd.to_datetime(combined["timestamps"], utc=True)
    combined = combined.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return combined.tail(int(lookback)).reset_index(drop=True), int(len(stored))


def main() -> None:
    configure_logging(service_name="forecast_latest")
    args = parse_args()
    prediction_request_id = new_correlation_id("pred")
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "forecast_latest.start",
        prediction_request_id=prediction_request_id,
        market=args.market,
        symbol=args.symbol,
        resolution=args.resolution,
        price_side=args.price_side,
        env=args.env,
        max_points=args.max_points,
        lookback=args.lookback,
        pred_len=args.pred_len,
        output_dir=args.output_dir,
    )
    try:
        resolution = validate_resolution(args.resolution)
        price_side = validate_price_side(args.price_side)
        settings = load_settings(args.env)
        settings.output_dir = Path(args.output_dir)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.settings.loaded",
            prediction_request_id=prediction_request_id,
            env=settings.env,
            output_dir=str(settings.output_dir),
            resolution=resolution,
            price_side=price_side,
        )

        client = CapitalRestClient(settings)
        client.authenticate()
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.market.resolve.start",
            prediction_request_id=prediction_request_id,
            market=args.market,
            symbol=args.symbol,
            resolution=resolution,
            env=args.env,
        )
        selected = client.resolve_market(args.market, args.epic, streaming=False)
        epic = selected["epic"]
        symbol = args.symbol or args.market or epic
        market_name = selected.get("instrumentName") or ""
        input_path = settings.output_dir / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}.csv"
        client.save_market_details(epic)
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.market.resolved",
            prediction_request_id=prediction_request_id,
            market=args.market,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
        )

        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.prices.fetch.start",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            max_points=args.max_points,
        )
        df = client.get_historical_prices(
            epic=epic,
            resolution=resolution,
            max_points=args.max_points,
            price_side=price_side,
            save_outputs=True,
            min_rows=min(args.lookback, args.max_points, 50),
        )
        original_rows = len(df)
        df = _closed_candles_only(df, resolution)
        dropped_unclosed_rows = max(0, original_rows - len(df))
        if dropped_unclosed_rows:
            log_event(
                LOGGER,
                logging.INFO,
                "forecast_latest.prices.unclosed_dropped",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                dropped_rows=dropped_unclosed_rows,
            )
        if df.empty:
            raise SystemExit("No closed candles available after filtering in-progress data.")
        df, stored_gap_rows = _complete_input_from_stored_candles(
            df,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            lookback=args.lookback,
            dsn=args.postgres_dsn,
        )
        if stored_gap_rows:
            log_event(
                LOGGER,
                logging.INFO,
                "forecast_latest.input.completed_from_stored_candles",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                stored_gap_rows=stored_gap_rows,
                rows=len(df),
                window_start=str(df["timestamps"].iloc[0]) if not df.empty else None,
                window_end=str(df["timestamps"].iloc[-1]) if not df.empty else None,
            )
        feature_selection = resolve_feature_experiment(df, args.feature_set)
        df = feature_selection.dataframe
        # Keep the model input artifact aligned with what is validated and stored.
        df.to_csv(input_path, index=False)
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.prices.fetch.completed",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            rows=len(df),
            window_start=str(df["timestamps"].iloc[0]) if not df.empty else None,
            window_end=str(df["timestamps"].iloc[-1]) if not df.empty else None,
        )

        data_quality = analyze_ohlcv_quality(
            df,
            resolution=resolution,
            expected_rows=args.lookback,
        )
        selected_feature_columns = feature_selection.feature_columns
        feature_mode = feature_selection.feature_mode
        websocket_terminal_ts = _latest_websocket_candle_timestamp(symbol=symbol, resolution=resolution, dsn=args.postgres_dsn)
        rest_terminal_ts = pd.to_datetime(df["timestamps"].iloc[-1], utc=True)
        if websocket_terminal_ts is not None and websocket_terminal_ts != rest_terminal_ts:
            log_event(
                LOGGER,
                logging.WARNING,
                "forecast_latest.input.websocket_rest_timestamp_mismatch",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                rest_last_input_timestamp_utc=rest_terminal_ts.isoformat(),
                websocket_latest_candle_timestamp_utc=websocket_terminal_ts.isoformat(),
            )
        strict_decision = evaluate_strict_input_policy(
            df,
            resolution=resolution,
            requested_lookback=args.lookback,
            selected_feature_columns=selected_feature_columns,
            source_label="latest_fetch",
            symbol=symbol,
            price_side=price_side,
            allow_short_lookback=str(os.getenv("PREDICTION_ALLOW_SHORT_LOOKBACK", "")).strip().lower() in {"1", "true", "yes", "on"},
            max_stale_intervals=int(os.getenv("PREDICTION_MAX_STALE_INPUT_INTERVALS", "1")),
        )
        data_quality_dict = {
            **data_quality.to_dict(),
            **strict_decision.checks,
            "selected_feature_columns": selected_feature_columns,
            "feature_mode": feature_mode,
            "amount_derivation_method": feature_selection.amount_derivation_method,
            "regime_context_used": feature_selection.regime_context_used,
            "feature_experiment_notes": feature_selection.notes,
            "strict_policy_passed": strict_decision.allow,
            "strict_policy_rejection_reason": None if strict_decision.allow else strict_decision.reason,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.data_quality.completed",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            quality_grade=data_quality.quality_grade,
            expected_rows=args.lookback,
            feature_mode=feature_mode,
            amount_derivation_method=feature_selection.amount_derivation_method,
            regime_context_used=feature_selection.regime_context_used,
            strict_policy_passed=strict_decision.allow,
            strict_policy_rejection_reason=None if strict_decision.allow else strict_decision.reason,
        )
        if not strict_decision.allow:
            persist_prediction_input_rejection(
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                price_side=price_side,
                requested_lookback=args.lookback,
                actual_lookback=int(strict_decision.checks.get("actual_lookback") or len(df)),
                reason=strict_decision.reason,
                rejection_reasons=strict_decision.rejection_reasons,
                quality_snapshot=data_quality_dict,
                input_csv_path=input_path,
                dsn=args.postgres_dsn,
            )
            log_event(
                LOGGER,
                logging.ERROR,
                "forecast_latest.input_quality_rejected",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                rejection_reason=strict_decision.reason,
                rejection_reasons=strict_decision.rejection_reasons,
            )
            raise SystemExit(f"Prediction input rejected: {strict_decision.reason}")

        min_quality_grade = os.getenv("MIN_PREDICTION_QUALITY_GRADE")
        quality_action = os.getenv("PREDICTION_QUALITY_ACTION", "downgrade").strip().lower()
        if min_quality_grade and not grade_meets_minimum(data_quality.quality_grade, min_quality_grade):
            message = f"Prediction input quality {data_quality.quality_grade} is below minimum {min_quality_grade}."
            if quality_action == "block":
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "forecast_latest.error",
                    prediction_request_id=prediction_request_id,
                    symbol=symbol,
                    epic=epic,
                    resolution=resolution,
                    error=message,
                )
                raise SystemExit(message)
            print(f"WARNING: {message} Signal quality will be downgraded in metadata.")

        upsert_instrument(
            symbol=symbol,
            epic=epic,
            market_name=market_name,
            price_side=price_side,
            metadata=selected,
            dsn=args.postgres_dsn,
        )
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.db.instrument_upserted",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
        )

        stored_rows = upsert_ohlcv_df(
            df,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            source="latest_fetch",
            dsn=args.postgres_dsn,
        )
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.db.ohlcv_upserted",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            stored_rows=stored_rows,
        )

        last_input = df["timestamps"].iloc[-1]
        print("\nLatest input fetched")
        print(f"Epic: {epic}")
        print(f"Market: {market_name}")
        print(f"Rows: {len(df)}")
        print(f"PostgreSQL candles upserted: {stored_rows}")
        print(f"Last input candle: {format_local_timestamp(last_input)}")

        # Generate run_stamp here so we can construct artifact paths deterministically
        # instead of globbing for the lexicographic latest file after the subprocess.
        run_stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
        cmd = [
            args.kronos_python,
            str(Path("src") / "main_run_kronos_predict.py"),
            "--input",
            str(input_path),
            "--resolution",
            resolution,
            "--lookback",
            str(args.lookback),
            "--pred-len",
            str(args.pred_len),
            "--epic",
            epic,
            "--market-name",
            market_name,
            "--price-side",
            price_side,
            "--feature-set",
            args.feature_set,
            "--output-dir",
            str(settings.output_dir),
            "--postgres-dsn",
            args.postgres_dsn or "",
            "--run-stamp",
            run_stamp,
        ]
        if args.repair_ohlc:
            cmd.append("--repair-ohlc")

        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.kronos.subprocess.start",
            prediction_request_id=prediction_request_id,
            market=args.market,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            lookback=args.lookback,
            pred_len=args.pred_len,
            max_points=args.max_points,
            command=safe_command_for_log(cmd),
            input_path=str(input_path),
        )
        result = run_logged_subprocess(
            cmd,
            logger=LOGGER,
            event_prefix="forecast_latest.kronos.subprocess",
            cwd=Path.cwd(),
            context={
                "prediction_request_id": prediction_request_id,
                "market": args.market,
                "symbol": symbol,
                "epic": epic,
                "resolution": resolution,
                "price_side": price_side,
                "lookback": args.lookback,
                "pred_len": args.pred_len,
            },
        )
        if result.returncode != 0 and not args.repair_ohlc:
            print("\nRaw Kronos output failed validation. Retrying with --repair-ohlc.")
            log_event(
                LOGGER,
                logging.WARNING,
                "forecast_latest.kronos.retry_repair_ohlc",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                subprocess_returncode=int(result.returncode),
                subprocess_output_tail=output_tail((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")),
            )
            result = run_logged_subprocess(
                [*cmd, "--repair-ohlc"],
                logger=LOGGER,
                event_prefix="forecast_latest.kronos.subprocess",
                cwd=Path.cwd(),
                context={
                    "prediction_request_id": prediction_request_id,
                    "market": args.market,
                    "symbol": symbol,
                    "epic": epic,
                    "resolution": resolution,
                    "price_side": price_side,
                    "lookback": args.lookback,
                    "pred_len": args.pred_len,
                    "retry_mode": "repair_ohlc",
                },
            )
        log_event(
            LOGGER,
            logging.INFO if result.returncode == 0 else logging.ERROR,
            "forecast_latest.kronos.subprocess.completed",
            prediction_request_id=prediction_request_id,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            subprocess_returncode=int(result.returncode),
            subprocess_output_tail=output_tail((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")) if result.returncode != 0 else None,
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)

        kronos_output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        signal_validation_summary = _extract_signal_validation_summary(kronos_output)
        if signal_validation_summary:
            log_event(
                LOGGER,
                logging.INFO,
                "forecast_latest.signal_validation.parsed",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                validation_run_id=signal_validation_summary.get("run_id"),
                validation_final_signal=signal_validation_summary.get("final_signal"),
                validation_total_score=signal_validation_summary.get("total_score"),
                validation_blocked=signal_validation_summary.get("blocked"),
            )
            print(
                "Signal validation summary: "
                f"run_id={signal_validation_summary.get('run_id')} "
                f"final_signal={signal_validation_summary.get('final_signal')} "
                f"score={signal_validation_summary.get('total_score')} "
                f"blocked={signal_validation_summary.get('blocked')}"
            )

        latest_metadata = settings.output_dir / f"forecast_metadata_{safe_epic_for_filename(epic)}_{resolution}_{run_stamp}.json"
        metadata = json.loads(latest_metadata.read_text(encoding="utf-8"))
        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.metadata.loaded",
            prediction_request_id=prediction_request_id,
            metadata_path=str(latest_metadata),
            symbol=symbol,
            epic=epic,
            resolution=resolution,
        )
        metadata["data_quality"] = data_quality_dict
        metadata["input_quality_snapshot"] = data_quality_dict
        metadata["selected_feature_columns"] = selected_feature_columns
        metadata["input_feature_columns"] = selected_feature_columns
        metadata["feature_mode"] = feature_mode
        metadata["amount_mode"] = (
            "DERIVED"
            if feature_selection.amount_derivation_method
            else ("AVAILABLE" if data_quality_dict.get("amount_available") else "UNAVAILABLE")
        )
        metadata["amount_available"] = bool(data_quality_dict.get("amount_available"))
        metadata["volume_available"] = bool(data_quality_dict.get("volume_available"))
        metadata["input_missing_candle_count"] = data_quality_dict.get("missing_candle_count")
        metadata["input_largest_gap_minutes"] = data_quality_dict.get("largest_gap_minutes")
        metadata["input_gap_list"] = data_quality_dict.get("gap_list") or []
        metadata["input_source_counts"] = data_quality_dict.get("source_counts") or {}
        metadata["input_closed_candle_verified"] = bool(strict_decision.allow)
        metadata["forecast_timestamp_verified"] = metadata.get("forecast_timestamp_check_status") == "PASS" and not metadata.get("forecast_timestamp_mismatches")
        if min_quality_grade and not grade_meets_minimum(data_quality.quality_grade, min_quality_grade):
            metadata["data_quality"]["quality_gate_action"] = quality_action
            metadata["data_quality"]["minimum_grade"] = min_quality_grade
        latest_metadata.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        try:
            persist_prediction_run_quality(
                run_id_from_metadata_path(latest_metadata),
                data_quality_dict,
                dsn=args.postgres_dsn,
            )
            log_event(
                LOGGER,
                logging.INFO,
                "forecast_latest.data_quality.persisted",
                prediction_request_id=prediction_request_id,
                run_id=run_id_from_metadata_path(latest_metadata),
                symbol=symbol,
                resolution=resolution,
                quality_grade=data_quality.quality_grade,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: data quality report could not be persisted: {exc}")
            log_event(
                LOGGER,
                logging.WARNING,
                "forecast_latest.data_quality.persisted",
                prediction_request_id=prediction_request_id,
                run_id=run_id_from_metadata_path(latest_metadata),
                symbol=symbol,
                resolution=resolution,
                quality_grade=data_quality.quality_grade,
                error=str(exc),
            )

        shadow_model = None if args.disable_shadow_model else _shadow_candidate_model(settings.output_dir)
        if shadow_model is not None and _shadow_model_enabled():
            try:
                _run_shadow_prediction(
                    base_cmd=cmd,
                    active_metadata=latest_metadata,
                    output_dir=settings.output_dir,
                    model_dir=Path(shadow_model["model_dir"]),
                    shadow_model_version_id=shadow_model.get("model_version_id"),
                    dsn=args.postgres_dsn,
                    prediction_request_id=prediction_request_id,
                    resolution=resolution,
                    symbol=symbol,
                    epic=epic,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Shadow model prediction could not be recorded: {exc}")
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "forecast_latest.shadow.completed",
                    prediction_request_id=prediction_request_id,
                    symbol=symbol,
                    epic=epic,
                    resolution=resolution,
                    shadow_model_version_id=shadow_model.get("model_version_id"),
                    status="failed",
                    error=str(exc),
                )
        else:
            log_event(
                LOGGER,
                logging.INFO,
                "forecast_latest.shadow.skipped",
                prediction_request_id=prediction_request_id,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                reason="disabled_or_no_candidate",
            )

        log_event(
            LOGGER,
            logging.INFO,
            "forecast_latest.completed",
            prediction_request_id=prediction_request_id,
            market=args.market,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            max_points=args.max_points,
            lookback=args.lookback,
            pred_len=args.pred_len,
            output_dir=str(settings.output_dir),
            input_path=str(input_path),
            metadata_path=str(latest_metadata),
            stored_rows=stored_rows,
            quality_grade=data_quality.quality_grade,
            validation_final_signal=(signal_validation_summary or {}).get("final_signal"),
            validation_total_score=(signal_validation_summary or {}).get("total_score"),
            validation_blocked=(signal_validation_summary or {}).get("blocked"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        print("\nCurrent/future forecast ready")
        print(f"Forecast start: {metadata['forecast_start_timestamp']}")
        print(f"Forecast end: {metadata['forecast_end_timestamp']}")
        print(f"Forecast CSV: {metadata['forecast_csv_path']}")
        print(f"Metadata: {latest_metadata}")
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "forecast_latest.error",
            prediction_request_id=prediction_request_id,
            market=args.market,
            symbol=args.symbol,
            resolution=args.resolution,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
