from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from db import connect, healthcheck
from prediction_store import prediction_summary


ALLOWED_SIGNAL_STATUSES = {"PENDING", "WIN", "LOSS"}
ALLOWED_RUN_STATUSES = {"PENDING", "PARTIAL", "VALIDATED", "ERROR"}
ALLOWED_SIGNALS = {"LONG", "SHORT", "HOLD"}
DISPLAY_TIMEZONE = "Asia/Amman"
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _looks_like_date_only(value: str | None) -> bool:
    return bool(value and _DATE_ONLY_RE.match(str(value).strip()))


def _normalized_upper(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _seconds_since(timestamp_value: Any) -> int | None:
    if timestamp_value is None:
        return None
    try:
        ts = timestamp_value
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
        return max(0, int(diff.total_seconds()))
    except Exception:  # noqa: BLE001
        return None


def _effective_signal_status(row: dict[str, Any]) -> str:
    wins = _to_int(row.get("outcomes_wins"))
    losses = _to_int(row.get("outcomes_losses"))
    status = str(row.get("status") or "PENDING").upper()
    if wins + losses > 0:
        return "WIN" if wins >= losses else "LOSS"
    return status


def _enrich_signal_levels(row: dict[str, Any]) -> dict[str, Any]:
    entry = _to_float(row.get("entry_price"))
    if entry is None:
        entry = _to_float(row.get("last_input_close"))
    signal = str(row.get("signal") or "HOLD").upper()
    expected_move_pct = abs(_to_float(row.get("expected_move_pct")) or 0.0)
    cost_threshold_pct = _to_float(row.get("cost_threshold_pct")) or 0.05
    tp = _to_float(row.get("tp_price"))
    sl = _to_float(row.get("sl_price"))
    if entry is not None and (tp is None or sl is None):
        move_pct = max(expected_move_pct, cost_threshold_pct)
        projected_move = entry * (move_pct / 100.0)
        risk_move = projected_move / 1.5
        if signal == "LONG":
            tp = entry + projected_move
            sl = entry - risk_move
        elif signal == "SHORT":
            tp = entry - projected_move
            sl = entry + risk_move
        else:
            tp = entry
            sl = entry
    row["entry_price"] = entry
    row["tp_price"] = tp
    row["sl_price"] = sl
    row["status"] = _effective_signal_status(row)
    return row


def query_signals(
    *,
    symbol: str | None = None,
    resolution: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    signal_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    dsn: str | None = None,
) -> dict[str, Any]:
    page = max(int(page), 1)
    page_size = max(min(int(page_size), 200), 1)
    offset = (page - 1) * page_size

    normalized_resolution = _normalized_upper(resolution)
    normalized_direction = _normalized_upper(direction)
    normalized_status = _normalized_upper(status)
    where = ["1=1"]
    params: list[Any] = []
    effective_status_sql = """
        CASE
            WHEN COALESCE(o.outcomes_wins, 0) + COALESCE(o.outcomes_losses, 0) > 0
            THEN CASE
                WHEN COALESCE(o.outcomes_wins, 0) >= COALESCE(o.outcomes_losses, 0) THEN 'WIN'
                ELSE 'LOSS'
            END
            ELSE s.status
        END
    """

    if symbol:
        where.append("s.symbol = %s")
        params.append(symbol)
    if normalized_resolution:
        where.append("s.resolution = %s")
        params.append(normalized_resolution)
    if date_from:
        if _looks_like_date_only(date_from):
            where.append(f"(s.timestamp_utc AT TIME ZONE '{DISPLAY_TIMEZONE}')::date >= %s::date")
            params.append(date_from)
        else:
            where.append("s.timestamp_utc >= %s")
            params.append(date_from)
    if date_to:
        if _looks_like_date_only(date_to):
            where.append(f"(s.timestamp_utc AT TIME ZONE '{DISPLAY_TIMEZONE}')::date <= %s::date")
            params.append(date_to)
        else:
            where.append("s.timestamp_utc <= %s")
            params.append(date_to)
    if normalized_direction:
        if normalized_direction in ALLOWED_SIGNALS:
            where.append("s.signal = %s")
            params.append(normalized_direction)
        else:
            where.append("s.direction = %s")
            params.append(normalized_direction)
    if normalized_status and normalized_status in ALLOWED_SIGNAL_STATUSES:
        where.append(f"({effective_status_sql}) = %s")
        params.append(normalized_status)
    elif normalized_status and normalized_status in ALLOWED_RUN_STATUSES:
        where.append("r.run_status = %s")
        params.append(normalized_status)
    if signal_id:
        where.append("s.signal_id ILIKE %s")
        params.append(f"%{signal_id.strip()}%")

    where_sql = " AND ".join(where)
    base_from = """
        FROM signals s
        JOIN prediction_runs r ON r.run_id = s.run_id
        LEFT JOIN signal_shadow_predictions shp ON shp.active_run_id = s.run_id
        LEFT JOIN (
            SELECT
                run_id,
                COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS outcomes_wins,
                COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS outcomes_losses,
                COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS outcomes_pending
            FROM prediction_outcomes
            GROUP BY run_id
        ) o ON o.run_id = s.run_id
    """

    with connect(dsn) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*)::int AS total {base_from} WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT
                s.signal_id,
                s.run_id,
                s.symbol,
                s.epic,
                s.resolution,
                s.timestamp_utc,
                s.signal,
                s.direction,
                {effective_status_sql} AS status,
                s.status AS status_raw,
                s.confidence,
                s.expected_move_pct,
                s.cost_threshold_pct,
                s.entry_price,
                s.tp_price,
                s.sl_price,
                s.reason,
                r.last_input_close,
                r.forecast_start_timestamp_utc,
                r.forecast_end_timestamp_utc,
                r.run_status,
                shp.shadow_run_id,
                shp.model_name AS shadow_model_name,
                shp.model_path AS shadow_model_path,
                shp.signal AS shadow_signal,
                shp.direction AS shadow_direction,
                shp.confidence AS shadow_confidence,
                shp.expected_move_pct AS shadow_expected_move_pct,
                shp.entry_price AS shadow_entry_price,
                shp.tp_price AS shadow_tp_price,
                shp.sl_price AS shadow_sl_price,
                shp.reason AS shadow_reason,
                shp.generated_at_utc AS shadow_generated_at_utc,
                COALESCE(o.outcomes_wins, 0)::int AS outcomes_wins,
                COALESCE(o.outcomes_losses, 0)::int AS outcomes_losses,
                COALESCE(o.outcomes_pending, 0)::int AS outcomes_pending
            {base_from}
            WHERE {where_sql}
            ORDER BY s.timestamp_utc DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, offset),
        ).fetchall()

    total = int(total_row["total"] if total_row else 0)
    total_pages = max((total + page_size - 1) // page_size, 1)
    enriched = [_enrich_signal_levels(dict(row)) for row in rows]
    return {
        "rows": enriched,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


def latest_validation_metrics(*, symbol: str, resolution: str, dsn: str | None = None) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        row = conn.execute(
            """
            SELECT
                r.run_id,
                r.generated_at_utc,
                r.forecast_start_timestamp_utc,
                r.forecast_end_timestamp_utc,
                COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN o.status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending,
                AVG(ABS(o.close_error)) FILTER (WHERE o.status IN ('WIN', 'LOSS'))::double precision AS mae,
                SQRT(AVG((o.close_error * o.close_error)) FILTER (WHERE o.status IN ('WIN', 'LOSS')) )::double precision AS rmse,
                AVG(ABS(o.close_error_pct)) FILTER (WHERE o.status IN ('WIN', 'LOSS'))::double precision AS mape_pct,
                AVG(ABS(o.forecast_close - o.actual_close)) FILTER (WHERE o.status IN ('WIN', 'LOSS'))::double precision AS max_abs_close_move_pct
            FROM prediction_runs r
            LEFT JOIN prediction_outcomes o ON o.run_id = r.run_id
            WHERE r.symbol = %s AND r.resolution = %s
            GROUP BY r.run_id, r.generated_at_utc, r.forecast_start_timestamp_utc, r.forecast_end_timestamp_utc
            ORDER BY r.generated_at_utc DESC
            LIMIT 1
            """,
            (symbol, resolution),
        ).fetchone()
    if not row:
        return None
    wins = _to_int(row.get("wins"))
    losses = _to_int(row.get("losses"))
    matched = wins + losses
    direction_accuracy = None if matched == 0 else (wins / matched) * 100.0
    quality_status = "NEEDS_MORE_SAMPLES"
    mape = _to_float(row.get("mape_pct"))
    if matched >= 30 and direction_accuracy is not None and mape is not None:
        if direction_accuracy >= 60.0 and mape <= 0.25:
            quality_status = "PROMISING"
        elif direction_accuracy < 50.0:
            quality_status = "WEAK"
        else:
            quality_status = "NEEDS_MORE_SAMPLES"
    return {
        "run_id": row.get("run_id"),
        "generated_at_utc": row.get("generated_at_utc"),
        "forecast_start_timestamp_utc": row.get("forecast_start_timestamp_utc"),
        "forecast_end_timestamp_utc": row.get("forecast_end_timestamp_utc"),
        "wins": wins,
        "losses": losses,
        "pending": _to_int(row.get("pending")),
        "matched_candles": matched,
        "mae": _to_float(row.get("mae")),
        "rmse": _to_float(row.get("rmse")),
        "mape_pct": mape,
        "direction_accuracy_pct": direction_accuracy,
        "quality_status": quality_status,
        "source": "prediction_outcomes",
        "max_abs_close_move_pct": _to_float(row.get("max_abs_close_move_pct")),
    }


def postgres_dashboard_snapshot(*, symbol: str = "ETHUSD", resolution: str = "MINUTE_5", dsn: str | None = None) -> dict[str, Any]:
    health = healthcheck(dsn)
    if not health["ok"]:
        return {"postgres": health}
    with connect(dsn) as conn:
        candles = conn.execute(
            """
            SELECT timestamp_utc, open, high, low, close, volume
            FROM ohlcv_candles
            WHERE symbol = %s AND resolution = %s
            ORDER BY timestamp_utc DESC
            LIMIT 120
            """,
            (symbol, resolution),
        ).fetchall()
        signals = conn.execute(
            """
            WITH outcome_rollup AS (
                SELECT
                    run_id,
                    COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS outcomes_wins,
                    COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS outcomes_losses,
                    COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS outcomes_pending
                FROM prediction_outcomes
                GROUP BY run_id
            )
            SELECT
                s.signal_id,
                s.run_id,
                s.symbol,
                s.epic,
                s.resolution,
                s.timestamp_utc,
                s.signal,
                s.direction,
                CASE
                    WHEN COALESCE(o.outcomes_wins, 0) + COALESCE(o.outcomes_losses, 0) > 0
                    THEN CASE
                        WHEN COALESCE(o.outcomes_wins, 0) >= COALESCE(o.outcomes_losses, 0) THEN 'WIN'
                        ELSE 'LOSS'
                    END
                    ELSE s.status
                END AS status,
                s.status AS status_raw,
                s.confidence,
                s.expected_move_pct,
                s.cost_threshold_pct,
                s.entry_price,
                s.tp_price,
                s.sl_price,
                s.reason,
                r.last_input_close,
                r.forecast_start_timestamp_utc,
                r.forecast_end_timestamp_utc,
                r.run_status,
                shp.shadow_run_id,
                shp.model_name AS shadow_model_name,
                shp.model_path AS shadow_model_path,
                shp.signal AS shadow_signal,
                shp.direction AS shadow_direction,
                shp.confidence AS shadow_confidence,
                shp.expected_move_pct AS shadow_expected_move_pct,
                shp.entry_price AS shadow_entry_price,
                shp.tp_price AS shadow_tp_price,
                shp.sl_price AS shadow_sl_price,
                shp.reason AS shadow_reason,
                shp.generated_at_utc AS shadow_generated_at_utc,
                COALESCE(o.outcomes_wins, 0)::int AS outcomes_wins,
                COALESCE(o.outcomes_losses, 0)::int AS outcomes_losses,
                COALESCE(o.outcomes_pending, 0)::int AS outcomes_pending
            FROM signals s
            JOIN prediction_runs r ON r.run_id = s.run_id
            LEFT JOIN signal_shadow_predictions shp ON shp.active_run_id = s.run_id
            LEFT JOIN outcome_rollup o ON o.run_id = s.run_id
            WHERE s.symbol = %s AND s.resolution = %s
            ORDER BY s.timestamp_utc DESC
            LIMIT 20
            """,
            (symbol, resolution),
        ).fetchall()
        websocket_live_quote = conn.execute(
            """
            SELECT symbol, epic, NULL::text AS resolution, price, bid, ask, timestamp_utc, updated_at, source
            FROM live_quotes
            WHERE symbol = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        fallback_live_quote = conn.execute(
            """
            SELECT symbol, epic, resolution, close AS price, timestamp_utc, updated_at, source
            FROM ohlcv_candles
            WHERE symbol = %s
            ORDER BY
                CASE source
                    WHEN 'websocket_ohlc' THEN 1
                    WHEN 'latest_fetch' THEN 2
                    WHEN 'actual_validation' THEN 3
                    ELSE 4
                END,
                (resolution = 'MINUTE') DESC,
                timestamp_utc DESC,
                updated_at DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        websocket_candle_quote = conn.execute(
            """
            SELECT symbol, epic, resolution, close AS price, timestamp_utc, updated_at, source
            FROM ohlcv_candles
            WHERE symbol = %s AND source = 'websocket_ohlc'
            ORDER BY timestamp_utc DESC, updated_at DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        outcomes = conn.execute(
            """
            SELECT o.status, count(*)::int AS count
            FROM prediction_outcomes o
            JOIN prediction_runs r ON r.run_id = o.run_id
            WHERE r.symbol = %s AND r.resolution = %s
            GROUP BY o.status
            """,
            (symbol, resolution),
        ).fetchall()
        heartbeats = conn.execute(
            "SELECT service_name, status, details, updated_at FROM service_heartbeats ORDER BY service_name"
        ).fetchall()

    live_quote = websocket_live_quote or fallback_live_quote
    websocket_row = dict(websocket_live_quote or websocket_candle_quote) if (websocket_live_quote or websocket_candle_quote) else None
    websocket_ref = None
    if websocket_row:
        websocket_ref = websocket_row.get("updated_at") or websocket_row.get("timestamp_utc")
    websocket_stale_seconds = _seconds_since(websocket_ref)
    worker_statuses = {
        "prediction_scheduler": {"status": "MISSING", "details": {}, "updated_at": None},
        "validation_worker": {"status": "MISSING", "details": {}, "updated_at": None},
        "websocket_stream": {"status": "MISSING", "details": {}, "updated_at": None},
        "auto_finetune_worker": {"status": "MISSING", "details": {}, "updated_at": None},
        "maintenance_worker": {"status": "MISSING", "details": {}, "updated_at": None},
    }
    for row in heartbeats:
        worker_statuses[row["service_name"]] = {
            "status": row.get("status"),
            "details": row.get("details") or {},
            "updated_at": row.get("updated_at"),
        }
    for state in worker_statuses.values():
        stale_seconds = _seconds_since(state.get("updated_at"))
        stale_alert = stale_seconds is None or stale_seconds > 180
        state["stale_seconds"] = stale_seconds
        state["stale_alert"] = stale_alert
        status_text = str(state.get("status") or "").upper()
        if status_text == "OK" and stale_alert:
            state["status"] = "STALE"

    return {
        "postgres": health,
        "candles": [dict(row) for row in reversed(candles)],
        "signals": [_enrich_signal_levels(dict(row)) for row in signals],
        "live_quote": dict(live_quote) if live_quote else None,
        "live_health": {
            "websocket_quote": websocket_row,
            "websocket_last_update_utc": websocket_ref,
            "websocket_stale_seconds": websocket_stale_seconds,
            "websocket_stale_alert": websocket_stale_seconds is None or websocket_stale_seconds > 90,
            "alert_threshold_seconds": 90,
        },
        "latest_validation": latest_validation_metrics(symbol=symbol, resolution=resolution, dsn=dsn),
        "outcomes": [dict(row) for row in outcomes],
        "heartbeats": [dict(row) for row in heartbeats],
        "worker_statuses": worker_statuses,
        "prediction_db": prediction_summary(dsn, limit=20),
    }
