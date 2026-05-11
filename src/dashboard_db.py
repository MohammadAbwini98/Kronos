from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
import time
from typing import Any

from db import connect, healthcheck
from logging_utils import log_event, new_correlation_id
from rate_limit_state import list_rate_limit_states
from supervisor_lease import current_supervisor_lease
from prediction_store import prediction_summary
from time_utils import display_timezone_name


ALLOWED_SIGNAL_STATUSES = {"PENDING", "WIN", "LOSS", "EXPIRED", "GOOD_HOLD", "MISSED_MOVE", "AMBIGUOUS"}
ALLOWED_RUN_STATUSES = {"PENDING", "PARTIAL", "VALIDATED", "ERROR"}
ALLOWED_SIGNALS = {"LONG", "SHORT", "HOLD"}
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WEBSOCKET_STALE_THRESHOLD_SECONDS = max(30, int(os.getenv("SIGNAL_WEBSOCKET_STALE_SECONDS", "90")))
LOGGER = logging.getLogger(__name__)


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
    status = str(row.get("status") or row.get("status_raw") or "PENDING").upper()
    return status if status in ALLOWED_SIGNAL_STATUSES else "PENDING"


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
    page_size: int = 10,
    dsn: str | None = None,
) -> dict[str, Any]:
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    page = max(int(page), 1)
    page_size = max(min(int(page_size), 200), 1)
    offset = (page - 1) * page_size

    log_event(
        LOGGER,
        logging.INFO,
        "dashboard_db.query_signals.start",
        request_id=request_id,
        symbol=symbol,
        resolution=resolution,
        date_from=date_from,
        date_to=date_to,
        direction=direction,
        status=status,
        signal_id=signal_id,
        page=page,
        page_size=page_size,
    )
    try:
        normalized_resolution = _normalized_upper(resolution)
        normalized_direction = _normalized_upper(direction)
        normalized_status = _normalized_upper(status)
        where = ["1=1"]
        params: list[Any] = []
        effective_status_sql = """
            COALESCE(NULLIF(s.status, ''), 'PENDING')
        """

        if symbol:
            where.append("s.symbol = %s")
            params.append(symbol)
        if normalized_resolution:
            where.append("s.resolution = %s")
            params.append(normalized_resolution)
        if date_from:
            if _looks_like_date_only(date_from):
                where.append(f"(s.timestamp_utc AT TIME ZONE '{display_timezone_name()}')::date >= %s::date")
                params.append(date_from)
            else:
                where.append("s.timestamp_utc >= %s")
                params.append(date_from)
        if date_to:
            if _looks_like_date_only(date_to):
                where.append(f"(s.timestamp_utc AT TIME ZONE '{display_timezone_name()}')::date <= %s::date")
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
            LEFT JOIN LATERAL (
                SELECT
                    sp.active_run_id,
                    sp.shadow_run_id,
                    sp.model_name,
                    sp.shadow_model_version_id,
                    sp.scoring_version,
                    sp.model_path,
                    sp.signal,
                    sp.status,
                    sp.disagreement,
                    sp.direction,
                    sp.confidence,
                    sp.expected_move_pct,
                    sp.entry_price,
                    sp.tp_price,
                    sp.sl_price,
                    sp.reason,
                    sp.generated_at_utc,
                    sp.outcome_updated_at
                FROM signal_shadow_predictions sp
                WHERE sp.active_run_id = s.run_id
                ORDER BY sp.generated_at_utc DESC NULLS LAST
                LIMIT 1
            ) shp ON TRUE
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
                    s.scoring_version,
                    s.actionable,
                    s.validation_status,
                    s.validation_score,
                    s.validation_summary,
                    s.quality_grade,
                    s.movement_after_cost_pct,
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
                    shp.shadow_model_version_id,
                    shp.scoring_version AS shadow_scoring_version,
                    shp.model_path AS shadow_model_path,
                    shp.signal AS shadow_signal,
                    shp.status AS shadow_status,
                    shp.disagreement,
                    shp.direction AS shadow_direction,
                    shp.confidence AS shadow_confidence,
                    shp.expected_move_pct AS shadow_expected_move_pct,
                    shp.entry_price AS shadow_entry_price,
                    shp.tp_price AS shadow_tp_price,
                    shp.sl_price AS shadow_sl_price,
                    shp.reason AS shadow_reason,
                    shp.generated_at_utc AS shadow_generated_at_utc,
                    shp.outcome_updated_at AS shadow_outcome_updated_at,
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
        payload = {
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
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard_db.query_signals.completed",
            request_id=request_id,
            symbol=symbol,
            resolution=resolution,
            page=page,
            page_size=page_size,
            total=total,
            returned_rows=len(enriched),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "dashboard_db.query_signals.error",
            request_id=request_id,
            symbol=symbol,
            resolution=resolution,
            page=page,
            page_size=page_size,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def latest_validation_metrics(*, symbol: str, resolution: str, dsn: str | None = None) -> dict[str, Any] | None:
    with connect(dsn) as conn:
        row = conn.execute(
            """
            WITH latest_run AS (
                SELECT *
                FROM prediction_runs
                WHERE symbol = %s AND resolution = %s
                ORDER BY generated_at_utc DESC
                LIMIT 1
            ),
            outcome_rollup AS (
                SELECT
                    run_id,
                    COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                    COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                    COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending,
                    AVG(ABS(close_error)) FILTER (WHERE status IN ('WIN', 'LOSS'))::double precision AS mae,
                    SQRT(AVG(close_error * close_error) FILTER (WHERE status IN ('WIN', 'LOSS')))::double precision AS rmse,
                    AVG(ABS(close_error_pct)) FILTER (WHERE status IN ('WIN', 'LOSS'))::double precision AS mape_pct
                FROM prediction_outcomes
                WHERE run_id = (SELECT run_id FROM latest_run)
                GROUP BY run_id
            ),
            horizon_rollup AS (
                SELECT
                    fc.run_id,
                    MAX(ABS(((fc.close / NULLIF(r.last_input_close, 0)) - 1.0) * 100.0))::double precision AS max_abs_close_move_pct
                FROM forecast_candles fc
                JOIN latest_run r ON r.run_id = fc.run_id
                GROUP BY fc.run_id
            )
            SELECT
                r.run_id,
                r.generated_at_utc,
                r.forecast_start_timestamp_utc,
                r.forecast_end_timestamp_utc,
                COALESCE(o.wins, 0)::int AS wins,
                COALESCE(o.losses, 0)::int AS losses,
                COALESCE(o.pending, 0)::int AS pending,
                o.mae,
                o.rmse,
                o.mape_pct,
                COALESCE(h.max_abs_close_move_pct, ABS(s.expected_move_pct)::double precision) AS max_abs_close_move_pct
            FROM latest_run r
            LEFT JOIN outcome_rollup o ON o.run_id = r.run_id
            LEFT JOIN horizon_rollup h ON h.run_id = r.run_id
            LEFT JOIN signals s ON s.run_id = r.run_id
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


def _model_status_snapshot(*, symbol: str, resolution: str, dsn: str | None = None) -> dict[str, Any]:
    try:
        with connect(dsn) as conn:
            active = conn.execute(
                """
                SELECT model_version_id, model_name, promotion_status, promotion_reason, artifact_manifest, updated_at
                FROM model_versions
                WHERE symbol = %s
                  AND resolution = %s
                  AND promotion_status = 'promoted'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol, resolution),
            ).fetchone()
            shadow = conn.execute(
                """
                SELECT
                    mv.model_version_id,
                    mv.model_name,
                    mv.promotion_status,
                    COUNT(se.id)::int AS samples,
                    COALESCE(SUM(se.shadow_wins), 0)::int AS wins,
                    COALESCE(SUM(se.shadow_losses), 0)::int AS losses
                FROM model_versions mv
                LEFT JOIN shadow_evaluations se ON se.shadow_model_version_id = mv.model_version_id
                WHERE mv.symbol = %s
                  AND mv.resolution = %s
                  AND mv.promotion_status IN ('pending_review', 'shadow', 'approved')
                GROUP BY mv.model_version_id
                ORDER BY mv.updated_at DESC
                LIMIT 1
                """,
                (symbol, resolution),
            ).fetchone()
        return {
            "active_model": dict(active) if active else None,
            "shadow_model": dict(shadow) if shadow else None,
        }
    except Exception:  # noqa: BLE001
        return {"active_model": None, "shadow_model": None}


def horizon_metric_summary(*, symbol: str, resolution: str, dsn: str | None = None) -> list[dict[str, Any]]:
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
                """
                SELECT
                    hm.horizon_index,
                    COUNT(*) FILTER (
                        WHERE hm.status IN ('WIN','LOSS')
                          AND hm.validation_state = 'FINAL'
                          AND hm.actual_window_complete = true
                    )::int AS samples,
                    COALESCE(SUM(CASE
                        WHEN hm.status = 'WIN'
                         AND hm.validation_state = 'FINAL'
                         AND hm.actual_window_complete = true THEN 1 ELSE 0
                    END), 0)::int AS wins,
                    COALESCE(SUM(CASE
                        WHEN hm.status = 'LOSS'
                         AND hm.validation_state = 'FINAL'
                         AND hm.actual_window_complete = true THEN 1 ELSE 0
                    END), 0)::int AS losses,
                    AVG(ABS(hm.close_error)) FILTER (
                        WHERE hm.status IN ('WIN','LOSS')
                          AND hm.validation_state = 'FINAL'
                          AND hm.actual_window_complete = true
                    )::double precision AS mae,
                    AVG(ABS(hm.close_error_pct)) FILTER (
                        WHERE hm.status IN ('WIN','LOSS')
                          AND hm.validation_state = 'FINAL'
                          AND hm.actual_window_complete = true
                    )::double precision AS mape_pct
                FROM forecast_horizon_metrics hm
                JOIN prediction_runs r ON r.run_id = hm.run_id
                WHERE r.symbol = %s AND r.resolution = %s
                GROUP BY hm.horizon_index
                ORDER BY hm.horizon_index
                LIMIT 96
                """,
                (symbol, resolution),
            ).fetchall()
        payload = []
        for row in rows:
            samples = _to_int(row.get("samples"))
            wins = _to_int(row.get("wins"))
            payload.append(
                {
                    **dict(row),
                    "direction_accuracy_pct": None if samples == 0 else (wins / samples) * 100.0,
                }
            )
        return payload
    except Exception:  # noqa: BLE001
        return []


def postgres_dashboard_snapshot(*, symbol: str = "ETHUSD", resolution: str = "MINUTE_5", dsn: str | None = None) -> dict[str, Any]:
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "dashboard_db.postgres_snapshot.start",
        request_id=request_id,
        symbol=symbol,
        resolution=resolution,
    )
    try:
        health = healthcheck(dsn)
        if not health["ok"]:
            payload = {"postgres": health}
            log_event(
                LOGGER,
                logging.WARNING,
                "dashboard_db.postgres_snapshot.completed",
                request_id=request_id,
                symbol=symbol,
                resolution=resolution,
                postgres_ok=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return payload
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
                    COALESCE(NULLIF(s.status, ''), 'PENDING') AS status,
                    s.status AS status_raw,
                    s.confidence,
                    s.expected_move_pct,
                    s.cost_threshold_pct,
                    s.scoring_version,
                    s.actionable,
                    s.validation_status,
                    s.validation_score,
                    s.validation_summary,
                    s.quality_grade,
                    s.movement_after_cost_pct,
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
                    shp.shadow_model_version_id,
                    shp.scoring_version AS shadow_scoring_version,
                    shp.model_path AS shadow_model_path,
                    shp.signal AS shadow_signal,
                    shp.status AS shadow_status,
                    shp.disagreement,
                    shp.direction AS shadow_direction,
                    shp.confidence AS shadow_confidence,
                    shp.expected_move_pct AS shadow_expected_move_pct,
                    shp.entry_price AS shadow_entry_price,
                    shp.tp_price AS shadow_tp_price,
                    shp.sl_price AS shadow_sl_price,
                    shp.reason AS shadow_reason,
                    shp.generated_at_utc AS shadow_generated_at_utc,
                    shp.outcome_updated_at AS shadow_outcome_updated_at,
                    COALESCE(o.outcomes_wins, 0)::int AS outcomes_wins,
                    COALESCE(o.outcomes_losses, 0)::int AS outcomes_losses,
                    COALESCE(o.outcomes_pending, 0)::int AS outcomes_pending
                FROM signals s
                JOIN prediction_runs r ON r.run_id = s.run_id
                LEFT JOIN LATERAL (
                    SELECT
                        sp.active_run_id,
                        sp.shadow_run_id,
                        sp.model_name,
                        sp.shadow_model_version_id,
                        sp.scoring_version,
                        sp.model_path,
                        sp.signal,
                        sp.status,
                        sp.disagreement,
                        sp.direction,
                        sp.confidence,
                        sp.expected_move_pct,
                        sp.entry_price,
                        sp.tp_price,
                        sp.sl_price,
                        sp.reason,
                        sp.generated_at_utc,
                        sp.outcome_updated_at
                    FROM signal_shadow_predictions sp
                    WHERE sp.active_run_id = s.run_id
                    ORDER BY sp.generated_at_utc DESC NULLS LAST
                    LIMIT 1
                ) shp ON TRUE
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

            latest_signal_validation_row = None
            timeframe_validations_rows: list[dict[str, Any]] = []
            signal_validation_summary_row = None
            validation_query_error = None
            try:
                latest_signal_validation_row = conn.execute(
                    """
                    SELECT
                        run_id,
                        symbol,
                        epic,
                        base_resolution,
                        candidate_signal,
                        final_signal,
                        forecast_direction,
                        last_input_close,
                        forecast_close,
                        forecast_return_pct,
                        estimated_cost_pct,
                        net_edge_pct,
                        blocked,
                        block_reason,
                        confidence_level,
                        total_score,
                        component_scores,
                        reason_codes,
                        reason_details,
                        created_at,
                        updated_at
                    FROM signal_validation_runs
                    WHERE symbol = %s
                      AND base_resolution = %s
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (symbol, resolution),
                ).fetchone()
                if latest_signal_validation_row and latest_signal_validation_row.get("run_id"):
                    timeframe_validations_rows = conn.execute(
                        """
                        SELECT
                            run_id,
                            timeframe,
                            timestamp_utc,
                            trend,
                            confirms_candidate,
                            trend_score,
                            momentum_score,
                            volume_score,
                            volatility_score,
                            support_resistance_score,
                            total_timeframe_score,
                            indicator_snapshot,
                            reason_details,
                            created_at
                        FROM signal_timeframe_validations
                        WHERE run_id = %s
                        ORDER BY CASE timeframe
                            WHEN 'MINUTE_15' THEN 1
                            WHEN 'MINUTE_30' THEN 2
                            WHEN 'HOUR' THEN 3
                            WHEN 'HOUR_4' THEN 4
                            ELSE 99
                        END
                        """,
                        (latest_signal_validation_row["run_id"],),
                    ).fetchall()
                signal_validation_summary_row = conn.execute(
                    """
                    SELECT
                        COUNT(*)::int AS total_runs,
                        COALESCE(SUM(CASE WHEN blocked THEN 1 ELSE 0 END), 0)::int AS blocked_runs,
                        COALESCE(SUM(CASE WHEN block_reason = 'INVALID_5M_INPUT' THEN 1 ELSE 0 END), 0)::int AS invalid_5m_input_runs,
                        COALESCE(SUM(CASE WHEN block_reason = 'FORECAST_EDGE_BELOW_COST' THEN 1 ELSE 0 END), 0)::int AS edge_below_cost_runs,
                        COALESCE(SUM(CASE WHEN block_reason = 'VERY_LOW_VOLUME' THEN 1 ELSE 0 END), 0)::int AS very_low_volume_runs,
                        COALESCE(SUM(CASE WHEN final_signal IN ('LONG', 'SHORT', 'STRONG_LONG', 'STRONG_SHORT', 'WEAK_LONG', 'WEAK_SHORT') THEN 1 ELSE 0 END), 0)::int AS actionable_runs,
                        AVG(total_score)::double precision AS average_score
                    FROM signal_validation_runs
                    WHERE symbol = %s
                      AND base_resolution = %s
                      AND created_at >= now() - interval '24 hours'
                    """,
                    (symbol, resolution),
                ).fetchone()
            except Exception as exc:  # noqa: BLE001
                validation_query_error = str(exc)

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
            "trade_execution_worker": {"status": "MISSING", "details": {}, "updated_at": None},
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

        model_status = _model_status_snapshot(symbol=symbol, resolution=resolution, dsn=dsn)
        try:
            latest_validation = latest_validation_metrics(symbol=symbol, resolution=resolution, dsn=dsn)
        except Exception:  # noqa: BLE001
            latest_validation = None
        if latest_signal_validation_row is None:
            if validation_query_error and "does not exist" in validation_query_error.lower():
                latest_signal_validation: dict[str, Any] = {
                    "ok": False,
                    "error": "validation_tables_missing",
                    "reason": validation_query_error,
                }
            elif validation_query_error:
                latest_signal_validation = {
                    "ok": False,
                    "error": "query_failed",
                    "reason": validation_query_error,
                }
            else:
                latest_signal_validation = {}
        else:
            latest_signal_validation = dict(latest_signal_validation_row)
        timeframe_validations = [dict(row) for row in timeframe_validations_rows]
        if signal_validation_summary_row:
            raw_summary = dict(signal_validation_summary_row)
            total_runs = _to_int(raw_summary.get("total_runs"))
            blocked_runs = _to_int(raw_summary.get("blocked_runs"))
            actionable_runs = _to_int(raw_summary.get("actionable_runs"))
            invalid_runs = _to_int(raw_summary.get("invalid_5m_input_runs"))
            edge_runs = _to_int(raw_summary.get("edge_below_cost_runs"))
            low_volume_runs = _to_int(raw_summary.get("very_low_volume_runs"))
            signal_validation_summary = {
                **raw_summary,
                "window_hours": 24,
                "blocked_ratio_pct": None if total_runs == 0 else round((blocked_runs / total_runs) * 100.0, 2),
                "actionable_ratio_pct": None if total_runs == 0 else round((actionable_runs / total_runs) * 100.0, 2),
                "invalid_5m_input_ratio_pct": None if total_runs == 0 else round((invalid_runs / total_runs) * 100.0, 2),
                "edge_below_cost_ratio_pct": None if total_runs == 0 else round((edge_runs / total_runs) * 100.0, 2),
                "very_low_volume_ratio_pct": None if total_runs == 0 else round((low_volume_runs / total_runs) * 100.0, 2),
            }
        else:
            signal_validation_summary = {}
        try:
            supervisor = current_supervisor_lease(dsn=dsn)
        except Exception:  # noqa: BLE001
            supervisor = None
        payload = {
            "postgres": health,
            "candles": [dict(row) for row in reversed(candles)],
            "signals": [_enrich_signal_levels(dict(row)) for row in signals],
            "live_quote": dict(live_quote) if live_quote else None,
            "live_health": {
                "websocket_quote": websocket_row,
                "websocket_last_update_utc": websocket_ref,
                "websocket_stale_seconds": websocket_stale_seconds,
                "websocket_stale_alert": websocket_stale_seconds is None or websocket_stale_seconds > WEBSOCKET_STALE_THRESHOLD_SECONDS,
                "alert_threshold_seconds": WEBSOCKET_STALE_THRESHOLD_SECONDS,
            },
            "latest_validation": latest_validation,
            "signal_validation": latest_signal_validation,
            "signal_validation_summary": signal_validation_summary,
            "timeframe_validations": timeframe_validations,
            "horizon_metrics": horizon_metric_summary(symbol=symbol, resolution=resolution, dsn=dsn),
            "outcomes": [dict(row) for row in outcomes],
            "heartbeats": [dict(row) for row in heartbeats],
            "worker_statuses": worker_statuses,
            "active_model": model_status.get("active_model"),
            "shadow_model": model_status.get("shadow_model"),
            "rate_limits": list_rate_limit_states(dsn=dsn),
            "supervisor_lease": supervisor,
            "prediction_db": prediction_summary(dsn, limit=20),
        }
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard_db.postgres_snapshot.completed",
            request_id=request_id,
            symbol=symbol,
            resolution=resolution,
            candles=len(payload.get("candles") or []),
            signals=len(payload.get("signals") or []),
            heartbeats=len(payload.get("heartbeats") or []),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "dashboard_db.postgres_snapshot.error",
            request_id=request_id,
            symbol=symbol,
            resolution=resolution,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
