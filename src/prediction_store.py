from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect, masked_postgres_dsn
from forecast_scoring import (
    DEFAULT_COST_THRESHOLD_PCT,
    DEFAULT_FLAT_THRESHOLD_PCT,
    DEFAULT_SCORING_VERSION,
    DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
    direction_from_prices,
    score_forecast_against_actuals,
    score_signal_quality,
    score_trade_signal_outcome,
    signal_status_from_counts,
)
from model_registry import associate_run_model_version, model_version_id_for_path, register_model_version
from logging_utils import log_event, new_correlation_id


LOGGER = logging.getLogger(__name__)


PREDICTION_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]
SOURCE_PRIORITY = {
    "historical": 0,
    "actual_validation": 1,
    "latest_fetch": 2,
    "websocket_ohlc": 3,
}
ACTIONABLE_VALIDATION_SIGNALS = {"LONG", "SHORT", "STRONG_LONG", "STRONG_SHORT", "WEAK_LONG", "WEAK_SHORT"}
NON_ACTIONABLE_VALIDATION_SIGNALS = {"BLOCKED", "HOLD", "WATCH", "VALIDATION_UNAVAILABLE"}


class PredictionStoreError(ValueError):
    """Raised when prediction persistence or validation cannot be completed."""


def _ensure_scoring_version(conn: Any, *, scoring_version: str = DEFAULT_SCORING_VERSION, flat_threshold_pct: float = DEFAULT_FLAT_THRESHOLD_PCT, cost_threshold_pct: float = DEFAULT_COST_THRESHOLD_PCT) -> None:
    conn.execute(
        """
        INSERT INTO forecast_scoring_versions(scoring_version, description, flat_threshold_pct, cost_threshold_pct)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(scoring_version) DO NOTHING
        """,
        (
            scoring_version,
            "Canonical close-direction and cost-aware signal scoring.",
            float(flat_threshold_pct),
            float(cost_threshold_pct),
        ),
    )


def _utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _to_utc_iso(value: Any) -> str:
    return pd.to_datetime(value, utc=True).isoformat()


def _safe_float(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    return float(value)


def _coerce_finite_float(
    value: Any,
    *,
    field: str,
    timestamp_utc: str,
    allow_null: bool = False,
) -> float:
    if pd.isna(value):
        if allow_null:
            return 0.0
        raise PredictionStoreError(f"Candle field {field!r} is null at {timestamp_utc}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PredictionStoreError(f"Candle field {field!r} is non-numeric at {timestamp_utc}: {value!r}") from exc
    if not math.isfinite(result):
        raise PredictionStoreError(f"Candle field {field!r} is non-finite at {timestamp_utc}: {value!r}")
    return result


def preferred_candle_source(existing: str | None, incoming: str | None) -> str:
    existing_value = existing or "historical"
    incoming_value = incoming or "historical"
    existing_rank = SOURCE_PRIORITY.get(existing_value, -1)
    incoming_rank = SOURCE_PRIORITY.get(incoming_value, -1)
    return incoming_value if incoming_rank >= existing_rank else existing_value


def _safe_symbol(metadata: dict[str, Any]) -> str:
    return str(metadata.get("symbol") or metadata.get("epic") or "ETHUSD")


def _as_validation_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validation_gated_trade_signal(signal_row: Any) -> tuple[str, str | None]:
    candidate = str((signal_row or {}).get("signal") or "HOLD").upper()
    validation_status = str((signal_row or {}).get("validation_status") or "").strip().upper()
    summary = _as_validation_summary((signal_row or {}).get("validation_summary"))
    final_signal = str(summary.get("final_signal") or validation_status).strip().upper()

    if final_signal in ACTIONABLE_VALIDATION_SIGNALS:
        if "LONG" in final_signal:
            return "LONG", final_signal
        if "SHORT" in final_signal:
            return "SHORT", final_signal
    if final_signal in NON_ACTIONABLE_VALIDATION_SIGNALS:
        return "HOLD", final_signal
    return candidate, None


def run_id_from_metadata_path(metadata_path: str | Path) -> str:
    return Path(metadata_path).stem.replace("forecast_metadata_", "")


def _load_ohlcv_csv(path: str | Path, label: str) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"{label} CSV does not exist: {source}")
    df = pd.read_csv(source)
    missing = [col for col in PREDICTION_COLUMNS if col not in df.columns]
    if missing:
        raise PredictionStoreError(f"{label} CSV missing columns: {', '.join(missing)}")
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    for col in PREDICTION_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[["open", "high", "low", "close"]].isna().any().any():
        raise PredictionStoreError(f"{label} CSV contains null OHLC values")
    return df


def upsert_instrument(
    *,
    symbol: str,
    epic: str,
    market_name: str = "",
    price_side: str = "mid",
    provider: str = "Capital.com",
    metadata: dict[str, Any] | None = None,
    dsn: str | None = None,
) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO market_instruments(provider, symbol, epic, market_name, price_side, metadata, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT(provider, symbol, epic, price_side) DO UPDATE SET
                market_name = EXCLUDED.market_name,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            """,
            (provider, symbol, epic, market_name, price_side, Jsonb(metadata or {})),
        )


def upsert_ohlcv_df(
    df: pd.DataFrame,
    *,
    symbol: str,
    epic: str,
    resolution: str,
    price_side: str,
    provider: str = "Capital.com",
    source: str = "historical",
    dsn: str | None = None,
) -> int:
    if df.empty:
        return 0
    clean = df.copy()
    required_columns = ["timestamps", "open", "high", "low", "close"]
    missing_required = [column for column in required_columns if column not in clean.columns]
    if missing_required:
        missing_list = ", ".join(missing_required)
        raise PredictionStoreError(f"OHLC DataFrame missing required columns: {missing_list}")
    if "volume" not in clean.columns:
        clean["volume"] = 0.0
    if "amount" not in clean.columns:
        clean["amount"] = 0.0
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    rows = []
    for _, row in clean.iterrows():
        timestamp_utc = _to_utc_iso(row["timestamps"])
        open_price = _coerce_finite_float(row["open"], field="open", timestamp_utc=timestamp_utc)
        high_price = _coerce_finite_float(row["high"], field="high", timestamp_utc=timestamp_utc)
        low_price = _coerce_finite_float(row["low"], field="low", timestamp_utc=timestamp_utc)
        close_price = _coerce_finite_float(row["close"], field="close", timestamp_utc=timestamp_utc)
        volume_value = _coerce_finite_float(row["volume"], field="volume", timestamp_utc=timestamp_utc, allow_null=True)
        amount_value = _coerce_finite_float(row["amount"], field="amount", timestamp_utc=timestamp_utc, allow_null=True)

        if high_price < max(open_price, close_price, low_price) or low_price > min(open_price, close_price, high_price):
            raise PredictionStoreError(
                "Invalid OHLC ordering at "
                f"{timestamp_utc}: open={open_price}, high={high_price}, low={low_price}, close={close_price}"
            )

        rows.append(
            (
                provider,
                symbol,
                epic,
                resolution,
                price_side,
                timestamp_utc,
                open_price,
                high_price,
                low_price,
                close_price,
                volume_value,
                amount_value,
                source,
                Jsonb({}),
            )
        )
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ohlcv_candles(
                    provider, symbol, epic, resolution, price_side, timestamp_utc,
                    open, high, low, close, volume, amount, source, raw_payload, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT(provider, symbol, epic, resolution, price_side, timestamp_utc) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    source = CASE
                        WHEN EXCLUDED.source = 'websocket_ohlc' OR ohlcv_candles.source = 'websocket_ohlc' THEN 'websocket_ohlc'
                        WHEN EXCLUDED.source = 'latest_fetch' OR ohlcv_candles.source = 'latest_fetch' THEN 'latest_fetch'
                        WHEN EXCLUDED.source = 'actual_validation' OR ohlcv_candles.source = 'actual_validation' THEN 'actual_validation'
                        ELSE EXCLUDED.source
                    END,
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = now()
                """,
                rows,
            )
    return len(rows)


def upsert_live_quote(
    *,
    symbol: str,
    epic: str,
    payload: dict[str, Any],
    provider: str = "Capital.com",
    source: str = "websocket_quote",
    dsn: str | None = None,
) -> dict[str, Any]:
    bid = payload.get("bid")
    ask = payload.get("ofr", payload.get("ask"))
    timestamp = payload.get("timestamp") or payload.get("t") or payload.get("utm")
    bid_value = None if bid is None else float(bid)
    ask_value = None if ask is None else float(ask)
    if bid_value is not None and ask_value is not None:
        price = (bid_value + ask_value) / 2.0
    elif bid_value is not None:
        price = bid_value
    elif ask_value is not None:
        price = ask_value
    else:
        raise PredictionStoreError("Live quote payload missing bid/ofr price")

    timestamp_utc = None
    if timestamp not in (None, ""):
        numeric = int(timestamp)
        unit = "ms" if abs(numeric) > 10_000_000_000 else "s"
        timestamp_utc = pd.to_datetime(numeric, unit=unit, utc=True).isoformat()

    with connect(dsn) as conn:
        row = conn.execute(
            """
            INSERT INTO live_quotes(
                provider, symbol, epic, bid, ask, mid, price, timestamp_utc, source, raw_payload, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT(provider, symbol, epic) DO UPDATE SET
                bid = EXCLUDED.bid,
                ask = EXCLUDED.ask,
                mid = EXCLUDED.mid,
                price = EXCLUDED.price,
                timestamp_utc = EXCLUDED.timestamp_utc,
                source = EXCLUDED.source,
                raw_payload = EXCLUDED.raw_payload,
                updated_at = now()
            RETURNING symbol, epic, bid, ask, mid, price, timestamp_utc, source, updated_at
            """,
            (
                provider,
                symbol,
                epic,
                bid_value,
                ask_value,
                (bid_value + ask_value) / 2.0 if bid_value is not None and ask_value is not None else None,
                price,
                timestamp_utc,
                source,
                Jsonb(payload),
            ),
        ).fetchone()
    return dict(row)


def insert_raw_market_event(
    *,
    symbol: str,
    epic: str,
    event_type: str,
    payload: dict[str, Any],
    event_timestamp_utc: str | None = None,
    provider: str = "Capital.com",
    dsn: str | None = None,
) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO raw_market_events(provider, symbol, epic, event_type, event_timestamp_utc, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (provider, symbol, epic, event_type, event_timestamp_utc, Jsonb(payload)),
        )


def load_recent_ohlcv(
    *,
    symbol: str,
    resolution: str,
    price_side: str = "mid",
    limit: int = 512,
    dsn: str | None = None,
) -> pd.DataFrame:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc AS timestamps, open, high, low, close, volume, amount
            FROM ohlcv_candles
            WHERE symbol = %s AND resolution = %s AND price_side = %s
            ORDER BY timestamp_utc DESC
            LIMIT %s
            """,
            (symbol, resolution, price_side, limit),
        ).fetchall()
    df = pd.DataFrame(rows, columns=PREDICTION_COLUMNS)
    if df.empty:
        return df
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    for col in PREDICTION_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("timestamps").reset_index(drop=True)


def _metadata_utc(metadata: dict[str, Any], local_key: str, utc_key: str) -> str:
    return _to_utc_iso(metadata.get(utc_key) or metadata[local_key])


def _load_recent_volatility_pct(input_csv_path: str | None) -> float | None:
    """Return rolling-12 close-return std-dev (in %) from the input candle CSV, or None."""
    if not input_csv_path:
        return None
    try:
        idf = pd.read_csv(input_csv_path)
        std = idf["close"].pct_change().rolling(12, min_periods=1).std().iloc[-1]
        return float(std) * 100.0 if pd.notna(std) else None
    except Exception:  # noqa: BLE001
        return None


def _signal_from_forecast(
    *,
    last_input_close: float,
    final_close: float,
    cost_threshold_pct: float,
    min_confidence: float,
    forecast_closes: list[float] | None = None,
    recent_volatility_pct: float | None = None,
) -> dict[str, Any]:
    """
    Horizon-aware, volatility-adjusted signal generation.

    Replaces the terminal-close heuristic with a multi-factor engine that
    considers the full forecast path direction consistency, volatility-normalised
    edge, and a blended confidence score.  The output schema is backward-compatible.

    Parameters
    ----------
    forecast_closes:
        All forecast close prices in horizon order.  When supplied, direction
        agreement is checked across every horizon step.  Defaults to
        [final_close] for backward-compat callers that do not pass the full path.
    recent_volatility_pct:
        Recent rolling close-return std-dev in percent (e.g. from 12-bar input
        window).  Used to normalise the expected edge so that a large move in a
        volatile regime is not over-scored.
    """
    closes = list(forecast_closes) if forecast_closes else [final_close]
    n = len(closes)

    # Terminal expected move (kept as primary metric for backward-compat schema)
    if last_input_close == 0:
        expected_move_pct = 0.0
    else:
        expected_move_pct = ((final_close / last_input_close) - 1.0) * 100.0

    direction = "UP" if expected_move_pct > 0 else ("DOWN" if expected_move_pct < 0 else "FLAT")
    magnitude = abs(expected_move_pct)

    # --- Direction agreement across all forecast horizons ---
    all_closes = [last_input_close] + closes
    steps = [all_closes[i + 1] - all_closes[i] for i in range(n)]
    if magnitude > 0:
        dominant_up = expected_move_pct > 0
        agreeing = sum(1 for s in steps if (s > 0) == dominant_up and s != 0)
    else:
        agreeing = 0
    direction_agreement = agreeing / n if n > 0 else 0.0

    # --- Volatility-normalised edge ---
    # vol_floor prevents noise-dominated signals when the market is very quiet.
    vol_floor = max(
        recent_volatility_pct if (recent_volatility_pct and recent_volatility_pct > 0) else 0.0,
        cost_threshold_pct * 2.0,
        0.001,
    )
    vol_adjusted_edge = magnitude / vol_floor  # > 1.0 means move is larger than noise floor

    # --- Blended confidence score (three components, 0–1 final) ---
    # Component 1: edge multiples of cost threshold (0–50 pts)
    edge_pts = min(50.0, (magnitude / max(cost_threshold_pct * 4.0, 1e-9)) * 50.0)
    # Component 2: cross-horizon direction agreement (0–30 pts)
    agree_pts = direction_agreement * 30.0
    # Component 3: volatility-normalised edge bonus (0–20 pts)
    vol_pts = min(20.0, max(0.0, (vol_adjusted_edge - 1.0) * 10.0))
    confidence = round(min(0.99, max(0.0, (edge_pts + agree_pts + vol_pts) / 100.0)), 4)

    # --- HOLD conditions ---
    if magnitude < cost_threshold_pct:
        return {
            "signal": "HOLD",
            "direction": direction,
            "confidence": confidence,
            "expected_move_pct": expected_move_pct,
            "reason": "Expected movement is below configured cost threshold.",
        }

    if n > 1 and direction_agreement < 0.5:
        return {
            "signal": "HOLD",
            "direction": direction,
            "confidence": confidence,
            "expected_move_pct": expected_move_pct,
            "reason": (
                f"Horizon direction disagrees "
                f"({direction_agreement:.0%} agreement across {n} horizons)."
            ),
        }

    if confidence < min_confidence:
        return {
            "signal": "HOLD",
            "direction": direction,
            "confidence": confidence,
            "expected_move_pct": expected_move_pct,
            "reason": "Confidence is below configured minimum.",
        }

    return {
        "signal": "LONG" if expected_move_pct > 0 else "SHORT",
        "direction": direction,
        "confidence": confidence,
        "expected_move_pct": expected_move_pct,
        "reason": (
            f"Forecast cleared cost ({magnitude:.3f}%), "
            f"direction ({direction_agreement:.0%} agreement across {n} horizons), "
            "and confidence thresholds."
        ),
    }


def _trade_levels_from_signal(*, entry_price: float, signal: dict[str, Any], cost_threshold_pct: float) -> dict[str, float]:
    base_move_pct = max(abs(float(signal["expected_move_pct"])), cost_threshold_pct)
    projected_move = entry_price * (base_move_pct / 100.0)
    risk_move = projected_move / 1.5
    kind = str(signal["signal"])
    if kind == "LONG":
        return {
            "entry_price": entry_price,
            "tp_price": entry_price + projected_move,
            "sl_price": entry_price - risk_move,
        }
    if kind == "SHORT":
        return {
            "entry_price": entry_price,
            "tp_price": entry_price - projected_move,
            "sl_price": entry_price + risk_move,
        }
    return {
        "entry_price": entry_price,
        "tp_price": entry_price,
        "sl_price": entry_price,
    }


def save_prediction_run(
    metadata_path: str | Path,
    *,
    db_path: str | Path | None = None,
    dsn: str | None = None,
    flat_threshold_pct: float = 0.02,
    cost_threshold_pct: float = 0.05,
    min_confidence: float = 0.55,
    prediction_request_id: str | None = None,
) -> dict[str, Any]:
    if db_path is not None and dsn is None:
        dsn = str(db_path)
    request_id = prediction_request_id or new_correlation_id("pred")
    started = time.perf_counter()
    metadata_source = Path(metadata_path)
    run_id = run_id_from_metadata_path(metadata_source)
    log_event(
        LOGGER,
        logging.INFO,
        "prediction_store.save_prediction_run.start",
        prediction_request_id=request_id,
        run_id=run_id,
        metadata_path=str(metadata_source),
        dsn=masked_postgres_dsn(dsn),
        flat_threshold_pct=flat_threshold_pct,
        cost_threshold_pct=cost_threshold_pct,
        min_confidence=min_confidence,
    )
    try:
        metadata = json.loads(metadata_source.read_text(encoding="utf-8"))
        forecast = _load_ohlcv_csv(metadata["forecast_csv_path"], "forecast")
        symbol = _safe_symbol(metadata)
        epic = str(metadata["epic"])
        price_side = str(metadata.get("price_side", "mid"))
        provider = str(metadata.get("source_provider", "Capital.com"))
        last_input_close = float(metadata["last_input_close"])
        final_close = float(forecast["close"].iloc[-1])
        signal = _signal_from_forecast(
            last_input_close=last_input_close,
            final_close=final_close,
            cost_threshold_pct=cost_threshold_pct,
            min_confidence=min_confidence,
            forecast_closes=list(forecast["close"]),
            recent_volatility_pct=_load_recent_volatility_pct(metadata.get("input_csv_path")),
        )
        data_quality = metadata.get("data_quality") or {}
        data_quality_grade = data_quality.get("quality_grade")
        model_name = str(metadata.get("model_name", "Kronos"))
        model_path = metadata.get("model_path") or ""
        tokenizer_path = metadata.get("tokenizer_path")
        model_version = register_model_version(
            model_version_id=metadata.get("model_version_id"),
            model_name=model_name,
            model_path=str(model_path or model_name),
            tokenizer_path=tokenizer_path,
            symbol=symbol,
            resolution=str(metadata["resolution"]),
            lookback=int(metadata.get("input_rows_used") or metadata.get("lookback") or 512),
            pred_len=int(metadata.get("forecast_rows") or 12),
            promotion_status="pending_review",
            dsn=dsn,
        )
        model_version_id = model_version["model_version_id"]
        trade_levels = _trade_levels_from_signal(entry_price=last_input_close, signal=signal, cost_threshold_pct=cost_threshold_pct)
        upsert_instrument(
            symbol=symbol,
            epic=epic,
            market_name=str(metadata.get("market_name", "")),
            price_side=price_side,
            provider=provider,
            metadata=metadata,
            dsn=dsn,
        )
        with connect(dsn) as conn:
            _ensure_scoring_version(conn, scoring_version=DEFAULT_SCORING_VERSION, flat_threshold_pct=flat_threshold_pct, cost_threshold_pct=cost_threshold_pct)
            conn.execute(
                """
                INSERT INTO prediction_runs(
                    run_id, provider, symbol, epic, market_name, resolution, price_side, source_provider,
                    model_name, model_path, tokenizer_path, generated_at_utc,
                    input_start_timestamp_utc, input_end_timestamp_utc,
                    forecast_start_timestamp_utc, forecast_end_timestamp_utc,
                    input_rows_used, forecast_rows, forecast_horizon_minutes, last_input_close,
                    metadata_path, input_csv_path, forecast_csv_path, validation_report_path,
                    scoring_version, data_quality_grade, model_version_id, run_status, updated_at
                )
                VALUES (
                    %(run_id)s, %(provider)s, %(symbol)s, %(epic)s, %(market_name)s, %(resolution)s, %(price_side)s, %(source_provider)s,
                    %(model_name)s, %(model_path)s, %(tokenizer_path)s, %(generated_at_utc)s,
                    %(input_start)s, %(input_end)s, %(forecast_start)s, %(forecast_end)s,
                    %(input_rows_used)s, %(forecast_rows)s, %(forecast_horizon_minutes)s, %(last_input_close)s,
                    %(metadata_path)s, %(input_csv_path)s, %(forecast_csv_path)s, %(validation_report_path)s,
                    %(scoring_version)s, %(data_quality_grade)s, %(model_version_id)s, 'PENDING', now()
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    forecast_rows = EXCLUDED.forecast_rows,
                    forecast_end_timestamp_utc = EXCLUDED.forecast_end_timestamp_utc,
                    last_input_close = EXCLUDED.last_input_close,
                    metadata_path = EXCLUDED.metadata_path,
                    input_csv_path = EXCLUDED.input_csv_path,
                    forecast_csv_path = EXCLUDED.forecast_csv_path,
                    validation_report_path = EXCLUDED.validation_report_path,
                    scoring_version = EXCLUDED.scoring_version,
                    data_quality_grade = EXCLUDED.data_quality_grade,
                    model_version_id = EXCLUDED.model_version_id,
                    updated_at = now()
                """,
                {
                    "run_id": run_id,
                    "provider": provider,
                    "symbol": symbol,
                    "epic": epic,
                    "market_name": metadata.get("market_name", ""),
                    "resolution": metadata["resolution"],
                    "price_side": price_side,
                    "source_provider": provider,
                    "model_name": model_name,
                    "model_path": model_path,
                    "tokenizer_path": tokenizer_path,
                    "generated_at_utc": _to_utc_iso(metadata["generated_at_utc"]),
                    "input_start": _metadata_utc(metadata, "input_start_timestamp", "input_start_timestamp_utc"),
                    "input_end": _metadata_utc(metadata, "input_end_timestamp", "input_end_timestamp_utc"),
                    "forecast_start": _metadata_utc(metadata, "forecast_start_timestamp", "forecast_start_timestamp_utc"),
                    "forecast_end": _metadata_utc(metadata, "forecast_end_timestamp", "forecast_end_timestamp_utc"),
                    "input_rows_used": int(metadata["input_rows_used"]),
                    "forecast_rows": int(metadata["forecast_rows"]),
                    "forecast_horizon_minutes": int(metadata["forecast_horizon_minutes"]),
                    "last_input_close": last_input_close,
                    "metadata_path": str(metadata_source),
                    "input_csv_path": str(metadata.get("input_csv_path") or ""),
                    "forecast_csv_path": str(metadata.get("forecast_csv_path") or ""),
                    "validation_report_path": str(metadata.get("validation_report_path") or ""),
                    "scoring_version": DEFAULT_SCORING_VERSION,
                    "data_quality_grade": data_quality_grade,
                    "model_version_id": model_version_id,
                },
            )
            anchor_close = last_input_close
            saved = 0
            for index, row in forecast.iterrows():
                close = _safe_float(row["close"])
                inserted = conn.execute(
                    """
                    INSERT INTO forecast_candles(
                        run_id, horizon_index, timestamp_utc, open, high, low, close, volume, amount,
                        anchor_close, predicted_direction, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT(run_id, horizon_index) DO UPDATE SET
                        timestamp_utc = EXCLUDED.timestamp_utc,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        anchor_close = EXCLUDED.anchor_close,
                        predicted_direction = EXCLUDED.predicted_direction,
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        run_id,
                        int(index) + 1,
                        _to_utc_iso(row["timestamps"]),
                        _safe_float(row["open"]),
                        _safe_float(row["high"]),
                        _safe_float(row["low"]),
                        close,
                        _safe_float(row["volume"]),
                        _safe_float(row["amount"]),
                        anchor_close,
                        direction_from_prices(anchor_close, close, flat_threshold_pct),
                    ),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO prediction_outcomes(
                        run_id, forecast_candle_id, forecast_timestamp_utc, predicted_direction, forecast_close, status, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 'PENDING', now())
                    ON CONFLICT(run_id, forecast_candle_id) DO UPDATE SET
                        forecast_timestamp_utc = EXCLUDED.forecast_timestamp_utc,
                        predicted_direction = EXCLUDED.predicted_direction,
                        forecast_close = EXCLUDED.forecast_close,
                        updated_at = now()
                    """,
                    (
                        run_id,
                        inserted["id"],
                        _to_utc_iso(row["timestamps"]),
                        direction_from_prices(anchor_close, close, flat_threshold_pct),
                        close,
                    ),
                )
                anchor_close = close
                saved += 1
            conn.execute(
                """
                INSERT INTO signals(
                    run_id, signal_id, symbol, epic, resolution, timestamp_utc, signal, direction, confidence,
                    expected_move_pct, cost_threshold_pct, entry_price, tp_price, sl_price,
                    scoring_version, actionable, quality_grade, outcome_policy_version, status, reason, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, now())
                ON CONFLICT(run_id) DO UPDATE SET
                    signal_id = EXCLUDED.signal_id,
                    signal = EXCLUDED.signal,
                    direction = EXCLUDED.direction,
                    confidence = EXCLUDED.confidence,
                    expected_move_pct = EXCLUDED.expected_move_pct,
                    cost_threshold_pct = EXCLUDED.cost_threshold_pct,
                    entry_price = EXCLUDED.entry_price,
                    tp_price = EXCLUDED.tp_price,
                    sl_price = EXCLUDED.sl_price,
                    scoring_version = EXCLUDED.scoring_version,
                    actionable = EXCLUDED.actionable,
                    quality_grade = EXCLUDED.quality_grade,
                    outcome_policy_version = EXCLUDED.outcome_policy_version,
                    status = EXCLUDED.status,
                    reason = EXCLUDED.reason,
                    updated_at = now()
                """,
                (
                    run_id,
                    run_id,
                    symbol,
                    epic,
                    metadata["resolution"],
                    _to_utc_iso(metadata["generated_at_utc"]),
                    signal["signal"],
                    signal["direction"],
                    signal["confidence"],
                    signal["expected_move_pct"],
                    cost_threshold_pct,
                    trade_levels["entry_price"],
                    trade_levels["tp_price"],
                    trade_levels["sl_price"],
                    DEFAULT_SCORING_VERSION,
                    signal["signal"] in {"LONG", "SHORT"},
                    data_quality_grade,
                    DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                    signal["reason"],
                ),
            )
        associate_run_model_version(run_id=run_id, model_version_id=model_version_id, role="active", dsn=dsn)
        summary = {
            "dsn": masked_postgres_dsn(dsn),
            "run_id": run_id,
            "saved_records": saved,
            "signal": signal,
            "model_version_id": model_version_id,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "prediction_store.save_prediction_run.completed",
            prediction_request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            epic=epic,
            resolution=metadata.get("resolution"),
            saved_records=saved,
            signal=signal.get("signal"),
            direction=signal.get("direction"),
            confidence=signal.get("confidence"),
            expected_move_pct=signal.get("expected_move_pct"),
            model_version_id=model_version_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "prediction_store.save_prediction_run.error",
            prediction_request_id=request_id,
            run_id=run_id,
            metadata_path=str(metadata_source),
            dsn=masked_postgres_dsn(dsn),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def save_shadow_prediction(
    *,
    active_run_id: str,
    metadata_path: str | Path,
    dsn: str | None = None,
    cost_threshold_pct: float = 0.05,
    min_confidence: float = 0.55,
    shadow_model_version_id: str | None = None,
    prediction_request_id: str | None = None,
) -> dict[str, Any]:
    request_id = prediction_request_id or new_correlation_id("pred")
    started = time.perf_counter()
    metadata_source = Path(metadata_path)
    log_event(
        LOGGER,
        logging.INFO,
        "prediction_store.save_shadow_prediction.start",
        prediction_request_id=request_id,
        active_run_id=active_run_id,
        metadata_path=str(metadata_source),
        dsn=masked_postgres_dsn(dsn),
    )
    try:
        metadata = json.loads(metadata_source.read_text(encoding="utf-8"))
        forecast = _load_ohlcv_csv(metadata["forecast_csv_path"], "shadow forecast")
        last_input_close = float(metadata["last_input_close"])
        final_close = float(forecast["close"].iloc[-1])
        signal = _signal_from_forecast(
            last_input_close=last_input_close,
            final_close=final_close,
            cost_threshold_pct=cost_threshold_pct,
            min_confidence=min_confidence,
            forecast_closes=list(forecast["close"]),
            recent_volatility_pct=_load_recent_volatility_pct(metadata.get("input_csv_path")),
        )
        trade_levels = _trade_levels_from_signal(entry_price=last_input_close, signal=signal, cost_threshold_pct=cost_threshold_pct)
        shadow_run_id = metadata_source.stem
        model_name = str(metadata.get("model_name", "Kronos-shadow"))
        model_path = str(metadata.get("model_path") or model_name)
        registered = register_model_version(
            model_version_id=shadow_model_version_id or metadata.get("model_version_id"),
            model_name=model_name,
            model_path=model_path,
            tokenizer_path=metadata.get("tokenizer_path"),
            symbol=str(metadata.get("symbol") or metadata.get("epic") or "ETHUSD"),
            resolution=str(metadata.get("resolution") or "MINUTE_5"),
            lookback=int(metadata.get("input_rows_used") or 512),
            pred_len=int(metadata.get("forecast_rows") or 12),
            promotion_status="shadow",
            dsn=dsn,
        )
        shadow_model_version_id = registered["model_version_id"]
        with connect(dsn) as conn:
            _ensure_scoring_version(conn, scoring_version=DEFAULT_SCORING_VERSION, cost_threshold_pct=cost_threshold_pct)
            conn.execute(
                """
                INSERT INTO signal_shadow_predictions(
                    active_run_id, shadow_run_id, model_name, model_path, generated_at_utc,
                    signal, direction, confidence, expected_move_pct, cost_threshold_pct,
                    entry_price, tp_price, sl_price, reason, metadata_path, forecast_csv_path,
                    validation_report_path, shadow_model_version_id, scoring_version, outcome_policy_version, status, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', now())
                ON CONFLICT(active_run_id) DO UPDATE SET
                    shadow_run_id = EXCLUDED.shadow_run_id,
                    model_name = EXCLUDED.model_name,
                    model_path = EXCLUDED.model_path,
                    generated_at_utc = EXCLUDED.generated_at_utc,
                    signal = EXCLUDED.signal,
                    direction = EXCLUDED.direction,
                    confidence = EXCLUDED.confidence,
                    expected_move_pct = EXCLUDED.expected_move_pct,
                    cost_threshold_pct = EXCLUDED.cost_threshold_pct,
                    entry_price = EXCLUDED.entry_price,
                    tp_price = EXCLUDED.tp_price,
                    sl_price = EXCLUDED.sl_price,
                    reason = EXCLUDED.reason,
                    metadata_path = EXCLUDED.metadata_path,
                    forecast_csv_path = EXCLUDED.forecast_csv_path,
                    validation_report_path = EXCLUDED.validation_report_path,
                    shadow_model_version_id = EXCLUDED.shadow_model_version_id,
                    scoring_version = EXCLUDED.scoring_version,
                    outcome_policy_version = EXCLUDED.outcome_policy_version,
                    status = 'PENDING',
                    outcome_updated_at = NULL,
                    updated_at = now()
                """,
                (
                    active_run_id,
                    shadow_run_id,
                    str(metadata.get("model_name", "Kronos-shadow")),
                    metadata.get("model_path"),
                    _to_utc_iso(metadata["generated_at_utc"]),
                    signal["signal"],
                    signal["direction"],
                    signal["confidence"],
                    signal["expected_move_pct"],
                    cost_threshold_pct,
                    trade_levels["entry_price"],
                    trade_levels["tp_price"],
                    trade_levels["sl_price"],
                    signal["reason"],
                    str(metadata_source),
                    str(metadata.get("forecast_csv_path") or ""),
                    str(metadata.get("validation_report_path") or ""),
                    shadow_model_version_id,
                    DEFAULT_SCORING_VERSION,
                    DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                ),
            )
        summary = {
            "dsn": masked_postgres_dsn(dsn),
            "active_run_id": active_run_id,
            "shadow_run_id": shadow_run_id,
            "shadow_model_version_id": shadow_model_version_id,
            "signal": signal,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "prediction_store.save_shadow_prediction.completed",
            prediction_request_id=request_id,
            active_run_id=active_run_id,
            shadow_run_id=shadow_run_id,
            shadow_model_version_id=shadow_model_version_id,
            signal=signal.get("signal"),
            direction=signal.get("direction"),
            confidence=signal.get("confidence"),
            expected_move_pct=signal.get("expected_move_pct"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "prediction_store.save_shadow_prediction.error",
            prediction_request_id=request_id,
            active_run_id=active_run_id,
            metadata_path=str(metadata_source),
            dsn=masked_postgres_dsn(dsn),
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def _shadow_validation_summary(
    *,
    forecast_csv_path: str | Path,
    actual_by_ts: dict[str, pd.Series],
    last_input_close: float,
    flat_threshold_pct: float,
    signal: str | None = None,
    entry_price: float | None = None,
    tp_price: float | None = None,
    sl_price: float | None = None,
    cost_threshold_pct: float = DEFAULT_COST_THRESHOLD_PCT,
    forecast_end_timestamp_utc: Any | None = None,
) -> dict[str, Any]:
    forecast = _load_ohlcv_csv(forecast_csv_path, "shadow forecast")
    actual = pd.DataFrame(
        [
            {
                "timestamps": timestamp,
                "open": _safe_float(row.get("open", row["close"])),
                "high": _safe_float(row.get("high", row["close"])),
                "low": _safe_float(row.get("low", row["close"])),
                "close": _safe_float(row["close"]),
            }
            for timestamp, row in actual_by_ts.items()
        ],
        columns=["timestamps", "open", "high", "low", "close"],
    )
    score = score_forecast_against_actuals(
        forecast,
        actual,
        last_input_close=float(last_input_close),
        flat_threshold_pct=flat_threshold_pct,
    )
    summary = score["summary"]
    trade_outcome = None
    if signal is not None and entry_price is not None and tp_price is not None and sl_price is not None:
        trade_outcome = score_trade_signal_outcome(
            signal=signal,
            entry_price=float(entry_price),
            tp_price=float(tp_price),
            sl_price=float(sl_price),
            actual_df=actual,
            cost_threshold_pct=float(cost_threshold_pct),
            forecast_end_timestamp_utc=forecast_end_timestamp_utc,
        )
    status = (trade_outcome or {}).get("status") or summary["status"]
    return {
        "status": status,
        "wins": summary["wins"] if trade_outcome is None else (1 if status == "WIN" else 0),
        "losses": summary["losses"] if trade_outcome is None else (1 if status == "LOSS" else 0),
        "pending": summary["pending"],
        "validated": summary["validated"],
        "horizon_metrics": {
            "forecast_accuracy": score["rows"],
            "trade_outcome": trade_outcome,
        },
        "trade_outcome": trade_outcome,
    }


def _signal_status_for_primary_window(horizon_rows: list[dict[str, Any]]) -> str:
    if not horizon_rows:
        return "PENDING"
    first_row = min(horizon_rows, key=lambda row: int(row.get("horizon_index") or 10**9))
    status = str(first_row.get("status") or "PENDING").upper()
    if status in {"WIN", "LOSS"}:
        return status
    return "PENDING"


def _upsert_shadow_evaluation(conn: Any, *, active_run_id: str, shadow_summary: dict[str, Any]) -> None:
    row = conn.execute(
        """
        SELECT
            r.run_id,
            r.symbol,
            r.resolution,
            r.generated_at_utc,
            r.model_version_id AS active_model_version_id,
            r.data_quality_grade,
            s.signal AS active_signal,
            s.status AS active_status,
            shp.shadow_run_id,
            shp.shadow_model_version_id,
            shp.signal AS shadow_signal,
            shp.status AS shadow_status,
            shp.scoring_version,
            COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS active_wins,
            COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS active_losses
        FROM prediction_runs r
        JOIN signals s ON s.run_id = r.run_id
        JOIN signal_shadow_predictions shp ON shp.active_run_id = r.run_id
        LEFT JOIN prediction_outcomes o ON o.run_id = r.run_id
        WHERE r.run_id = %s
        GROUP BY r.run_id, s.signal, s.status, shp.shadow_run_id, shp.shadow_model_version_id,
                 shp.signal, shp.status, shp.scoring_version
        """,
        (active_run_id,),
    ).fetchone()
    if not row or not row.get("shadow_model_version_id"):
        return
    # Use persisted trade-signal statuses for active and shadow rows. Forecast
    # horizon win/loss counts remain in prediction_outcomes/forecast_horizon_metrics.
    active_status = str(row.get("active_status") or "PENDING")
    shadow_status = str(shadow_summary.get("status") or row.get("shadow_status") or "PENDING")
    disagreement = str(row.get("active_signal") or "") != str(row.get("shadow_signal") or "")
    conn.execute(
        """
        INSERT INTO shadow_evaluations(
            active_run_id, shadow_run_id, active_model_version_id, shadow_model_version_id,
            scoring_version, symbol, resolution, generated_at_utc, active_signal, active_status,
            shadow_signal, shadow_status, disagreement, active_wins, active_losses, shadow_wins,
            shadow_losses, comparable_horizons, horizon_metrics, data_quality_grade, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT(active_run_id, shadow_model_version_id, scoring_version) DO UPDATE SET
            active_status = EXCLUDED.active_status,
            shadow_status = EXCLUDED.shadow_status,
            disagreement = EXCLUDED.disagreement,
            active_wins = EXCLUDED.active_wins,
            active_losses = EXCLUDED.active_losses,
            shadow_wins = EXCLUDED.shadow_wins,
            shadow_losses = EXCLUDED.shadow_losses,
            comparable_horizons = EXCLUDED.comparable_horizons,
            horizon_metrics = EXCLUDED.horizon_metrics,
            data_quality_grade = EXCLUDED.data_quality_grade,
            updated_at = now()
        """,
        (
            active_run_id,
            row["shadow_run_id"],
            row.get("active_model_version_id"),
            row["shadow_model_version_id"],
            row.get("scoring_version") or DEFAULT_SCORING_VERSION,
            row["symbol"],
            row["resolution"],
            _to_utc_iso(row["generated_at_utc"]),
            row["active_signal"],
            active_status,
            row["shadow_signal"],
            shadow_status,
            disagreement,
            1 if active_status == "WIN" else 0,
            1 if active_status == "LOSS" else 0,
            int(shadow_summary.get("wins") or 0),
            int(shadow_summary.get("losses") or 0),
            int(shadow_summary.get("validated") or 0),
            Jsonb(shadow_summary.get("horizon_metrics") or {}),
            row.get("data_quality_grade"),
        ),
    )


def refresh_shadow_prediction_statuses(*, dsn: str | None = None, limit: int = 50) -> dict[str, Any]:
    checked = updated = pending = errors = 0
    with connect(dsn) as conn:
        shadows = conn.execute(
            """
            SELECT
                shp.active_run_id,
                shp.forecast_csv_path,
                r.symbol,
                r.epic,
                r.resolution,
                r.price_side,
                r.last_input_close,
                r.forecast_start_timestamp_utc,
                r.forecast_end_timestamp_utc,
                shp.signal,
                shp.entry_price,
                shp.tp_price,
                shp.sl_price,
                shp.cost_threshold_pct
            FROM signal_shadow_predictions shp
            JOIN prediction_runs r ON r.run_id = shp.active_run_id
            WHERE shp.status = 'PENDING'
              AND r.run_status IN ('PARTIAL', 'VALIDATED')
            ORDER BY shp.updated_at ASC
            LIMIT %s
            """,
            (max(1, int(limit)),),
        ).fetchall()
        for shadow in shadows:
            checked += 1
            try:
                actual_rows = conn.execute(
                    """
                    SELECT timestamp_utc AS timestamps, open, high, low, close
                    FROM ohlcv_candles
                    WHERE symbol = %s
                      AND epic = %s
                      AND resolution = %s
                      AND price_side = %s
                      AND timestamp_utc >= %s
                      AND timestamp_utc <= %s
                    ORDER BY timestamp_utc ASC
                    """,
                    (
                        shadow["symbol"],
                        shadow["epic"],
                        shadow["resolution"],
                        shadow["price_side"],
                        shadow["forecast_start_timestamp_utc"],
                        shadow["forecast_end_timestamp_utc"],
                    ),
                ).fetchall()
                actual_by_ts = {
                    _to_utc_iso(row["timestamps"]): pd.Series(
                        {
                            "open": row["open"],
                            "high": row["high"],
                            "low": row["low"],
                            "close": row["close"],
                        }
                    )
                    for row in actual_rows
                }
                summary = _shadow_validation_summary(
                    forecast_csv_path=shadow["forecast_csv_path"],
                    actual_by_ts=actual_by_ts,
                    last_input_close=float(shadow["last_input_close"]),
                    flat_threshold_pct=0.02,
                    signal=shadow["signal"],
                    entry_price=float(shadow["entry_price"]),
                    tp_price=float(shadow["tp_price"]),
                    sl_price=float(shadow["sl_price"]),
                    cost_threshold_pct=float(shadow["cost_threshold_pct"]),
                    forecast_end_timestamp_utc=shadow["forecast_end_timestamp_utc"],
                )
                if summary["status"] == "PENDING":
                    pending += 1
                    continue
                conn.execute(
                    """
                    UPDATE signal_shadow_predictions
                    SET status = %s,
                        disagreement = (signal <> (SELECT signal FROM signals WHERE signals.run_id = signal_shadow_predictions.active_run_id)),
                        horizon_metrics = %s,
                        outcome_policy_version = %s,
                        outcome_reason = %s,
                        outcome_hit_timestamp_utc = %s,
                        outcome_updated_at = now(),
                        updated_at = now()
                    WHERE active_run_id = %s
                    """,
                    (
                        summary["status"],
                        Jsonb(summary.get("horizon_metrics") or {}),
                        (summary.get("trade_outcome") or {}).get("policy_version") or DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                        (summary.get("trade_outcome") or {}).get("reason"),
                        (summary.get("trade_outcome") or {}).get("hit_timestamp_utc"),
                        shadow["active_run_id"],
                    ),
                )
                _upsert_shadow_evaluation(conn, active_run_id=shadow["active_run_id"], shadow_summary=summary)
                updated += 1
            except Exception:  # noqa: BLE001
                errors += 1
    return {
        "checked": checked,
        "updated": updated,
        "pending": pending,
        "errors": errors,
    }


def update_predictions_with_actuals(
    *,
    run_id: str | None = None,
    metadata_path: str | Path | None = None,
    actual_csv_path: str | Path,
    db_path: str | Path | None = None,
    dsn: str | None = None,
    flat_threshold_pct: float = 0.02,
    scoring_version: str = DEFAULT_SCORING_VERSION,
) -> dict[str, Any]:
    if db_path is not None and dsn is None:
        dsn = str(db_path)
    if run_id is None:
        if metadata_path is None:
            raise PredictionStoreError("Provide run_id or metadata_path")
        run_id = run_id_from_metadata_path(metadata_path)
    actual = _load_ohlcv_csv(actual_csv_path, "actual")
    actual_by_ts = {_to_utc_iso(row["timestamps"]): row for _, row in actual.iterrows()}
    wins = losses = pending = validated = 0
    with connect(dsn) as conn:
        _ensure_scoring_version(conn, scoring_version=scoring_version, flat_threshold_pct=flat_threshold_pct)
        run = conn.execute(
            """
            SELECT symbol, epic, resolution, price_side, provider, last_input_close,
                   forecast_end_timestamp_utc
            FROM prediction_runs
            WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
        if not run:
            raise PredictionStoreError(f"No prediction run found for run_id={run_id}")
        upsert_ohlcv_df(
            actual,
            symbol=run["symbol"],
            epic=run["epic"],
            resolution=run["resolution"],
            price_side=run["price_side"],
            provider=run["provider"],
            source="actual_validation",
            dsn=dsn,
        )
        records = conn.execute(
            """
            SELECT id, horizon_index, timestamp_utc, close, predicted_direction
            FROM forecast_candles
            WHERE run_id = %s
            ORDER BY horizon_index
            """,
            (run_id,),
        ).fetchall()
        total_records = len(records)
        forecast_for_score = pd.DataFrame(
            [
                {
                    "timestamps": record["timestamp_utc"],
                    "close": record["close"],
                }
                for record in records
            ],
            columns=["timestamps", "close"],
        )
        score = score_forecast_against_actuals(
            forecast_for_score,
            actual,
            last_input_close=float(run["last_input_close"]),
            flat_threshold_pct=flat_threshold_pct,
        )
        score_by_horizon = {row["horizon_index"]: row for row in score["rows"]}
        for record in records:
            score_row = score_by_horizon[int(record["horizon_index"])]
            ts = _to_utc_iso(record["timestamp_utc"])
            actual_row = actual_by_ts.get(ts)
            if actual_row is None:
                pending += 1
                conn.execute(
                    """
                    UPDATE prediction_outcomes
                    SET status = 'PENDING', updated_at = now()
                    WHERE run_id = %s AND forecast_candle_id = %s
                    """,
                    (run_id, record["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO forecast_horizon_metrics(
                        run_id, scoring_version, horizon_index, forecast_timestamp_utc,
                        predicted_direction, actual_direction, status, forecast_close, actual_close,
                        close_error, close_error_pct, abs_close_error, expected_move_pct,
                        realized_move_pct, movement_after_cost_pct, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NULL, 'PENDING', %s, NULL, NULL, NULL, NULL, %s, NULL, NULL, now())
                    ON CONFLICT(run_id, scoring_version, horizon_index) DO UPDATE SET
                        forecast_timestamp_utc = EXCLUDED.forecast_timestamp_utc,
                        predicted_direction = EXCLUDED.predicted_direction,
                        actual_direction = EXCLUDED.actual_direction,
                        status = EXCLUDED.status,
                        forecast_close = EXCLUDED.forecast_close,
                        actual_close = EXCLUDED.actual_close,
                        close_error = EXCLUDED.close_error,
                        close_error_pct = EXCLUDED.close_error_pct,
                        abs_close_error = EXCLUDED.abs_close_error,
                        expected_move_pct = EXCLUDED.expected_move_pct,
                        realized_move_pct = EXCLUDED.realized_move_pct,
                        movement_after_cost_pct = EXCLUDED.movement_after_cost_pct,
                        updated_at = now()
                    """,
                    (
                        run_id,
                        scoring_version,
                        int(record["horizon_index"]),
                        ts,
                        score_row["predicted_direction"] or "FLAT",
                        score_row["forecast_close"],
                        score_row["expected_move_pct"],
                    ),
                )
                continue
            actual_close = score_row["actual_close"]
            actual_direction = score_row["actual_direction"]
            status = score_row["status"]
            close_error = score_row["close_error"]
            close_error_pct = score_row["close_error_pct"]
            candle = conn.execute(
                """
                SELECT id FROM ohlcv_candles
                WHERE symbol = %s AND epic = %s AND resolution = %s AND price_side = %s AND timestamp_utc = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (run["symbol"], run["epic"], run["resolution"], run["price_side"], ts),
            ).fetchone()
            conn.execute(
                """
                UPDATE prediction_outcomes
                SET actual_candle_id = %s,
                    actual_timestamp_utc = %s,
                    predicted_direction = %s,
                    actual_direction = %s,
                    actual_close = %s,
                    close_error = %s,
                    close_error_pct = %s,
                    status = %s,
                    validated_at_utc = now(),
                    updated_at = now()
                WHERE run_id = %s AND forecast_candle_id = %s
                """,
                (
                    candle["id"] if candle else None,
                    ts,
                    score_row["predicted_direction"],
                    actual_direction,
                    actual_close,
                    close_error,
                    close_error_pct,
                    status,
                    run_id,
                    record["id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO forecast_horizon_metrics(
                    run_id, scoring_version, horizon_index, forecast_timestamp_utc,
                    predicted_direction, actual_direction, status, forecast_close, actual_close,
                    close_error, close_error_pct, abs_close_error, expected_move_pct,
                    realized_move_pct, movement_after_cost_pct, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT(run_id, scoring_version, horizon_index) DO UPDATE SET
                    forecast_timestamp_utc = EXCLUDED.forecast_timestamp_utc,
                    predicted_direction = EXCLUDED.predicted_direction,
                    actual_direction = EXCLUDED.actual_direction,
                    status = EXCLUDED.status,
                    forecast_close = EXCLUDED.forecast_close,
                    actual_close = EXCLUDED.actual_close,
                    close_error = EXCLUDED.close_error,
                    close_error_pct = EXCLUDED.close_error_pct,
                    abs_close_error = EXCLUDED.abs_close_error,
                    expected_move_pct = EXCLUDED.expected_move_pct,
                    realized_move_pct = EXCLUDED.realized_move_pct,
                    movement_after_cost_pct = EXCLUDED.movement_after_cost_pct,
                    updated_at = now()
                """,
                (
                    run_id,
                    scoring_version,
                    int(record["horizon_index"]),
                    ts,
                    score_row["predicted_direction"] or "FLAT",
                    actual_direction,
                    status,
                    score_row["forecast_close"],
                    actual_close,
                    close_error,
                    close_error_pct,
                    None if close_error is None else abs(float(close_error)),
                    score_row["expected_move_pct"],
                    score_row["realized_move_pct"],
                    score_row["movement_after_cost_pct"],
                ),
            )
            if status == "WIN":
                wins += 1
            else:
                losses += 1
            validated += 1
        if pending == total_records:
            run_status = "PENDING"
        elif pending == 0:
            run_status = "VALIDATED"
        else:
            run_status = "PARTIAL"
        conn.execute("UPDATE prediction_runs SET run_status = %s, updated_at = now() WHERE run_id = %s", (run_status, run_id))
        signal_row = conn.execute(
            """
             SELECT signal, confidence, expected_move_pct, cost_threshold_pct,
                 entry_price, tp_price, sl_price, validation_status, validation_summary
            FROM signals
            WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
        signal_quality = None
        trade_outcome = None
        signal_status = _signal_status_for_primary_window(score["rows"])
        if signal_row:
            trade_signal, validation_final_signal = _validation_gated_trade_signal(signal_row)
            candidate_signal = str(signal_row["signal"] or "HOLD").upper()
            entry_price = float(signal_row["entry_price"] or run["last_input_close"])
            if signal_row["tp_price"] is None or signal_row["sl_price"] is None:
                fallback_levels = _trade_levels_from_signal(
                    entry_price=entry_price,
                    signal={
                        "signal": trade_signal,
                        "expected_move_pct": float(signal_row["expected_move_pct"]),
                    },
                    cost_threshold_pct=float(signal_row["cost_threshold_pct"]),
                )
                tp_price = fallback_levels["tp_price"]
                sl_price = fallback_levels["sl_price"]
            else:
                tp_price = float(signal_row["tp_price"])
                sl_price = float(signal_row["sl_price"])
            trade_outcome = score_trade_signal_outcome(
                signal=trade_signal,
                entry_price=entry_price,
                tp_price=tp_price,
                sl_price=sl_price,
                actual_df=actual,
                cost_threshold_pct=float(signal_row["cost_threshold_pct"]),
                forecast_end_timestamp_utc=run["forecast_end_timestamp_utc"],
            )
            if trade_signal != candidate_signal:
                gate_reason = (
                    f"Validation final signal {validation_final_signal or 'UNSPECIFIED'} "
                    f"overrode candidate {candidate_signal} for outcome scoring."
                )
                prior_reason = str(trade_outcome.get("reason") or "").strip()
                trade_outcome["reason"] = f"{gate_reason} {prior_reason}".strip()
            signal_status = str(trade_outcome["status"])
            signal_quality = score_signal_quality(
                signal=trade_signal,
                confidence=float(signal_row["confidence"]),
                expected_move_pct=float(signal_row["expected_move_pct"]),
                cost_threshold_pct=float(signal_row["cost_threshold_pct"]),
                scoring_summary=score["summary"],
                trade_outcome=trade_outcome,
            )
            conn.execute(
                """
                INSERT INTO signal_quality_metrics(
                    run_id, scoring_version, signal, status, actionable, confidence,
                    expected_move_pct, realized_move_pct, cost_threshold_pct,
                    movement_after_cost_pct, precision_bucket, false_positive, hold_quality,
                    outcome_policy_version, outcome_reason, outcome_hit_timestamp_utc, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT(run_id) DO UPDATE SET
                    scoring_version = EXCLUDED.scoring_version,
                    signal = EXCLUDED.signal,
                    status = EXCLUDED.status,
                    actionable = EXCLUDED.actionable,
                    confidence = EXCLUDED.confidence,
                    expected_move_pct = EXCLUDED.expected_move_pct,
                    realized_move_pct = EXCLUDED.realized_move_pct,
                    cost_threshold_pct = EXCLUDED.cost_threshold_pct,
                    movement_after_cost_pct = EXCLUDED.movement_after_cost_pct,
                    precision_bucket = EXCLUDED.precision_bucket,
                    false_positive = EXCLUDED.false_positive,
                    hold_quality = EXCLUDED.hold_quality,
                    outcome_policy_version = EXCLUDED.outcome_policy_version,
                    outcome_reason = EXCLUDED.outcome_reason,
                    outcome_hit_timestamp_utc = EXCLUDED.outcome_hit_timestamp_utc,
                    updated_at = now()
                """,
                (
                    run_id,
                    scoring_version,
                    signal_quality["signal"],
                    signal_quality["status"],
                    signal_quality["actionable"],
                    signal_quality["confidence"],
                    signal_quality["expected_move_pct"],
                    signal_quality["realized_move_pct"],
                    signal_quality["cost_threshold_pct"],
                    signal_quality["movement_after_cost_pct"],
                    signal_quality["precision_bucket"],
                    signal_quality["false_positive"],
                    signal_quality["hold_quality"],
                    signal_quality["outcome_policy_version"] or DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                    signal_quality["outcome_reason"],
                    signal_quality["outcome_hit_timestamp_utc"],
                ),
            )
        movement_after_cost = None if signal_quality is None else signal_quality.get("movement_after_cost_pct")
        conn.execute(
            "UPDATE signals SET status = %s, outcome_updated_at = now(), updated_at = now() WHERE run_id = %s",
            (signal_status, run_id),
        )
        conn.execute(
            """
            UPDATE signals
            SET movement_after_cost_pct = %s,
                scoring_version = %s,
                outcome_policy_version = %s,
                outcome_reason = %s,
                outcome_hit_timestamp_utc = %s,
                actionable = %s,
                updated_at = now()
            WHERE run_id = %s
            """,
            (
                movement_after_cost,
                scoring_version,
                (trade_outcome or {}).get("policy_version") or DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                (trade_outcome or {}).get("reason"),
                (trade_outcome or {}).get("hit_timestamp_utc"),
                bool(signal_quality and signal_quality.get("actionable")),
                run_id,
            ),
        )
        shadow = conn.execute(
            """
            SELECT forecast_csv_path, signal, entry_price, tp_price, sl_price, cost_threshold_pct
            FROM signal_shadow_predictions
            WHERE active_run_id = %s
            """,
            (run_id,),
        ).fetchone()
        if shadow and shadow.get("forecast_csv_path"):
            try:
                shadow_summary = _shadow_validation_summary(
                    forecast_csv_path=shadow["forecast_csv_path"],
                    actual_by_ts=actual_by_ts,
                    last_input_close=float(run["last_input_close"]),
                    flat_threshold_pct=flat_threshold_pct,
                    signal=shadow["signal"],
                    entry_price=float(shadow["entry_price"]),
                    tp_price=float(shadow["tp_price"]),
                    sl_price=float(shadow["sl_price"]),
                    cost_threshold_pct=float(shadow["cost_threshold_pct"]),
                    forecast_end_timestamp_utc=run["forecast_end_timestamp_utc"],
                )
                conn.execute(
                    """
                    UPDATE signal_shadow_predictions
                    SET status = %s,
                        disagreement = (signal <> (SELECT signal FROM signals WHERE signals.run_id = signal_shadow_predictions.active_run_id)),
                        horizon_metrics = %s,
                        outcome_policy_version = %s,
                        outcome_reason = %s,
                        outcome_hit_timestamp_utc = %s,
                        outcome_updated_at = now(),
                        updated_at = now()
                    WHERE active_run_id = %s
                    """,
                    (
                        shadow_summary["status"],
                        Jsonb(shadow_summary.get("horizon_metrics") or {}),
                        (shadow_summary.get("trade_outcome") or {}).get("policy_version") or DEFAULT_SIGNAL_OUTCOME_POLICY_VERSION,
                        (shadow_summary.get("trade_outcome") or {}).get("reason"),
                        (shadow_summary.get("trade_outcome") or {}).get("hit_timestamp_utc"),
                        run_id,
                    ),
                )
                _upsert_shadow_evaluation(conn, active_run_id=run_id, shadow_summary=shadow_summary)
            except Exception:  # noqa: BLE001
                pass
    total = wins + losses
    return {
        "dsn": masked_postgres_dsn(dsn),
        "run_id": run_id,
        "validated_records": validated,
        "pending_records": pending,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": None if total == 0 else (wins / total) * 100.0,
        "run_status": run_status,
    }


def prediction_summary(dsn: str | None = None, limit: int = 20, db_path: str | Path | None = None) -> dict[str, Any]:
    if db_path is not None and dsn is None:
        dsn = str(db_path)
    with connect(dsn) as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*)::int AS total_records,
                COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending
            FROM prediction_outcomes
            """
        ).fetchone()
        runs = conn.execute(
            """
            SELECT
                r.run_id, r.symbol, r.epic, r.resolution, r.price_side, r.generated_at_utc,
                r.forecast_start_timestamp_utc, r.forecast_end_timestamp_utc, r.run_status,
                s.signal_id, s.signal, s.direction, s.status AS signal_status,
                s.confidence, s.expected_move_pct, s.entry_price, s.tp_price, s.sl_price,
                COUNT(o.id)::int AS records,
                COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN o.status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending
            FROM prediction_runs r
            LEFT JOIN prediction_outcomes o ON o.run_id = r.run_id
            LEFT JOIN signals s ON s.run_id = r.run_id
            GROUP BY r.run_id, s.signal_id, s.signal, s.direction, s.status, s.confidence, s.expected_move_pct, s.entry_price, s.tp_price, s.sl_price
            ORDER BY r.generated_at_utc DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    wins = int(totals["wins"])
    losses = int(totals["losses"])
    evaluated = wins + losses
    return {
        "dsn": masked_postgres_dsn(dsn),
        "total_records": int(totals["total_records"]),
        "wins": wins,
        "losses": losses,
        "pending": int(totals["pending"]),
        "win_rate_pct": None if evaluated == 0 else (wins / evaluated) * 100.0,
        "recent_runs": [dict(row) for row in runs],
    }
