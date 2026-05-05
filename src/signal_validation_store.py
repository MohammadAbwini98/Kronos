from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from db import connect


def _is_missing_validation_table_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "does not exist" in text
        and (
            "signal_validation_runs" in text
            or "signal_timeframe_validations" in text
            or "validation_score" in text
            or "validation_summary" in text
        )
    )


def _structured_missing_table_error(exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "validation_tables_missing",
        "reason": str(exc),
    }


def _coerce_timestamp_utc(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def save_signal_validation_run(validation: dict, dsn: str | None = None) -> dict[str, Any]:
    payload = dict(validation or {})
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return {"ok": False, "error": "run_id_required"}

    try:
        with connect(dsn) as conn:
            row = conn.execute(
                """
                INSERT INTO signal_validation_runs(
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
                    updated_at
                )
                VALUES (
                    %(run_id)s,
                    %(symbol)s,
                    %(epic)s,
                    %(base_resolution)s,
                    %(candidate_signal)s,
                    %(final_signal)s,
                    %(forecast_direction)s,
                    %(last_input_close)s,
                    %(forecast_close)s,
                    %(forecast_return_pct)s,
                    %(estimated_cost_pct)s,
                    %(net_edge_pct)s,
                    %(blocked)s,
                    %(block_reason)s,
                    %(confidence_level)s,
                    %(total_score)s,
                    %(component_scores)s,
                    %(reason_codes)s,
                    %(reason_details)s,
                    now()
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    epic = EXCLUDED.epic,
                    base_resolution = EXCLUDED.base_resolution,
                    candidate_signal = EXCLUDED.candidate_signal,
                    final_signal = EXCLUDED.final_signal,
                    forecast_direction = EXCLUDED.forecast_direction,
                    last_input_close = EXCLUDED.last_input_close,
                    forecast_close = EXCLUDED.forecast_close,
                    forecast_return_pct = EXCLUDED.forecast_return_pct,
                    estimated_cost_pct = EXCLUDED.estimated_cost_pct,
                    net_edge_pct = EXCLUDED.net_edge_pct,
                    blocked = EXCLUDED.blocked,
                    block_reason = EXCLUDED.block_reason,
                    confidence_level = EXCLUDED.confidence_level,
                    total_score = EXCLUDED.total_score,
                    component_scores = EXCLUDED.component_scores,
                    reason_codes = EXCLUDED.reason_codes,
                    reason_details = EXCLUDED.reason_details,
                    updated_at = now()
                RETURNING run_id, final_signal, total_score, blocked, block_reason
                """,
                {
                    "run_id": run_id,
                    "symbol": str(payload.get("symbol") or "ETHUSD"),
                    "epic": str(payload.get("epic") or payload.get("symbol") or "ETHUSD"),
                    "base_resolution": str(payload.get("base_resolution") or payload.get("resolution") or "MINUTE_5"),
                    "candidate_signal": str(payload.get("candidate_signal") or "HOLD"),
                    "final_signal": str(payload.get("final_signal") or "VALIDATION_UNAVAILABLE"),
                    "forecast_direction": str(payload.get("forecast_direction") or "FLAT"),
                    "last_input_close": payload.get("last_input_close"),
                    "forecast_close": payload.get("forecast_close")
                    if payload.get("forecast_close") is not None
                    else payload.get("last_forecast_close"),
                    "forecast_return_pct": payload.get("forecast_return_pct"),
                    "estimated_cost_pct": payload.get("estimated_cost_pct"),
                    "net_edge_pct": payload.get("net_edge_pct"),
                    "blocked": bool(payload.get("blocked", False)),
                    "block_reason": payload.get("block_reason"),
                    "confidence_level": str(payload.get("confidence_level") or "NONE"),
                    "total_score": float(payload.get("total_score") or 0.0),
                    "component_scores": Jsonb(payload.get("component_scores") or {}),
                    "reason_codes": Jsonb(payload.get("reason_codes") or []),
                    "reason_details": Jsonb(payload.get("reason_details") or []),
                },
            ).fetchone()
        return {"ok": True, "saved": dict(row) if row else {"run_id": run_id}}
    except Exception as exc:  # noqa: BLE001
        if _is_missing_validation_table_error(exc):
            return _structured_missing_table_error(exc)
        return {"ok": False, "error": "save_failed", "reason": str(exc)}


def save_timeframe_validations(run_id: str, validations: list[dict], dsn: str | None = None) -> dict[str, Any]:
    if not run_id:
        return {"ok": False, "error": "run_id_required"}

    items = list(validations or [])
    if not items:
        return {"ok": True, "saved_count": 0}

    try:
        with connect(dsn) as conn:
            for row in items:
                conn.execute(
                    """
                    INSERT INTO signal_timeframe_validations(
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
                        reason_details
                    )
                    VALUES (
                        %(run_id)s,
                        %(timeframe)s,
                        %(timestamp_utc)s,
                        %(trend)s,
                        %(confirms_candidate)s,
                        %(trend_score)s,
                        %(momentum_score)s,
                        %(volume_score)s,
                        %(volatility_score)s,
                        %(support_resistance_score)s,
                        %(total_timeframe_score)s,
                        %(indicator_snapshot)s,
                        %(reason_details)s
                    )
                    ON CONFLICT(run_id, timeframe) DO UPDATE SET
                        timestamp_utc = EXCLUDED.timestamp_utc,
                        trend = EXCLUDED.trend,
                        confirms_candidate = EXCLUDED.confirms_candidate,
                        trend_score = EXCLUDED.trend_score,
                        momentum_score = EXCLUDED.momentum_score,
                        volume_score = EXCLUDED.volume_score,
                        volatility_score = EXCLUDED.volatility_score,
                        support_resistance_score = EXCLUDED.support_resistance_score,
                        total_timeframe_score = EXCLUDED.total_timeframe_score,
                        indicator_snapshot = EXCLUDED.indicator_snapshot,
                        reason_details = EXCLUDED.reason_details
                    """,
                    {
                        "run_id": run_id,
                        "timeframe": str(row.get("timeframe") or "UNKNOWN"),
                        "timestamp_utc": _coerce_timestamp_utc(row.get("timestamp_utc")),
                        "trend": str(row.get("trend") or "NEUTRAL"),
                        "confirms_candidate": bool(row.get("confirms_candidate", False)),
                        "trend_score": float(row.get("trend_score") or 0.0),
                        "momentum_score": float(row.get("momentum_score") or 0.0),
                        "volume_score": float(row.get("volume_score") or 0.0),
                        "volatility_score": float(row.get("volatility_score") or 0.0),
                        "support_resistance_score": float(row.get("support_resistance_score") or 0.0),
                        "total_timeframe_score": float(row.get("total_timeframe_score") or 0.0),
                        "indicator_snapshot": Jsonb(row.get("indicator_snapshot") or {}),
                        "reason_details": Jsonb(row.get("reason_details") or []),
                    },
                )
        return {"ok": True, "saved_count": len(items)}
    except Exception as exc:  # noqa: BLE001
        if _is_missing_validation_table_error(exc):
            return _structured_missing_table_error(exc)
        return {"ok": False, "error": "save_failed", "reason": str(exc)}


def load_latest_signal_validation(symbol: str = "ETHUSD", dsn: str | None = None) -> dict:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
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
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return {} if row is None else dict(row)
    except Exception as exc:  # noqa: BLE001
        if _is_missing_validation_table_error(exc):
            return _structured_missing_table_error(exc)
        return {"ok": False, "error": "query_failed", "reason": str(exc)}


def load_signal_validation_history(symbol: str = "ETHUSD", limit: int = 50, dsn: str | None = None) -> list[dict]:
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    symbol,
                    epic,
                    base_resolution,
                    candidate_signal,
                    final_signal,
                    forecast_direction,
                    blocked,
                    block_reason,
                    confidence_level,
                    total_score,
                    created_at
                FROM signal_validation_runs
                WHERE symbol = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (symbol, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def load_timeframe_validations(run_id: str, dsn: str | None = None) -> list[dict]:
    if not run_id:
        return []
    try:
        with connect(dsn) as conn:
            rows = conn.execute(
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
                ORDER BY timeframe ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def load_validation_summary(dsn: str | None = None) -> dict:
    try:
        with connect(dsn) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)::int AS total_runs,
                    COALESCE(SUM(CASE WHEN blocked THEN 1 ELSE 0 END), 0)::int AS blocked_runs,
                    COALESCE(SUM(CASE WHEN final_signal IN ('LONG', 'SHORT', 'STRONG_LONG', 'STRONG_SHORT', 'WEAK_LONG', 'WEAK_SHORT') THEN 1 ELSE 0 END), 0)::int AS actionable_runs,
                    AVG(total_score)::double precision AS average_score
                FROM signal_validation_runs
                """
            ).fetchone()
        return dict(row or {})
    except Exception as exc:  # noqa: BLE001
        if _is_missing_validation_table_error(exc):
            return _structured_missing_table_error(exc)
        return {"ok": False, "error": "query_failed", "reason": str(exc)}


def update_signal_validation_summary(run_id: str, validation: dict, dsn: str | None = None) -> None:
    if not run_id:
        return

    summary = {
        "candidate_signal": validation.get("candidate_signal"),
        "final_signal": validation.get("final_signal"),
        "confidence_level": validation.get("confidence_level"),
        "total_score": validation.get("total_score"),
        "blocked": validation.get("blocked"),
        "block_reason": validation.get("block_reason"),
        "component_scores": validation.get("component_scores") or {},
        "reason_codes": validation.get("reason_codes") or [],
        "reason_details": validation.get("reason_details") or [],
        "net_edge_pct": validation.get("net_edge_pct"),
        "estimated_cost_pct": validation.get("estimated_cost_pct"),
    }

    try:
        with connect(dsn) as conn:
            conn.execute(
                """
                UPDATE signals
                SET validation_score = %s,
                    validation_status = %s,
                    validation_summary = %s,
                    updated_at = now()
                WHERE run_id = %s
                """,
                (
                    validation.get("total_score"),
                    str(validation.get("final_signal") or "VALIDATION_UNAVAILABLE"),
                    Jsonb(summary),
                    run_id,
                ),
            )
    except Exception:
        # Dashboard and scheduler should continue even if validation columns are not present yet.
        return
