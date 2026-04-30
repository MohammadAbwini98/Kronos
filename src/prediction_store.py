from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from db import connect, masked_postgres_dsn


PREDICTION_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


class PredictionStoreError(ValueError):
    """Raised when prediction persistence or validation cannot be completed."""


def _utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _to_utc_iso(value: Any) -> str:
    return pd.to_datetime(value, utc=True).isoformat()


def _safe_float(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_symbol(metadata: dict[str, Any]) -> str:
    return str(metadata.get("symbol") or metadata.get("epic") or "ETHUSD")


def run_id_from_metadata_path(metadata_path: str | Path) -> str:
    return Path(metadata_path).stem.replace("forecast_metadata_", "")


def direction_from_prices(anchor_close: float, close: float, flat_threshold_pct: float = 0.02) -> str:
    if anchor_close == 0:
        return "FLAT"
    move_pct = ((close / anchor_close) - 1.0) * 100.0
    if abs(move_pct) < flat_threshold_pct:
        return "FLAT"
    return "UP" if move_pct > 0 else "DOWN"


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
    clean["timestamps"] = pd.to_datetime(clean["timestamps"], utc=True)
    rows = []
    for _, row in clean.iterrows():
        rows.append(
            (
                provider,
                symbol,
                epic,
                resolution,
                price_side,
                _to_utc_iso(row["timestamps"]),
                _safe_float(row["open"]),
                _safe_float(row["high"]),
                _safe_float(row["low"]),
                _safe_float(row["close"]),
                _safe_float(row["volume"]),
                _safe_float(row["amount"]),
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
                    source = EXCLUDED.source,
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = now()
                """,
                rows,
            )
    return len(rows)


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


def _signal_from_forecast(
    *,
    last_input_close: float,
    final_close: float,
    cost_threshold_pct: float,
    min_confidence: float,
) -> dict[str, Any]:
    if last_input_close == 0:
        expected_move_pct = 0.0
    else:
        expected_move_pct = ((final_close / last_input_close) - 1.0) * 100.0
    direction = "UP" if expected_move_pct > 0 else ("DOWN" if expected_move_pct < 0 else "FLAT")
    magnitude = abs(expected_move_pct)
    confidence = min(0.99, max(0.0, magnitude / max(cost_threshold_pct * 4.0, 1e-9)))
    if magnitude < cost_threshold_pct:
        signal = "HOLD"
        reason = "Expected movement is below configured cost threshold."
    elif confidence < min_confidence:
        signal = "HOLD"
        reason = "Confidence is below configured minimum."
    else:
        signal = "LONG" if expected_move_pct > 0 else "SHORT"
        reason = "Forecast movement cleared cost and confidence thresholds."
    return {
        "signal": signal,
        "direction": direction,
        "confidence": confidence,
        "expected_move_pct": expected_move_pct,
        "reason": reason,
    }


def save_prediction_run(
    metadata_path: str | Path,
    *,
    db_path: str | Path | None = None,
    dsn: str | None = None,
    flat_threshold_pct: float = 0.02,
    cost_threshold_pct: float = 0.05,
    min_confidence: float = 0.55,
) -> dict[str, Any]:
    if db_path is not None and dsn is None:
        dsn = str(db_path)
    metadata_source = Path(metadata_path)
    metadata = json.loads(metadata_source.read_text(encoding="utf-8"))
    forecast = _load_ohlcv_csv(metadata["forecast_csv_path"], "forecast")
    run_id = run_id_from_metadata_path(metadata_source)
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
    )
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
        conn.execute(
            """
            INSERT INTO prediction_runs(
                run_id, provider, symbol, epic, market_name, resolution, price_side, source_provider,
                model_name, model_path, tokenizer_path, generated_at_utc,
                input_start_timestamp_utc, input_end_timestamp_utc,
                forecast_start_timestamp_utc, forecast_end_timestamp_utc,
                input_rows_used, forecast_rows, forecast_horizon_minutes, last_input_close,
                metadata_path, input_csv_path, forecast_csv_path, validation_report_path,
                run_status, updated_at
            )
            VALUES (
                %(run_id)s, %(provider)s, %(symbol)s, %(epic)s, %(market_name)s, %(resolution)s, %(price_side)s, %(source_provider)s,
                %(model_name)s, %(model_path)s, %(tokenizer_path)s, %(generated_at_utc)s,
                %(input_start)s, %(input_end)s, %(forecast_start)s, %(forecast_end)s,
                %(input_rows_used)s, %(forecast_rows)s, %(forecast_horizon_minutes)s, %(last_input_close)s,
                %(metadata_path)s, %(input_csv_path)s, %(forecast_csv_path)s, %(validation_report_path)s,
                'PENDING', now()
            )
            ON CONFLICT(run_id) DO UPDATE SET
                forecast_rows = EXCLUDED.forecast_rows,
                forecast_end_timestamp_utc = EXCLUDED.forecast_end_timestamp_utc,
                last_input_close = EXCLUDED.last_input_close,
                metadata_path = EXCLUDED.metadata_path,
                input_csv_path = EXCLUDED.input_csv_path,
                forecast_csv_path = EXCLUDED.forecast_csv_path,
                validation_report_path = EXCLUDED.validation_report_path,
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
                "model_name": metadata.get("model_name", "Kronos"),
                "model_path": metadata.get("model_path"),
                "tokenizer_path": metadata.get("tokenizer_path"),
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
                run_id, symbol, epic, resolution, timestamp_utc, signal, direction, confidence,
                expected_move_pct, cost_threshold_pct, reason, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT(run_id) DO UPDATE SET
                signal = EXCLUDED.signal,
                direction = EXCLUDED.direction,
                confidence = EXCLUDED.confidence,
                expected_move_pct = EXCLUDED.expected_move_pct,
                cost_threshold_pct = EXCLUDED.cost_threshold_pct,
                reason = EXCLUDED.reason,
                updated_at = now()
            """,
            (
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
                signal["reason"],
            ),
        )
    return {
        "dsn": masked_postgres_dsn(dsn),
        "run_id": run_id,
        "saved_records": saved,
        "signal": signal,
    }


def update_predictions_with_actuals(
    *,
    run_id: str | None = None,
    metadata_path: str | Path | None = None,
    actual_csv_path: str | Path,
    db_path: str | Path | None = None,
    dsn: str | None = None,
    flat_threshold_pct: float = 0.02,
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
        run = conn.execute(
            "SELECT symbol, epic, resolution, price_side, provider, last_input_close FROM prediction_runs WHERE run_id = %s",
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
        previous_actual_close = float(run["last_input_close"])
        for record in records:
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
                continue
            actual_close = _safe_float(actual_row["close"])
            actual_direction = direction_from_prices(previous_actual_close, actual_close, flat_threshold_pct)
            status = "WIN" if actual_direction == record["predicted_direction"] else "LOSS"
            close_error = float(record["close"]) - actual_close
            close_error_pct = None if actual_close == 0 else (close_error / actual_close) * 100.0
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
                    actual_direction,
                    actual_close,
                    close_error,
                    close_error_pct,
                    status,
                    run_id,
                    record["id"],
                ),
            )
            if status == "WIN":
                wins += 1
            else:
                losses += 1
            validated += 1
            previous_actual_close = actual_close
        run_status = "VALIDATED" if pending == 0 else "PARTIAL"
        conn.execute("UPDATE prediction_runs SET run_status = %s, updated_at = now() WHERE run_id = %s", (run_status, run_id))
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
                s.signal, s.confidence, s.expected_move_pct,
                COUNT(o.id)::int AS records,
                COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN o.status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending
            FROM prediction_runs r
            LEFT JOIN prediction_outcomes o ON o.run_id = r.run_id
            LEFT JOIN signals s ON s.run_id = r.run_id
            GROUP BY r.run_id, s.signal, s.confidence, s.expected_move_pct
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
