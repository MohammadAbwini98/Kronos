from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from candle_context import load_recent_candles, resolution_to_timedelta, validate_candle_frame
from config import configure_logging
from db import connect
from forecast_normalizer import normalize_forecast
from higher_timeframe_fetcher import ensure_higher_timeframe_candles
from higher_timeframe_validator import validate_higher_timeframes
from logging_utils import log_event, new_correlation_id
from signal_blockers import evaluate_hard_blockers
from signal_config import add_signal_cli_overrides, load_signal_config, signal_overrides_from_args
from signal_scoring import score_signal
from signal_validation_store import (
    load_latest_signal_validation,
    save_signal_validation_run,
    save_timeframe_validations,
    update_signal_validation_summary,
)
from technical_indicators import atr, volume_zscore


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and score external higher-timeframe context for a prediction run.")
    parser.add_argument("--run-id", default=None, help="Prediction run id.")
    parser.add_argument("--latest", action="store_true", help="Use latest prediction run for symbol/resolution.")
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", "ETHUSD"))
    parser.add_argument("--resolution", default=os.getenv("SIGNAL_RESOLUTION", "MINUTE_5"))
    parser.add_argument("--price-side", default=os.getenv("CAPITAL_DEFAULT_PRICE_SIDE", "mid"))
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    add_signal_cli_overrides(parser)
    args = parser.parse_args()
    args.resolution = str(args.resolution).strip().upper()
    return args


def _load_json(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}
    source = Path(path_value)
    if not source.exists():
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _find_run(
    *,
    run_id: str | None,
    latest: bool,
    symbol: str,
    resolution: str,
    dsn: str | None,
) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        if run_id:
            row = conn.execute(
                """
                SELECT *
                FROM prediction_runs
                WHERE run_id = %s
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

        if latest:
            row = conn.execute(
                """
                SELECT *
                FROM prediction_runs
                WHERE symbol = %s
                  AND resolution = %s
                ORDER BY generated_at_utc DESC
                LIMIT 1
                """,
                (symbol, resolution),
            ).fetchone()
            return dict(row) if row else None

    return None


def _load_forecast_frame(run: dict[str, Any], dsn: str | None) -> pd.DataFrame:
    run_id = str(run["run_id"])
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount
            FROM forecast_candles
            WHERE run_id = %s
            ORDER BY horizon_index ASC
            """,
            (run_id,),
        ).fetchall()

    frame = pd.DataFrame(rows, columns=["timestamps", "open", "high", "low", "close", "volume", "amount"])
    if frame.empty:
        csv_path = run.get("forecast_csv_path")
        if csv_path and Path(str(csv_path)).exists():
            frame = pd.read_csv(str(csv_path))

    if frame.empty:
        return frame

    frame["timestamps"] = pd.to_datetime(frame["timestamps"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["timestamps"]).sort_values("timestamps").reset_index(drop=True)
    return frame


def _load_input_frame(run: dict[str, Any], dsn: str | None, lookback: int) -> pd.DataFrame:
    csv_path = run.get("input_csv_path")
    if csv_path and Path(str(csv_path)).exists():
        df = pd.read_csv(str(csv_path))
        if "timestamps" in df.columns:
            df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True, errors="coerce")
        for column in ["open", "high", "low", "close", "volume", "amount"]:
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
        df = df.dropna(subset=["timestamps", "close"]).sort_values("timestamps")
        df = df.drop_duplicates(subset=["timestamps"], keep="last").reset_index(drop=True)
        if not df.empty:
            return df.tail(max(1, int(lookback))).reset_index(drop=True)

    return load_recent_candles(
        symbol=str(run.get("symbol") or "ETHUSD"),
        resolution=str(run.get("resolution") or "MINUTE_5"),
        price_side=str(run.get("price_side") or "mid"),
        limit=max(1, int(lookback)),
        dsn=dsn,
    )


def _closed_candles_only(
    frame: pd.DataFrame,
    *,
    resolution: str,
    now_utc: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    current = now_utc or pd.Timestamp.now(tz="UTC")
    try:
        delta = resolution_to_timedelta(resolution)
    except Exception:  # noqa: BLE001
        return frame
    cutoff = current - delta
    closed = frame.copy()
    closed["timestamps"] = pd.to_datetime(closed["timestamps"], utc=True, errors="coerce")
    closed = closed[closed["timestamps"] <= cutoff]
    if closed.empty:
        return frame
    return closed.reset_index(drop=True)


def _spread_pct(symbol: str, dsn: str | None) -> float | None:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                """
                SELECT bid, ask
                FROM live_quotes
                WHERE symbol = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        if not row:
            return None
        bid = row.get("bid")
        ask = row.get("ask")
        if bid is None or ask is None:
            return None
        bid_v = float(bid)
        ask_v = float(ask)
        if bid_v <= 0 or ask_v <= 0:
            return None
        mid = (bid_v + ask_v) / 2.0
        if mid == 0:
            return None
        return ((ask_v - bid_v) / mid) * 100.0
    except Exception:
        return None


def _market_context_from_primary(primary: pd.DataFrame, symbol: str, dsn: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "spread_pct": _spread_pct(symbol, dsn),
        "volume_zscore": None,
        "atr_percentile": None,
    }
    if primary.empty:
        return payload

    try:
        vol_z = volume_zscore(primary["volume"], period=20)
        if not vol_z.empty:
            value = vol_z.iloc[-1]
            payload["volume_zscore"] = None if pd.isna(value) else float(value)
    except Exception:
        payload["volume_zscore"] = None

    try:
        atr_series = atr(primary["high"], primary["low"], primary["close"], period=14)
        atr_pct = (atr_series / primary["close"].replace(0.0, pd.NA)) * 100.0
        atr_pct = atr_pct.dropna()
        if len(atr_pct.index) >= 10:
            latest = float(atr_pct.iloc[-1])
            percentile = float((atr_pct <= latest).mean() * 100.0)
            payload["atr_percentile"] = percentile
    except Exception:
        payload["atr_percentile"] = None

    return payload


def _build_validation_payload(
    *,
    run: dict[str, Any],
    normalized: dict[str, Any],
    scoring: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "run_id": run["run_id"],
        "symbol": run.get("symbol"),
        "epic": run.get("epic") or run.get("symbol"),
        "base_resolution": run.get("resolution"),
        "candidate_signal": scoring.get("candidate_signal") or normalized.get("candidate_signal"),
        "final_signal": scoring.get("final_signal"),
        "forecast_direction": normalized.get("forecast_direction"),
        "last_input_close": normalized.get("last_input_close"),
        "forecast_close": normalized.get("last_forecast_close"),
        "forecast_return_pct": normalized.get("forecast_return_pct"),
        "estimated_cost_pct": normalized.get("estimated_cost_pct"),
        "net_edge_pct": normalized.get("net_edge_pct"),
        "blocked": scoring.get("blocked", False),
        "block_reason": scoring.get("block_reason"),
        "confidence_level": scoring.get("confidence_level", "NONE"),
        "total_score": scoring.get("total_score", 0.0),
        "component_scores": scoring.get("component_scores") or {},
        "reason_codes": scoring.get("reason_codes") or [],
        "reason_details": scoring.get("reason_details") or [],
    }
    return payload


def validate_signal_context_for_run(
    *,
    run_id: str | None = None,
    latest: bool = False,
    symbol: str = "ETHUSD",
    resolution: str = "MINUTE_5",
    price_side: str = "mid",
    dsn: str | None = None,
    env_name: str = "demo",
    config_overrides: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    validation_request_id = request_id or new_correlation_id("sigval")
    if dsn:
        os.environ["POSTGRES_DSN"] = str(dsn)
    cfg = load_signal_config(overrides=config_overrides)

    log_event(
        LOGGER,
        logging.INFO,
        "signal_validation.start",
        validation_request_id=validation_request_id,
        run_id=run_id,
        latest=latest,
        symbol=symbol,
        resolution=resolution,
        validation_enabled=cfg.signal_validation_enabled,
        validation_strict=cfg.signal_validation_strict,
    )

    try:
        run = _find_run(
            run_id=run_id,
            latest=latest,
            symbol=symbol,
            resolution=resolution,
            dsn=dsn,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "operational_error": True,
            "error": f"Database query failed while loading run: {exc}",
            "run_id": run_id,
        }

    if run is None:
        return {
            "ok": False,
            "operational_error": True,
            "error": "Prediction run was not found.",
            "run_id": run_id,
        }

    run_id_value = str(run["run_id"])
    metadata = _load_json(run.get("metadata_path"))

    forecast_frame = _load_forecast_frame(run, dsn)
    if forecast_frame.empty:
        return {
            "ok": False,
            "operational_error": True,
            "error": "Forecast candles are missing for this run.",
            "run_id": run_id_value,
        }

    input_frame = _load_input_frame(run, dsn, lookback=cfg.signal_lookback)
    if input_frame.empty:
        return {
            "ok": False,
            "operational_error": True,
            "error": "Input candles are missing for this run.",
            "run_id": run_id_value,
        }

    input_frame = _closed_candles_only(
        input_frame,
        resolution=str(run.get("resolution") or resolution),
    )

    try:
        normalized = normalize_forecast(
            metadata=metadata,
            metadata_path=run.get("metadata_path"),
            forecast=forecast_frame,
            input_data=input_frame,
            validation_report=run.get("validation_report_path"),
            estimated_cost_pct=cfg.signal_cost_threshold_pct,
            flat_threshold_pct=cfg.signal_flat_threshold_pct,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "operational_error": True,
            "error": f"Forecast normalization failed: {exc}",
            "run_id": run_id_value,
        }

    fetch_status = ensure_higher_timeframe_candles(
        symbol=str(run.get("symbol") or symbol),
        epic=str(run.get("epic") or metadata.get("epic") or symbol),
        price_side=str(run.get("price_side") or price_side),
        required_timeframes=list(cfg.signal_validation_timeframes),
        min_rows_per_timeframe=max(80, min(240, int(cfg.signal_lookback // 2))),
        env_name=env_name,
        dsn=dsn,
    )

    primary_validation = validate_candle_frame(input_frame, str(run.get("resolution") or resolution))
    market_context = _market_context_from_primary(input_frame, str(run.get("symbol") or symbol), dsn)

    timeframe_results = validate_higher_timeframes(
        symbol=str(run.get("symbol") or symbol),
        candidate_signal=str(normalized.get("candidate_signal") or "HOLD"),
        timeframes=list(cfg.signal_validation_timeframes),
        price_side=str(run.get("price_side") or price_side),
        dsn=dsn,
        limit=max(120, cfg.signal_lookback),
    )

    blockers = evaluate_hard_blockers(
        normalized_forecast=normalized,
        primary_input_validation=primary_validation,
        context_fetch_status=fetch_status,
        timeframe_validations=timeframe_results,
        config=cfg,
        market_context=market_context,
        database_available=True,
    )

    scoring = score_signal(
        normalized_forecast=normalized,
        timeframe_validations=timeframe_results,
        blockers=blockers,
        config=cfg,
        market_context=market_context,
    )

    unavailable_codes = {
        "VALIDATION_DISABLED",
        "VALIDATION_UNAVAILABLE",
        "MISSING_HIGHER_TIMEFRAME_CONTEXT",
        "PROVISIONAL_HIGHER_TIMEFRAME_CONTEXT",
    }
    if scoring.get("blocked") and any(code in unavailable_codes for code in scoring.get("reason_codes") or []):
        scoring["final_signal"] = "VALIDATION_UNAVAILABLE"

    scoring["net_edge_pct"] = normalized.get("net_edge_pct")
    scoring["estimated_cost_pct"] = normalized.get("estimated_cost_pct")

    validation_payload = _build_validation_payload(run=run, normalized=normalized, scoring=scoring)

    save_result = save_signal_validation_run(validation_payload, dsn=dsn)
    timeframe_save = save_timeframe_validations(run_id_value, timeframe_results, dsn=dsn)

    update_signal_validation_summary(run_id_value, {**validation_payload, **scoring}, dsn=dsn)

    persistence_warning = None
    if not save_result.get("ok", False):
        persistence_warning = save_result

    output = {
        "ok": True,
        "run_id": run_id_value,
        "candidate_signal": scoring.get("candidate_signal"),
        "final_signal": scoring.get("final_signal"),
        "confidence_level": scoring.get("confidence_level"),
        "total_score": scoring.get("total_score"),
        "blocked": bool(scoring.get("blocked")),
        "block_reason": scoring.get("block_reason"),
        "component_scores": scoring.get("component_scores") or {},
        "reason_codes": scoring.get("reason_codes") or [],
        "reason_details": scoring.get("reason_details") or [],
        "net_edge_pct": normalized.get("net_edge_pct"),
        "estimated_cost_pct": normalized.get("estimated_cost_pct"),
        "timeframes": {
            item["timeframe"]: {
                "trend": item.get("trend"),
                "confirms_candidate": item.get("confirms_candidate"),
                "total_timeframe_score": item.get("total_timeframe_score"),
            }
            for item in timeframe_results
        },
        "timeframe_validations": timeframe_results,
        "fetch_status": fetch_status,
        "store_status": {
            "validation_run": save_result,
            "timeframes": timeframe_save,
        },
    }

    if persistence_warning and cfg.signal_validation_strict:
        return {
            "ok": False,
            "operational_error": True,
            "error": "Validation persistence failed in strict mode.",
            "run_id": run_id_value,
            "details": persistence_warning,
        }

    if persistence_warning:
        output["warning"] = persistence_warning
        output["final_signal"] = "VALIDATION_UNAVAILABLE"

    log_event(
        LOGGER,
        logging.INFO,
        "signal_validation.completed",
        validation_request_id=validation_request_id,
        run_id=run_id_value,
        final_signal=output.get("final_signal"),
        total_score=output.get("total_score"),
        blocked=output.get("blocked"),
        block_reason=output.get("block_reason"),
    )

    return output


def run_validation_for_run(
    run_id: str,
    *,
    dsn: str | None = None,
    env_name: str = "demo",
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_signal_context_for_run(
        run_id=run_id,
        latest=False,
        dsn=dsn,
        env_name=env_name,
        config_overrides=config_overrides,
    )


def main() -> None:
    configure_logging(service_name="validate_signal_context")
    args = parse_args()

    if not args.run_id and not args.latest:
        raise SystemExit("Provide --run-id or --latest.")

    overrides = signal_overrides_from_args(args)
    result = validate_signal_context_for_run(
        run_id=args.run_id,
        latest=bool(args.latest),
        symbol=args.symbol,
        resolution=args.resolution,
        price_side=args.price_side,
        dsn=args.postgres_dsn,
        env_name=args.env,
        config_overrides=overrides,
    )

    print(json.dumps(result, indent=2, default=str))

    if not result.get("ok") and result.get("operational_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
