# Logging and Observability Implementation

## Scope

This implementation standardizes logging and observability for runtime orchestration, forecasting, validation, dashboard APIs, and supporting scripts.

The work is intentionally limited to:

- Structured logging
- Correlation IDs
- Subprocess instrumentation
- Safe secret masking
- Handler deduplication and environment-driven logging controls
- Documentation and tests

No forecasting logic, model behavior, promotion rules, or trading behavior was changed.

## Core Components

### 1) Structured logging helpers

File: `src/logging_utils.py`

Key helpers:

- `log_event(logger, level, event, **fields)`
- `new_correlation_id(prefix)`
- `timed_step(...)`
- `safe_log_dict(...)`
- `mask_secret(...)`
- `mask_dsn(...)`
- `safe_command_for_log(...)`
- `output_tail(...)`

Security behavior:

- Masks DSNs, tokens, passwords, authorization values, and similar sensitive fields.
- Sanitizes command arguments and output tails before logging.
- Truncates overly long string fields.

### 2) Subprocess observability helper

File: `src/subprocess_utils.py`

Key helper:

- `run_logged_subprocess(...)`

Behavior:

- Emits `*.start`, `*.completed`, `*.error`, and `*.timeout` events.
- Logs masked command arguments.
- Logs sanitized output tails on failure/timeouts.
- Includes duration and return code metadata.

### 3) Logging configuration upgrades

File: `src/config.py`

`configure_logging(...)` now supports:

- Idempotent handler setup (managed handler dedupe)
- Console/file toggles via environment
- JSON line output option for file logs
- Configurable file rollover size and retention

Environment controls:

- `LOG_LEVEL`
- `LOG_TO_CONSOLE`
- `LOG_TO_FILE`
- `LOG_JSON`
- `CAPITAL_LOG_DIR`
- `CAPITAL_LOG_MAX_BYTES`
- `CAPITAL_LOG_BACKUP_COUNT`

## Correlation IDs

Correlation IDs are generated with prefix-specific IDs:

- `pred_*` for forecast/prediction workflows
- `sched_*` for scheduler cycles
- `val_*` for validation cycles
- `req_*` for request/one-off operations

These IDs are propagated into structured event fields:

- `prediction_request_id`
- `scheduler_cycle_id`
- `validation_cycle_id`
- `request_id`

## Instrumented Runtime Modules

### Forecast pipeline

- `src/main_forecast_latest.py`
- `src/main_run_kronos_predict.py`
- `src/prediction_store.py`

Representative events:

- `forecast_latest.*`
- `kronos.*`
- `prediction_store.*`

### Workers

- `src/main_prediction_scheduler.py`
- `src/main_validation_worker.py`
- `src/main_stream_ohlc.py`

Representative events:

- `scheduler.*`
- `validation.*`
- `websocket.*`

### Capital clients and DB

- `src/capital_auth.py`
- `src/capital_rest_client.py`
- `src/capital_ws_ohlc_client.py`
- `src/db.py`
- `src/main_db_migrate.py`

Representative events:

- `capital.auth.*`
- `capital.rest.*`
- `websocket.*`
- `db.connect.*`, `db.migration.*`, `db.healthcheck.*`

### Dashboard

- `src/dashboard_server.py`
- `src/dashboard_db.py`

Representative events:

- `dashboard.request.start|completed|error`
- `dashboard.subprocess.*`
- `dashboard.action.*`
- `dashboard_db.query_signals.*`
- `dashboard_db.postgres_snapshot.*`

### One-off scripts

- `src/main_fetch_historical.py`
- `src/main_fetch_historical_range.py`
- `src/main_fetch_actual_for_forecast.py`
- `src/main_validate_forecast_quality.py`
- `src/main_backfill_historical_5m.py`

Representative events:

- `fetch_historical.*`
- `fetch_historical_range.*`
- `fetch_actual.*`
- `validate_forecast_quality.*`
- `historical_5m_backfill.*`

## Event Envelope

Structured events are JSON objects containing at minimum:

- `event`
- Context fields (symbol, epic, resolution, run IDs, status)
- Correlation IDs when applicable
- `duration_ms` on completed/error events

The default logger envelope from formatters includes timestamp/level/logger metadata.

## Verification

Focused tests executed:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_logging_observability tests.test_dashboard_server_security tests.test_prediction_scheduler_websocket_gate tests.test_validation_worker
```

Result: pass

## Notes

- Existing CLI summary `print(...)` output was preserved for operator workflows.
- Logging additions were implemented to avoid leaking credentials or tokens.
- The implementation is additive and observability-focused.
