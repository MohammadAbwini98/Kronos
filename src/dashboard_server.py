from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from config import configure_logging
from dashboard_db import postgres_dashboard_snapshot, query_signals
from dashboard_ui import dashboard_html
from dataset_snapshots import create_dataset_snapshot
from db import connect
from logging_utils import log_event, new_correlation_id, output_tail, safe_command_for_log
from model_registry import evaluate_promotion, list_model_versions, model_performance
from prediction_store import prediction_summary
from prediction_log_report import generate_prediction_log_report
from time_utils import display_timezone_name
from trade_execution import (
    CapitalTradingClient,
    TradeExecutionQueueService,
    TradeExecutionRepository,
    TradeExecutionService,
    enqueue_signal_for_execution,
)
from walk_forward import create_walk_forward_experiment, get_walk_forward_experiment, run_walk_forward_experiment


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
SUPPORTED_RESOLUTIONS = {"MINUTE", "MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY", "WEEK"}
LOGGER = logging.getLogger(__name__)
_TRANSACTION_HISTORY_CACHE = {"expires_at": 0.0, "transactions": [], "error": None}
_TRANSACTION_HISTORY_CACHE_LOCK = threading.Lock()
_TRADE_ACTIVITY_CACHE = {"expires_at": 0.0, "activities": [], "error": None}
_TRADE_ACTIVITY_CACHE_LOCK = threading.Lock()
_TRADE_ENRICHMENT_SERVICE: TradeExecutionService | None = None
_TRADE_ENRICHMENT_SERVICE_LOCK = threading.Lock()


def _latest_file(pattern: str) -> Path | None:
    files = sorted(OUTPUT_DIR.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _safe_json(path: str | Path | None) -> dict:
    if not path:
        return {}
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def _safe_csv(path: str | Path | None, limit: int | None = None) -> list[dict]:
    if not path:
        return []
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        return []
    df = pd.read_csv(source)
    if "timestamps" in df.columns:
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True).dt.tz_convert(display_timezone_name()).astype(str)
    if limit is not None:
        df = df.tail(limit)
    return df.to_dict(orient="records")


def _metadata_stamp(path: Path) -> str:
    return path.stem.split("_")[-1]


def _safe_file_fragment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _coerce_symbol_resolution(
    symbol: str | None,
    resolution: str | None,
    *,
    default_symbol: str = "ETHUSD",
    default_resolution: str = "MINUTE_5",
) -> tuple[str, str]:
    symbol_value = str(symbol or default_symbol).strip().upper()
    resolution_value = str(resolution or default_resolution).strip().upper()
    if not symbol_value or len(symbol_value) > 64:
        raise ValueError("symbol is required")
    if resolution_value not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Unsupported resolution")
    return symbol_value, resolution_value


def _action_context(payload: dict) -> tuple[str, str]:
    return _coerce_symbol_resolution(
        payload.get("symbol") or payload.get("market"),
        payload.get("resolution"),
        default_symbol="ETHUSD",
        default_resolution="MINUTE_5",
    )


def _metadata_matches_context(metadata: dict, symbol: str | None, resolution: str | None) -> bool:
    if not metadata:
        return False
    metadata_symbol = str(metadata.get("epic") or metadata.get("symbol") or "").strip().upper()
    metadata_resolution = str(metadata.get("resolution") or "").strip().upper()
    symbol_ok = not symbol or not metadata_symbol or metadata_symbol == symbol
    resolution_ok = not resolution or not metadata_resolution or metadata_resolution == resolution
    return symbol_ok and resolution_ok


def _latest_metadata(symbol: str | None = None, resolution: str | None = None) -> tuple[Path | None, dict]:
    symbol_part = _safe_file_fragment(symbol) if symbol else "ETHUSD"
    resolution_part = _safe_file_fragment(resolution) if resolution else "*"
    preferred = f"forecast_metadata_{symbol_part}_{resolution_part}_*.json"
    fallback_symbol = f"forecast_metadata_{symbol_part}_*.json"
    path = _latest_file(preferred) or _latest_file(fallback_symbol) or _latest_file("forecast_metadata_ETHUSD_*.json") or _latest_file("forecast_metadata_*.json")
    return path, _safe_json(path)


def _quality_report_for_metadata(metadata_path: Path | None, metadata: dict) -> tuple[Path | None, dict]:
    if metadata_path is not None:
        stamp = _metadata_stamp(metadata_path)
        epic = _safe_file_fragment(str(metadata.get("epic") or "ETHUSD"))
        resolution = _safe_file_fragment(str(metadata.get("resolution") or "MINUTE_5"))
        candidate = OUTPUT_DIR / f"forecast_quality_report_{epic}_{resolution}_{stamp}.json"
        if candidate.exists():
            return candidate, _safe_json(candidate)
    validation_path = metadata.get("validation_report_path")
    legacy = _safe_json(validation_path)
    if legacy.get("forecast_quality_validation"):
        source = Path(validation_path) if validation_path else None
        return source, legacy
    return None, {}


def _merge_validation(primary: dict, fallback: dict) -> dict:
    result = dict(primary or {})
    for key, value in (fallback or {}).items():
        if result.get(key) is None:
            result[key] = value
    return result


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")
    setattr(handler, "_response_status", status)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Expires", "0")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> None:
    request_id = str(getattr(handler, "_request_id", str(uuid.uuid4())))
    _json_response(
        handler,
        status,
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
                "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        },
    )


def _require_auth(handler: BaseHTTPRequestHandler) -> bool:
    token = os.getenv("DASHBOARD_API_TOKEN")
    if not token:
        return True
    if handler.headers.get("Authorization") == f"Bearer {token}":
        return True
    _error_response(handler, 401, "VALIDATION_ERROR", "Missing or invalid dashboard API token")
    return False


def _content_type(path: Path) -> str:
    if path.suffix.lower() == ".html":
        return "text/html; charset=utf-8"
    if path.suffix.lower() == ".json":
        return "application/json; charset=utf-8"
    if path.suffix.lower() == ".csv":
        return "text/csv; charset=utf-8"
    return "text/plain; charset=utf-8"


def _resolve_path_within_root(path_value: str | Path) -> Path:
    target = Path(path_value)
    if not target.is_absolute():
        target = ROOT / target
    resolved = target.resolve(strict=True)
    resolved.relative_to(ROOT.resolve())
    return resolved


def _run(
    cmd: list[str],
    timeout: int = 420,
    *,
    request_id: str | None = None,
    endpoint: str | None = None,
) -> dict:
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "dashboard.subprocess.start",
        request_id=request_id,
        endpoint=endpoint,
        timeout_seconds=timeout,
        command=safe_command_for_log(cmd),
    )
    try:
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "dashboard.subprocess.error",
            request_id=request_id,
            endpoint=endpoint,
            duration_ms=int((time.perf_counter() - started) * 1000),
            command=safe_command_for_log(cmd),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    log_event(
        LOGGER,
        logging.INFO if result.returncode == 0 else logging.WARNING,
        "dashboard.subprocess.completed",
        request_id=request_id,
        endpoint=endpoint,
        duration_ms=int((time.perf_counter() - started) * 1000),
        returncode=int(result.returncode),
        output_tail=output_tail(output),
        command=safe_command_for_log(cmd),
    )
    return {"returncode": result.returncode, "output": output}


def _history(limit: int = 20) -> list[dict]:
    rows = []
    for path in sorted(OUTPUT_DIR.glob("forecast_metadata_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        metadata = _safe_json(path)
        validation = _safe_json(metadata.get("validation_report_path"))
        validation_body = validation.get("forecast_quality_validation", validation)
        rows.append(
            {
                "metadata_path": str(path),
                "forecast_path": metadata.get("forecast_csv_path"),
                "generated_at_local": metadata.get("generated_at_local"),
                "forecast_start": metadata.get("forecast_start_timestamp"),
                "forecast_end": metadata.get("forecast_end_timestamp"),
                "epic": metadata.get("epic"),
                "resolution": metadata.get("resolution"),
                "direction": validation_body.get("forecast_direction"),
                "last_input_close": metadata.get("last_input_close"),
                "last_forecast_close": validation_body.get("last_forecast_close"),
                "quality_status": validation_body.get("quality_status"),
            }
        )
    return rows


def _prediction_db_summary() -> dict:
    try:
        return prediction_summary(limit=20)
    except Exception as exc:  # keep dashboard status available if the local DB is locked or missing
        return {"error": str(exc)}


def _trade_enrichment_service() -> TradeExecutionService:
    global _TRADE_ENRICHMENT_SERVICE
    with _TRADE_ENRICHMENT_SERVICE_LOCK:
        if _TRADE_ENRICHMENT_SERVICE is None:
            _TRADE_ENRICHMENT_SERVICE = TradeExecutionService()
        return _TRADE_ENRICHMENT_SERVICE


def _cached_trade_transactions(service: TradeExecutionService, ttl_seconds: int = 30) -> tuple[list[dict], str | None]:
    now = time.monotonic()
    with _TRANSACTION_HISTORY_CACHE_LOCK:
        if float(_TRANSACTION_HISTORY_CACHE.get("expires_at") or 0) > now:
            return list(_TRANSACTION_HISTORY_CACHE.get("transactions") or []), _TRANSACTION_HISTORY_CACHE.get("error")

    try:
        transactions = service.client.get_transaction_history(last_period_seconds=86400, transaction_type="TRADE")
        error = None
    except Exception as exc:  # noqa: BLE001
        with _TRANSACTION_HISTORY_CACHE_LOCK:
            transactions = list(_TRANSACTION_HISTORY_CACHE.get("transactions") or [])
        if transactions:
            return transactions, None
        transactions = []
        error = str(exc)

    with _TRANSACTION_HISTORY_CACHE_LOCK:
        _TRANSACTION_HISTORY_CACHE.update(
            {
                "expires_at": time.monotonic() + (ttl_seconds if not error else 60),
                "transactions": transactions,
                "error": error,
            }
        )
    return list(transactions), error


def _cached_trade_activities(service: TradeExecutionService, ttl_seconds: int = 30) -> tuple[list[dict], str | None]:
    now = time.monotonic()
    with _TRADE_ACTIVITY_CACHE_LOCK:
        if float(_TRADE_ACTIVITY_CACHE.get("expires_at") or 0) > now:
            return list(_TRADE_ACTIVITY_CACHE.get("activities") or []), _TRADE_ACTIVITY_CACHE.get("error")

    try:
        activities = service.client.get_activity_history(last_period_seconds=86400)
        error = None
    except Exception as exc:  # noqa: BLE001
        with _TRADE_ACTIVITY_CACHE_LOCK:
            activities = list(_TRADE_ACTIVITY_CACHE.get("activities") or [])
        if activities:
            return activities, None
        activities = []
        error = str(exc)

    with _TRADE_ACTIVITY_CACHE_LOCK:
        _TRADE_ACTIVITY_CACHE.update(
            {
                "expires_at": time.monotonic() + (ttl_seconds if not error else 60),
                "activities": activities,
                "error": error,
            }
        )
    return list(activities), error


def _trade_execution_status() -> dict:
    try:
        queue = TradeExecutionQueueService()
        trades = queue.repository.executed_trades(limit=100)
        transaction_lookup_error = None
        outcome_lookup_error = None
        if any(str(row.get("deal_id") or "").strip() for row in trades):
            transaction_service = _trade_enrichment_service()
            transactions, transaction_lookup_error = _cached_trade_transactions(transaction_service)
            trades = transaction_service.enrich_transaction_references(trades, transactions=transactions)
            activities, outcome_lookup_error = _cached_trade_activities(transaction_service)
            trades = transaction_service.enrich_trade_outcomes(trades, activities=activities)
            if transaction_lookup_error:
                for row in trades:
                    if str(row.get("deal_id") or "").strip():
                        row["transaction_lookup_error"] = transaction_lookup_error
            if outcome_lookup_error:
                for row in trades:
                    if str(row.get("deal_id") or "").strip():
                        row["trade_outcome_lookup_error"] = outcome_lookup_error
        active_statuses = {"OPEN", "CLOSE_REQUESTED"}
        pending_statuses = {"PENDING", "SUBMITTED"}
        return {
            "ok": True,
            "queue": queue.snapshot(),
            "trades": trades,
            "transaction_lookup_error": transaction_lookup_error,
            "trade_outcome_lookup_error": outcome_lookup_error,
            "active_trades": [row for row in trades if str(row.get("status") or "").upper() in active_statuses],
            "pending_trades": [row for row in trades if str(row.get("status") or "").upper() in pending_statuses],
            "historical_trades": [
                row
                for row in trades
                if str(row.get("status") or "").upper() not in active_statuses | pending_statuses
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_account_snapshot() -> dict:
    try:
        client = CapitalTradingClient()
        account = client.get_account_snapshot()
        positions = client.get_open_positions()
        return {
            "ok": True,
            "account": {
                "account_id": account.account_id,
                "account_name": account.account_name,
                "currency": account.currency,
                "balance": account.balance,
                "available": account.available,
                "profit_loss": account.profit_loss,
                "equity": account.equity,
                "is_demo": account.is_demo,
            },
            "open_positions": positions,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _postgres_snapshot(symbol: str = "ETHUSD", resolution: str = "MINUTE_5") -> dict:
    try:
        return postgres_dashboard_snapshot(symbol=symbol, resolution=resolution)
    except Exception as exc:  # noqa: BLE001
        return {"postgres": {"ok": False, "error": str(exc)}}


def _metadata_for_run_id(run_id: str | None, symbol: str | None = None, resolution: str | None = None) -> tuple[Path | None, dict]:
    normalized_symbol = str(symbol).strip().upper() if symbol else None
    normalized_resolution = str(resolution).strip().upper() if resolution else None
    if not run_id:
        return _latest_metadata(normalized_symbol, normalized_resolution)
    try:
        with connect() as conn:
            row = conn.execute("SELECT metadata_path FROM prediction_runs WHERE run_id = %s", (run_id,)).fetchone()
        if row and row.get("metadata_path"):
            path = Path(row["metadata_path"])
            if not path.is_absolute():
                path = ROOT / path
            metadata = _safe_json(path)
            if not _metadata_matches_context(metadata, normalized_symbol, normalized_resolution):
                return None, {}
            return path, metadata
    except Exception:
        return None, {}
    return None, {}


def _validated_payload(handler: BaseHTTPRequestHandler) -> dict | None:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        payload = json.loads(handler.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
        return payload
    except Exception as exc:  # noqa: BLE001
        _error_response(handler, 400, "VALIDATION_ERROR", "Invalid JSON request payload", {"reason": str(exc)})
        return None


def _auto_finetune_status() -> dict:
    payload = _safe_json(OUTPUT_DIR / "auto_finetune_status.json")
    if not payload:
        return {}
    enabled = str(os.getenv("ENABLE_AUTO_FINETUNE", "true")).strip().lower() in {"1", "true", "yes", "on"}
    rows = int(payload.get("dataset_rows") or 0)
    required = int(payload.get("required_dataset_rows") or payload.get("min_rows") or 0)
    progress = payload.get("promotion_progress_pct")
    if progress is None:
        progress = 100.0 if required <= 0 else min(100.0, (rows / required) * 100.0)
    promotion_status = str(payload.get("promotion_status") or "").strip().lower()
    active_ready = bool(payload.get("active_model_ready"))
    auto_model_running = enabled and active_ready and promotion_status in {"approved", "promoted"}
    model_path = payload.get("active_model_path")
    model_version = Path(str(model_path)).name if model_path else None
    enriched = dict(payload)
    enriched.update(
        {
            "dataset_rows": rows,
            "enabled": enabled,
            "required_dataset_rows": required,
            "promotion_progress_pct": round(float(progress), 2),
            "current_model_label": "Kronos-auto-finetuned" if auto_model_running else "Kronos-base",
            "current_model_version": model_version if auto_model_running else "Kronos-base",
            "candidate_model_version": model_version,
            "auto_model_running": auto_model_running,
        }
    )
    return enriched


def _human_summary(metadata: dict, validation_body: dict, postgres_snapshot: dict) -> dict:
    candles = postgres_snapshot.get("candles", [])
    latest_signal = (postgres_snapshot.get("signals") or [{}])[0]
    latest_candle = candles[-1] if candles else {}
    live_quote = postgres_snapshot.get("live_quote") or {}
    live_health = postgres_snapshot.get("live_health") or {}
    worker_statuses = postgres_snapshot.get("worker_statuses") or {}
    scheduler_worker = worker_statuses.get("prediction_scheduler") or {}
    prediction_db = postgres_snapshot.get("prediction_db") or {}
    latest_run = (prediction_db.get("recent_runs") or [{}])[0]
    live_source = live_quote.get("source")
    return {
        "latest_price": live_quote.get("price") or latest_candle.get("close") or metadata.get("last_input_close"),
        "latest_price_time": live_quote.get("updated_at") or live_quote.get("timestamp_utc") or latest_candle.get("timestamp_utc"),
        "latest_candle_time": latest_candle.get("timestamp_utc"),
        "live_source": live_source,
        "live_source_warning": "Live price is currently from latest_fetch fallback" if live_source == "latest_fetch" else None,
        "websocket_stale_alert": bool(live_health.get("websocket_stale_alert")),
        "websocket_stale_seconds": live_health.get("websocket_stale_seconds"),
        "signal": latest_signal.get("signal"),
        "signal_status": latest_signal.get("status"),
        "entry_price": latest_signal.get("entry_price"),
        "tp_price": latest_signal.get("tp_price"),
        "sl_price": latest_signal.get("sl_price"),
        "confidence_pct": None
        if latest_signal.get("confidence") is None
        else float(latest_signal.get("confidence")) * 100.0,
        "direction": validation_body.get("forecast_direction") or latest_signal.get("direction"),
        "quality_status": validation_body.get("quality_status"),
        "last_prediction_time": latest_run.get("generated_at_utc") or metadata.get("generated_at_utc"),
        "last_prediction_run_id": latest_run.get("run_id"),
        "last_auto_prediction_time": scheduler_worker.get("updated_at"),
    }


def _status_warnings(postgres_snapshot: dict) -> list[str]:
    warnings: list[str] = []
    required_workers = {"prediction_scheduler", "validation_worker", "websocket_stream"}
    if str(os.getenv("ENABLE_AUTO_FINETUNE", "true")).strip().lower() in {"1", "true", "yes", "on"}:
        required_workers.add("auto_finetune_worker")
    trade_worker_enabled = str(
        os.getenv("ENABLE_TRADE_EXECUTION_WORKER", os.getenv("AUTO_EXECUTE_SIGNALS", "false"))
    ).strip().lower() in {"1", "true", "yes", "on"}
    if trade_worker_enabled:
        required_workers.add("trade_execution_worker")
    live_quote = postgres_snapshot.get("live_quote") or {}
    if live_quote.get("source") == "latest_fetch":
        warnings.append("Live price fallback active: source is latest_fetch (websocket stream unavailable or stale).")
    live_health = postgres_snapshot.get("live_health") or {}
    if live_health.get("websocket_stale_alert"):
        stale = live_health.get("websocket_stale_seconds")
        if stale is None:
            warnings.append("Websocket health warning: no websocket live quote or candle has been persisted yet.")
        else:
            warnings.append(f"Websocket health warning: last websocket live update is stale ({stale}s old).")
    for service_name, state in (postgres_snapshot.get("worker_statuses") or {}).items():
        status = str((state or {}).get("status") or "").upper()
        stale = bool((state or {}).get("stale_alert"))
        stale_seconds = (state or {}).get("stale_seconds")
        if service_name in required_workers and status in {"ERROR", "MISSING"}:
            warnings.append(f"Worker {service_name} status is {status}.")
        if service_name in required_workers and status == "STALE":
            warnings.append(f"Worker {service_name} heartbeat is stale ({stale_seconds}s).")
        if service_name in required_workers and stale and status == "OK":
            warnings.append(f"Worker {service_name} heartbeat appears stale ({stale_seconds}s).")
        if service_name == "maintenance_worker" and status == "ERROR":
            warnings.append(f"Worker {service_name} status is {status}.")

    signal_validation = postgres_snapshot.get("signal_validation") or {}
    if signal_validation.get("error") == "validation_tables_missing":
        warnings.append("Signal validation tables are missing. Run migrations to enable validation scoring.")

    final_signal = str(signal_validation.get("final_signal") or "").upper()
    blocked = bool(signal_validation.get("blocked"))
    block_reason = signal_validation.get("block_reason")
    if blocked:
        warnings.append(f"Signal is blocked by validation rules ({block_reason or 'UNKNOWN'}).")
    if final_signal == "VALIDATION_UNAVAILABLE":
        warnings.append("Signal validation is unavailable; actionable signal output is suppressed.")

    reason_codes = signal_validation.get("reason_codes") or []
    if "MISSING_HIGHER_TIMEFRAME_CONTEXT" in reason_codes:
        warnings.append("Higher-timeframe context is missing for signal validation.")
    if "HIGHER_TIMEFRAME_CONFLICT" in reason_codes:
        warnings.append("Signal blocked because required higher-timeframe confirmation conflicts with the candidate direction.")
    if "WIDE_SPREAD_OR_COST_UNKNOWN" in reason_codes:
        warnings.append("Signal blocked due to wide spread or unknown trading cost context.")
    if "EXTREME_VOLATILITY" in reason_codes:
        warnings.append("Signal blocked due to extreme volatility regime.")
    if "VERY_LOW_VOLUME" in reason_codes:
        warnings.append("Signal blocked due to very low volume context.")

    validation_summary = postgres_snapshot.get("signal_validation_summary") or {}
    total_runs = int(validation_summary.get("total_runs") or 0)

    def _ratio(name: str) -> float:
        try:
            return float(validation_summary.get(name) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    if total_runs >= 20:
        blocked_ratio = _ratio("blocked_ratio_pct")
        actionable_ratio = _ratio("actionable_ratio_pct")
        invalid_ratio = _ratio("invalid_5m_input_ratio_pct")
        edge_ratio = _ratio("edge_below_cost_ratio_pct")
        low_volume_ratio = _ratio("very_low_volume_ratio_pct")
        window_hours = int(validation_summary.get("window_hours") or 24)

        if blocked_ratio >= 70.0:
            warnings.append(
                f"Validation blocker alert: {blocked_ratio:.1f}% of runs were blocked in the last {window_hours}h ({total_runs} runs)."
            )
        if actionable_ratio <= 15.0:
            warnings.append(
                f"Validation throughput alert: only {actionable_ratio:.1f}% actionable runs in the last {window_hours}h."
            )
        if invalid_ratio >= 35.0:
            warnings.append(
                f"Input integrity alert: INVALID_5M_INPUT accounts for {invalid_ratio:.1f}% of validation runs in the last {window_hours}h."
            )
        if edge_ratio >= 20.0:
            warnings.append(
                f"Edge filter alert: FORECAST_EDGE_BELOW_COST accounts for {edge_ratio:.1f}% of validation runs in the last {window_hours}h."
            )
        if low_volume_ratio >= 20.0:
            warnings.append(
                f"Liquidity alert: VERY_LOW_VOLUME accounts for {low_volume_ratio:.1f}% of validation runs in the last {window_hours}h."
            )
    return warnings


def _dashboard_html() -> str:
    return dashboard_html()


def _html() -> str:
    return _dashboard_html()


class DashboardHandler(BaseHTTPRequestHandler):
    def _begin_request(self, method: str) -> None:
        request_id = self.headers.get("X-Request-ID") or new_correlation_id("req")
        self._request_id = request_id
        self._request_started = time.perf_counter()
        self._response_status = 500
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.request.start",
            request_id=request_id,
            method=method,
            path=self.path,
            client_ip=self.client_address[0] if self.client_address else None,
            user_agent=self.headers.get("User-Agent"),
        )

    def _finish_request(self, method: str) -> None:
        started = getattr(self, "_request_started", None)
        duration_ms = int((time.perf_counter() - started) * 1000) if started is not None else None
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.request.completed",
            request_id=getattr(self, "_request_id", None),
            method=method,
            path=self.path,
            status_code=getattr(self, "_response_status", None),
            duration_ms=duration_ms,
        )

    def do_GET(self) -> None:  # noqa: N802
        self._begin_request("GET")
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/":
                body = _html().encode("utf-8")
                self._response_status = 200
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/status":
                if not _require_auth(self):
                    return
                selected_symbol = (query.get("symbol", ["ETHUSD"])[0] or "ETHUSD").strip()
                selected_resolution = (query.get("resolution", ["MINUTE_5"])[0] or "MINUTE_5").strip().upper()
                if selected_resolution not in SUPPORTED_RESOLUTIONS:
                    _error_response(self, 400, "VALIDATION_ERROR", "Invalid resolution", {"field": "resolution"})
                    return
                metadata_path, metadata = _latest_metadata(selected_symbol, selected_resolution)
                quality_path, quality_report = _quality_report_for_metadata(metadata_path, metadata)
                forecast = _safe_csv(metadata.get("forecast_csv_path"))
                input_tail = _safe_csv(metadata.get("input_csv_path"), limit=100)
                latest_actual = _latest_file(f"actual_for_forecast_{metadata.get('epic', 'ETHUSD')}_{metadata.get('resolution', 'MINUTE_5')}_*.csv")
                actual_tail = _safe_csv(latest_actual, limit=100) or input_tail
                baseline_reports = sorted(OUTPUT_DIR.glob("forecast_quality_report_BASELINE_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                baseline_summary = {p.stem: _safe_json(p).get("forecast_quality_validation", {}) for p in baseline_reports[:6]}
                postgres_snapshot = _postgres_snapshot(selected_symbol, selected_resolution)
                auto_finetune = _auto_finetune_status()
                validation_from_db = postgres_snapshot.get("latest_validation") or {}
                signal_validation = postgres_snapshot.get("signal_validation") or {}
                timeframe_validations = postgres_snapshot.get("timeframe_validations") or []
                if quality_report:
                    validation_body = quality_report.get("forecast_quality_validation", quality_report)
                else:
                    validation_body = {}
                validation_body = _merge_validation(validation_body, validation_from_db)
                postgres_candles = postgres_snapshot.get("candles") or []
                market_tail = [
                    {("timestamps" if k == "timestamp_utc" else k): v for k, v in row.items()}
                    for row in postgres_candles[-100:]
                ]
                validation_source = "quality_report" if quality_path else ("prediction_outcomes" if validation_from_db else "none")
                _json_response(
                    self,
                    200,
                    {
                        "metadata": metadata,
                        "validation": validation_body,
                        "signal_validation": signal_validation,
                        "timeframe_validations": timeframe_validations,
                        "forecast": forecast,
                        "input_tail": input_tail,
                        "actual_tail": actual_tail,
                        "market_tail": market_tail,
                        "history": _history(),
                        "prediction_db": postgres_snapshot.get("prediction_db", _prediction_db_summary()),
                        "postgres_snapshot": postgres_snapshot,
                        "live_quote": postgres_snapshot.get("live_quote"),
                        "live_health": postgres_snapshot.get("live_health"),
                        "worker_statuses": postgres_snapshot.get("worker_statuses"),
                        "active_model": postgres_snapshot.get("active_model"),
                        "shadow_model": postgres_snapshot.get("shadow_model"),
                        "rate_limits": postgres_snapshot.get("rate_limits"),
                        "supervisor_lease": postgres_snapshot.get("supervisor_lease"),
                        "horizon_metrics": postgres_snapshot.get("horizon_metrics"),
                        "auto_finetune": auto_finetune,
                        "trade_execution": _trade_execution_status(),
                        "human_summary": _human_summary(metadata, validation_body, postgres_snapshot),
                        "baseline_summary": baseline_summary,
                        "validation_source": validation_source,
                        "status_warnings": _status_warnings(postgres_snapshot),
                        "selected_symbol": selected_symbol,
                        "selected_resolution": selected_resolution,
                        "files": {
                            "metadata": str(metadata_path) if metadata_path else None,
                            "input": metadata.get("input_csv_path"),
                            "forecast": metadata.get("forecast_csv_path"),
                            "validation": str(quality_path) if quality_path else metadata.get("validation_report_path"),
                            "latest_actual": str(latest_actual) if latest_actual else None,
                        },
                    },
                )
                return
            if parsed.path == "/api/signals":
                if not _require_auth(self):
                    return
                symbol = (query.get("symbol", ["ETHUSD"])[0] or "ETHUSD").strip()
                resolution = (query.get("timeframe", [query.get("resolution", [""])[0]])[0] or "").strip().upper() or None
                date_from = (query.get("date_from", [""])[0] or "").strip() or None
                date_to = (query.get("date_to", [""])[0] or "").strip() or None
                direction = (query.get("direction", [""])[0] or "").strip() or None
                status = (query.get("status", [""])[0] or "").strip() or None
                signal_id = (query.get("signal_id", [""])[0] or "").strip() or None
                try:
                    page = int((query.get("page", ["1"])[0] or "1").strip() or "1")
                except ValueError:
                    page = 1
                try:
                    page_size = int((query.get("page_size", ["10"])[0] or "10").strip() or "10")
                except ValueError:
                    page_size = 10
                _json_response(
                    self,
                    200,
                    query_signals(
                        symbol=symbol,
                        resolution=resolution,
                        date_from=date_from,
                        date_to=date_to,
                        direction=direction,
                        status=status,
                        signal_id=signal_id,
                        page=page,
                        page_size=page_size,
                    ),
                )
                return
            if parsed.path == "/api/model-performance":
                if not _require_auth(self):
                    return
                symbol = (query.get("symbol", ["ETHUSD"])[0] or "ETHUSD").strip()
                resolution = (query.get("resolution", ["MINUTE_5"])[0] or "MINUTE_5").strip().upper()
                model_version_id = (query.get("model_version_id", [""])[0] or "").strip() or None
                try:
                    _json_response(
                        self,
                        200,
                        model_performance(symbol=symbol, resolution=resolution, model_version_id=model_version_id),
                    )
                except Exception as exc:  # noqa: BLE001
                    _error_response(self, 503, "DATABASE_ERROR", "Unable to load model performance", {"reason": str(exc)})
                return
            if parsed.path == "/api/model-versions":
                if not _require_auth(self):
                    return
                try:
                    _json_response(self, 200, list_model_versions())
                except Exception as exc:  # noqa: BLE001
                    _error_response(self, 503, "DATABASE_ERROR", "Unable to load model versions", {"reason": str(exc)})
                return
            if parsed.path == "/api/trade-execution/status":
                if not _require_auth(self):
                    return
                _json_response(self, 200, _trade_execution_status())
                return
            if parsed.path == "/api/trades":
                if not _require_auth(self):
                    return
                try:
                    limit = int(query.get("limit", ["50"])[0] or 50)
                except ValueError:
                    limit = 50
                try:
                    _json_response(self, 200, {"rows": TradeExecutionRepository().executed_trades(limit=max(1, min(limit, 200)))})
                except Exception as exc:  # noqa: BLE001
                    _error_response(self, 503, "DATABASE_ERROR", "Unable to load executed trades", {"reason": str(exc)})
                return
            if parsed.path == "/api/broker/account":
                if not _require_auth(self):
                    return
                _json_response(self, 200, _broker_account_snapshot())
                return
            if parsed.path == "/api/broker/positions":
                if not _require_auth(self):
                    return
                try:
                    client = CapitalTradingClient()
                    _json_response(self, 200, {"ok": True, "open_positions": client.get_open_positions()})
                except Exception as exc:  # noqa: BLE001
                    _json_response(self, 200, {"ok": False, "error": str(exc), "open_positions": []})
                return
            if parsed.path.startswith("/api/walk-forward-experiments/"):
                if not _require_auth(self):
                    return
                experiment_id = parsed.path.rsplit("/", 1)[-1]
                try:
                    payload = get_walk_forward_experiment(experiment_id)
                    if not payload:
                        _error_response(self, 404, "NOT_FOUND", "Walk-forward experiment not found", {"experiment_id": experiment_id})
                        return
                    _json_response(self, 200, payload)
                except Exception as exc:  # noqa: BLE001
                    _error_response(self, 503, "DATABASE_ERROR", "Unable to load walk-forward experiment", {"reason": str(exc)})
                return
            if parsed.path == "/file":
                target = parse_qs(parsed.query).get("path", [""])[0]
                try:
                    if not target:
                        raise FileNotFoundError
                    resolved = _resolve_path_within_root(target)
                    body = resolved.read_bytes()
                except (FileNotFoundError, ValueError):
                    self._response_status = 404
                    self.send_error(404)
                    return
                self._response_status = 200
                self.send_response(200)
                self.send_header("Content-Type", _content_type(resolved))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._response_status = 404
            self.send_error(404)
        except Exception as exc:  # noqa: BLE001
            log_event(
                LOGGER,
                logging.ERROR,
                "dashboard.request.error",
                request_id=getattr(self, "_request_id", None),
                method="GET",
                path=self.path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _error_response(self, 500, "INTERNAL_ERROR", "Unhandled server error", {"reason": str(exc)})
        finally:
            self._finish_request("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._begin_request("POST")
        try:
            if not _require_auth(self):
                return
            parsed = urlparse(self.path)
            payload = _validated_payload(self)
            if payload is None:
                return
            if parsed.path == "/api/predict":
                self._predict(payload)
                return
            if parsed.path == "/api/fetch-actual":
                self._fetch_actual(payload)
                return
            if parsed.path == "/api/validate-actual":
                self._validate_actual(payload)
                return
            if parsed.path == "/api/baselines":
                self._baselines(payload)
                return
            if parsed.path == "/api/dataset-snapshots":
                self._dataset_snapshot(payload)
                return
            if parsed.path == "/api/walk-forward-experiments":
                self._walk_forward(payload)
                return
            if parsed.path.startswith("/api/model-versions/") and parsed.path.endswith("/evaluate-promotion"):
                model_version_id = parsed.path.split("/")[-2]
                self._evaluate_promotion(model_version_id, payload)
                return
            if parsed.path == "/api/trade-execution/execute-signal":
                self._execute_signal(payload)
                return
            if parsed.path == "/api/trade-execution/drain":
                self._drain_trade_execution_queue()
                return
            if parsed.path == "/api/trade-execution/force-close":
                self._force_close_trade(payload)
                return
            if parsed.path == "/api/trade-execution/transaction-history":
                self._fetch_trade_transaction(payload)
                return
            self._response_status = 404
            self.send_error(404)
        except Exception as exc:  # noqa: BLE001
            log_event(
                LOGGER,
                logging.ERROR,
                "dashboard.request.error",
                request_id=getattr(self, "_request_id", None),
                method="POST",
                path=self.path,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            _error_response(self, 500, "INTERNAL_ERROR", "Unhandled server error", {"reason": str(exc)})
        finally:
            self._finish_request("POST")

    def _predict(self, payload: dict) -> None:
        request_id = getattr(self, "_request_id", None)
        market = str(payload.get("market", "ETHUSD")).strip()
        symbol = str(payload.get("symbol") or market).strip()
        resolution = str(payload.get("resolution", "MINUTE_5")).strip().upper()
        feature_set = str(payload.get("feature_set", "auto")).strip()
        try:
            pred_len_int = int(payload.get("pred_len", 12))
            lookback_int = int(payload.get("lookback", 512))
        except (TypeError, ValueError):
            _error_response(self, 400, "VALIDATION_ERROR", "pred_len and lookback must be integers")
            return
        if not market or len(market) > 64 or not symbol or len(symbol) > 64:
            _error_response(self, 400, "VALIDATION_ERROR", "market and symbol are required", {"field": "market"})
            return
        if resolution not in SUPPORTED_RESOLUTIONS:
            _error_response(self, 400, "VALIDATION_ERROR", "Unsupported resolution", {"field": "resolution"})
            return
        if not (1 <= pred_len_int <= 96) or not (50 <= lookback_int <= 2048):
            _error_response(self, 400, "VALIDATION_ERROR", "pred_len or lookback out of range")
            return
        if feature_set not in {"auto", "ohlc", "ohlcv", "ohlcva"}:
            _error_response(self, 400, "VALIDATION_ERROR", "Unsupported feature_set", {"field": "feature_set"})
            return
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.action.predict.start",
            request_id=request_id,
            market=market,
            symbol=symbol,
            resolution=resolution,
            feature_set=feature_set,
        )
        pred_len = str(pred_len_int)
        lookback = str(lookback_int)
        repair = bool(payload.get("repair_ohlc", True))
        run_shadow = bool(payload.get("run_shadow", True))
        cmd = [
            sys.executable,
            "src/main_forecast_latest.py",
            "--market",
            market,
            "--symbol",
            symbol,
            "--resolution",
            resolution,
            "--max",
            "512",
            "--lookback",
            lookback,
            "--pred-len",
            pred_len,
            "--price-side",
            "mid",
            "--env",
            "demo",
            "--feature-set",
            feature_set,
        ]
        if repair:
            cmd.append("--repair-ohlc")
        if not run_shadow:
            cmd.append("--disable-shadow-model")
        result = _run(cmd, request_id=request_id, endpoint="/api/predict")
        report_url = None
        report_path = None
        if result["returncode"] == 0:
            metadata_path = _latest_file(f"forecast_metadata_{market}_*.json") or _latest_file("forecast_metadata_*.json")
            if metadata_path:
                metadata = _safe_json(metadata_path)
                forecast_path = ROOT / metadata["forecast_csv_path"]
                validation_path = ROOT / metadata["validation_report_path"]
                stamp = _metadata_stamp(metadata_path)
                report_path = OUTPUT_DIR / f"prediction_log_report_{metadata['epic']}_{metadata['resolution']}_{stamp}.html"
                generate_prediction_log_report(forecast_path, metadata_path, validation_path, report_path)
                report_url = f"/file?path={report_path.relative_to(ROOT).as_posix()}"
        log_event(
            LOGGER,
            logging.INFO if result["returncode"] == 0 else logging.WARNING,
            "dashboard.action.predict.completed",
            request_id=request_id,
            market=market,
            symbol=symbol,
            resolution=resolution,
            returncode=int(result["returncode"]),
            report_path=str(report_path) if report_path else None,
        )
        _json_response(
            self,
            200 if result["returncode"] == 0 else 500,
            {
                **result,
                "status": "completed" if result["returncode"] == 0 else "failed",
                "error": None if result["returncode"] == 0 else result["output"],
                "report_path": str(report_path) if report_path else None,
                "report_url": report_url,
            },
        )

    def _fetch_actual(self, payload: dict) -> None:
        request_id = getattr(self, "_request_id", None)
        try:
            symbol, resolution = _action_context(payload)
        except ValueError as exc:
            _error_response(self, 400, "VALIDATION_ERROR", str(exc))
            return
        run_id = (payload.get("run_id") or "").strip() or None
        metadata_path, _ = _metadata_for_run_id(run_id, symbol=symbol, resolution=resolution)
        if not metadata_path:
            _error_response(
                self,
                404,
                "NOT_FOUND",
                "No forecast metadata found for selected context",
                {"run_id": run_id, "symbol": symbol, "resolution": resolution},
            )
            return
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.action.fetch_actual.start",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            metadata_path=str(metadata_path),
        )
        result = _run(
            [
                sys.executable,
                "src/main_fetch_actual_for_forecast.py",
                "--metadata",
                str(metadata_path),
                "--price-side",
                "mid",
                "--env",
                "demo",
                "--buffer-candles",
                "2",
                "--allow-partial",
            ],
            timeout=180,
            request_id=request_id,
            endpoint="/api/fetch-actual",
        )
        log_event(
            LOGGER,
            logging.INFO if result["returncode"] == 0 else logging.WARNING,
            "dashboard.action.fetch_actual.completed",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            returncode=int(result["returncode"]),
        )
        _json_response(self, 200 if result["returncode"] == 0 else 500, {"status": "completed" if result["returncode"] == 0 else "failed", "run_id": run_id, **result})

    def _validate_actual(self, payload: dict) -> None:
        request_id = getattr(self, "_request_id", None)
        try:
            symbol, resolution = _action_context(payload)
        except ValueError as exc:
            _error_response(self, 400, "VALIDATION_ERROR", str(exc))
            return
        run_id = (payload.get("run_id") or "").strip() or None
        metadata_path, metadata = _metadata_for_run_id(run_id, symbol=symbol, resolution=resolution)
        if not metadata_path:
            _error_response(
                self,
                404,
                "NOT_FOUND",
                "No forecast metadata found for selected context",
                {"run_id": run_id, "symbol": symbol, "resolution": resolution},
            )
            return
        stamp = _metadata_stamp(metadata_path)
        epic = metadata.get("epic", "ETHUSD")
        resolution = metadata.get("resolution", "MINUTE_5")
        actual = OUTPUT_DIR / f"actual_for_forecast_{epic}_{resolution}_{stamp}.csv"
        if not actual.exists():
            _error_response(self, 404, "NOT_FOUND", f"Actual CSV not found: {actual}", {"run_id": run_id})
            return
        validate_cmd = [
                sys.executable,
                "src/main_validate_forecast_quality.py",
                "--forecast",
                metadata["forecast_csv_path"],
                "--actual",
                str(actual),
                "--resolution",
                resolution,
                "--price-side",
                metadata.get("price_side", "mid"),
                "--epic",
                epic,
                "--metadata",
                str(metadata_path),
                "--output",
                str(OUTPUT_DIR / f"forecast_quality_report_{epic}_{resolution}_{stamp}.json"),
        ]
        if run_id:
            validate_cmd.extend(["--run-id", run_id])
        if payload.get("scoring_version"):
            validate_cmd.extend(["--scoring-version", str(payload.get("scoring_version"))])
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.action.validate_actual.start",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            metadata_path=str(metadata_path),
            actual_path=str(actual),
        )
        result = _run(
            validate_cmd,
            timeout=180,
            request_id=request_id,
            endpoint="/api/validate-actual",
        )
        log_event(
            LOGGER,
            logging.INFO if result["returncode"] == 0 else logging.WARNING,
            "dashboard.action.validate_actual.completed",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            returncode=int(result["returncode"]),
        )
        _json_response(self, 200 if result["returncode"] == 0 else 500, result)

    def _baselines(self, payload: dict) -> None:
        request_id = getattr(self, "_request_id", None)
        try:
            symbol, resolution = _action_context(payload)
        except ValueError as exc:
            _error_response(self, 400, "VALIDATION_ERROR", str(exc))
            return
        run_id = (payload.get("run_id") or "").strip() or None
        metadata_path, metadata = _metadata_for_run_id(run_id, symbol=symbol, resolution=resolution)
        if not metadata_path:
            _error_response(
                self,
                404,
                "NOT_FOUND",
                "No forecast metadata found for selected context",
                {"run_id": run_id, "symbol": symbol, "resolution": resolution},
            )
            return
        stamp = _metadata_stamp(metadata_path)
        epic = metadata.get("epic", "ETHUSD")
        resolution = metadata.get("resolution", "MINUTE_5")
        actual = OUTPUT_DIR / f"actual_for_forecast_{epic}_{resolution}_{stamp}.csv"
        methods = ["naive", "moving_average", "drift", "last_direction"]
        logs: list[str] = []
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.action.baselines.start",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            methods=methods,
        )
        for method in methods:
            baseline_csv = OUTPUT_DIR / f"baseline_{method}_{epic}_{resolution}_{stamp}.csv"
            generated = _run(
                [
                    sys.executable,
                    "src/main_generate_baseline_forecasts.py",
                    "--input",
                    metadata["input_csv_path"],
                    "--resolution",
                    resolution,
                    "--pred-len",
                    str(metadata.get("forecast_rows", 12)),
                    "--method",
                    method,
                    "--output",
                    str(baseline_csv),
                ],
                timeout=120,
                request_id=request_id,
                endpoint="/api/baselines",
            )
            logs.append(generated["output"])
            if generated["returncode"] == 0 and actual.exists():
                validated = _run(
                    [
                        sys.executable,
                        "src/main_validate_forecast_quality.py",
                        "--forecast",
                        str(baseline_csv),
                        "--actual",
                        str(actual),
                        "--resolution",
                        resolution,
                        "--price-side",
                        metadata.get("price_side", "mid"),
                        "--epic",
                        epic,
                        "--output",
                        str(OUTPUT_DIR / f"forecast_quality_report_BASELINE_{method}_{epic}_{resolution}_{stamp}.json"),
                    ],
                    timeout=120,
                    request_id=request_id,
                    endpoint="/api/baselines",
                )
                logs.append(validated["output"])
        log_event(
            LOGGER,
            logging.INFO,
            "dashboard.action.baselines.completed",
            request_id=request_id,
            run_id=run_id,
            symbol=symbol,
            resolution=resolution,
            returncode=0,
        )
        _json_response(self, 200, {"returncode": 0, "output": "\n".join(logs)})

    def _dataset_snapshot(self, payload: dict) -> None:
        required = ["dataset_role", "symbol", "resolution", "start_timestamp_utc", "end_timestamp_utc"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            _error_response(self, 400, "VALIDATION_ERROR", "Missing required dataset snapshot fields", {"missing": missing})
            return
        try:
            result = create_dataset_snapshot(
                dataset_role=str(payload["dataset_role"]),
                symbol=str(payload["symbol"]),
                resolution=str(payload["resolution"]).upper(),
                price_side=str(payload.get("price_side", "mid")),
                start_timestamp_utc=str(payload["start_timestamp_utc"]),
                end_timestamp_utc=str(payload["end_timestamp_utc"]),
                feature_set_id=payload.get("feature_set_id", "raw-ohlcv-v1"),
                source_filter=payload.get("source_filter") or {},
                quality_filter=payload.get("quality_filter") or {},
                output_dir=OUTPUT_DIR / "datasets",
            )
            _json_response(self, 201, result)
        except ValueError as exc:
            _error_response(self, 400, "VALIDATION_ERROR", str(exc))
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "DATABASE_ERROR", "Dataset snapshot failed", {"reason": str(exc)})

    def _walk_forward(self, payload: dict) -> None:
        required = ["symbol", "resolution", "start_timestamp_utc", "end_timestamp_utc", "lookback", "pred_len", "stride"]
        missing = [field for field in required if payload.get(field) in (None, "")]
        if missing:
            _error_response(self, 400, "VALIDATION_ERROR", "Missing required walk-forward fields", {"missing": missing})
            return
        try:
            result = create_walk_forward_experiment(
                symbol=str(payload["symbol"]),
                resolution=str(payload["resolution"]).upper(),
                price_side=str(payload.get("price_side", "mid")),
                model_version_id=payload.get("model_version_id"),
                start_timestamp_utc=str(payload["start_timestamp_utc"]),
                end_timestamp_utc=str(payload["end_timestamp_utc"]),
                lookback=int(payload["lookback"]),
                pred_len=int(payload["pred_len"]),
                stride=int(payload["stride"]),
                feature_set_id=payload.get("feature_set_id", "raw-ohlcv-v1"),
                baselines=list(payload.get("baselines") or ["naive"]),
                output_dir=OUTPUT_DIR / "walk_forward",
            )
            threading.Thread(target=run_walk_forward_experiment, args=(result["experiment_id"],), daemon=True).start()
            _json_response(self, 202, result)
        except ValueError as exc:
            _error_response(self, 400, "VALIDATION_ERROR", str(exc))
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "DATABASE_ERROR", "Walk-forward experiment failed", {"reason": str(exc)})

    def _evaluate_promotion(self, model_version_id: str, payload: dict) -> None:
        try:
            result = evaluate_promotion(
                model_version_id=model_version_id,
                scoring_version=str(payload.get("scoring_version", "v1")),
                min_shadow_samples=int(payload.get("min_shadow_samples", 100)),
                min_direction_accuracy_pct=float(payload.get("min_direction_accuracy_pct", 55.0)),
                min_actionable_precision_pct=float(payload.get("min_actionable_precision_pct", 55.0)),
                max_mape_regression_pct=float(payload.get("max_mape_regression_pct", 5.0)),
                required_horizons=[int(value) for value in payload.get("required_horizons", [])],
            )
            _json_response(self, 200, result)
        except ValueError as exc:
            _error_response(self, 404, "NOT_FOUND", str(exc), {"model_version_id": model_version_id})
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "DATABASE_ERROR", "Promotion evaluation failed", {"reason": str(exc)})

    def _execute_signal(self, payload: dict) -> None:
        signal_id = str(payload.get("signal_id") or payload.get("run_id") or "").strip()
        if not signal_id:
            _error_response(self, 400, "VALIDATION_ERROR", "signal_id or run_id is required")
            return
        requested_size = None
        if payload.get("requested_size") not in (None, ""):
            try:
                requested_size = Decimal(str(payload.get("requested_size")))
            except (InvalidOperation, ValueError):
                _error_response(self, 400, "VALIDATION_ERROR", "requested_size must be numeric")
                return
        try:
            result = enqueue_signal_for_execution(
                signal_id,
                requested_by="manual",
                require_auto_enabled=False,
                requested_size=requested_size,
                force_market_execution=bool(payload.get("force_market_execution")),
            )
            _json_response(self, 202 if result.get("accepted") else 200, result)
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "TRADE_EXECUTION_ERROR", "Unable to queue signal execution", {"reason": str(exc)})

    def _drain_trade_execution_queue(self) -> None:
        try:
            queue = TradeExecutionQueueService()
            drained = queue.drain_once()
            _json_response(self, 200, {"ok": True, "drained": drained, "queue": queue.snapshot()})
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "TRADE_EXECUTION_ERROR", "Unable to drain trade execution queue", {"reason": str(exc)})

    def _force_close_trade(self, payload: dict) -> None:
        try:
            executed_trade_id = int(payload.get("executed_trade_id") or payload.get("trade_id"))
        except (TypeError, ValueError):
            _error_response(self, 400, "VALIDATION_ERROR", "executed_trade_id is required")
            return
        try:
            service = TradeExecutionService()
            result = service.force_close(executed_trade_id)
            _json_response(self, 200 if result.get("success") else 409, result)
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "TRADE_EXECUTION_ERROR", "Unable to force close demo trade", {"reason": str(exc)})

    def _fetch_trade_transaction(self, payload: dict) -> None:
        executed_trade_id = None
        if payload.get("executed_trade_id") not in (None, ""):
            try:
                executed_trade_id = int(payload.get("executed_trade_id"))
            except (TypeError, ValueError):
                _error_response(self, 400, "VALIDATION_ERROR", "executed_trade_id must be an integer")
                return
        deal_id = str(payload.get("deal_id") or "").strip() or None
        if executed_trade_id is None and not deal_id:
            _error_response(self, 400, "VALIDATION_ERROR", "executed_trade_id or deal_id is required")
            return
        try:
            service = TradeExecutionService()
            result = service.fetch_transaction_reference(executed_trade_id=executed_trade_id, deal_id=deal_id)
            _json_response(self, 200 if result.get("success") else 404, result)
        except Exception as exc:  # noqa: BLE001
            _error_response(self, 503, "TRADE_EXECUTION_ERROR", "Unable to fetch Capital.com transaction history", {"reason": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start local Capital.com Kronos dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open the dashboard in the default browser.")
    return parser.parse_args()


def main() -> None:
    configure_logging(service_name="dashboard_server")
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    log_event(
        LOGGER,
        logging.INFO,
        "dashboard.server.start",
        host=args.host,
        port=args.port,
        url=url,
        auto_open=not args.no_open,
    )
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event(LOGGER, logging.INFO, "dashboard.server.stop", reason="KeyboardInterrupt")
    finally:
        server.server_close()
        log_event(LOGGER, logging.INFO, "dashboard.server.stopped", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
