# Logging And Observability Audit

Scope: PHASE 0 logging audit for the current branch, focused strictly on runtime observability and log safety (no feature-logic expansion).

## 1) Files already using logging

Core modules with logger usage:
- src/capital_auth.py
- src/capital_rest_client.py
- src/capital_ws_ohlc_client.py
- src/main_stream_ohlc.py
- src/main_prediction_scheduler.py
- src/main_validation_worker.py
- src/main_auto_finetune_worker.py
- src/main_maintenance_worker.py

Logging bootstrap present:
- src/config.py (configure_logging with Rich + optional rotating file)

Service scripts already passing service_name to configure_logging:
- src/main_stream_ohlc.py
- src/main_prediction_scheduler.py
- src/main_validation_worker.py
- src/main_auto_finetune_worker.py
- src/main_maintenance_worker.py
- src/main_backfill_historical_5m.py

Scripts calling configure_logging() without service_name (console only today):
- src/main_fetch_historical.py
- src/main_fetch_historical_range.py
- src/main_fetch_actual_for_forecast.py
- src/main_forecast_latest.py
- src/main_prepare_kronos_input.py

## 2) Files still using print() for important runtime steps

High-impact runtime workflows still print major milestones instead of structured logs:
- src/main_run_kronos_predict.py (model loading, predict, validation report, artifact paths)
- src/main_forecast_latest.py (fetch lifecycle, subprocess retry path, shadow path, completion summary)
- src/main_stream_ohlc.py (startup and stop lifecycle summaries)
- src/main_fetch_historical.py
- src/main_fetch_historical_range.py
- src/main_fetch_actual_for_forecast.py
- src/main_validate_forecast_quality.py
- src/main_db_migrate.py
- src/main_backfill_historical_5m.py
- src/dashboard_server.py (server start/stop)

Note: final CLI summaries are useful and should remain, but key runtime transitions need logs in addition to final prints.

## 3) Files silently swallowing exceptions

Observed broad exception handlers with low/no observability detail:
- src/prediction_store.py (contains an explicit pass in exception handling path)
- src/dashboard_server.py (KeyboardInterrupt path with pass)
- src/dashboard_db.py (multiple broad exception handlers returning fallbacks)
- src/main_fetch_actual_for_forecast.py (DB fallback branch on broad exception)
- src/main_forecast_latest.py (shadow candidate status read path)
- src/main_auto_finetune_worker.py (status and metrics helper paths)
- src/main_maintenance_worker.py (heartbeat and state helpers)
- src/main_prediction_scheduler.py (websocket gate DB path)
- src/main_stream_ohlc.py (heartbeat write failure path)

## 4) Files missing operation duration logging

Most modules do not consistently log elapsed time for major operations. Missing/partial duration coverage in:
- src/capital_auth.py (auth/refresh timing)
- src/capital_rest_client.py (request lifecycle durations)
- src/main_run_kronos_predict.py (input read/validate/model load/predict/save)
- src/main_forecast_latest.py (market resolve/fetch/upsert/subprocess/shadow)
- src/main_prediction_scheduler.py (cycle/subprocess/sleep durations)
- src/main_validation_worker.py (cycle/per-run child-process durations)
- src/dashboard_server.py (request duration per endpoint)
- src/dashboard_db.py (snapshot/query duration)
- src/db.py + src/main_db_migrate.py (connect/healthcheck/migration durations)
- src/prediction_store.py (upsert/save/update durations)

## 5) Files missing run_id/request_id/correlation IDs

Correlation is inconsistent or absent across workflows:
- Dashboard request handlers: no request_id in logs because request lifecycle logging is absent.
- Scheduler cycles: no explicit scheduler_cycle_id despite looped service behavior.
- Validation cycles: no explicit validation_cycle_id.
- WebSocket sessions: no explicit websocket_session_id.
- Migration runs: no migration_run_id.
- Prediction process (forecast_latest -> run_kronos_predict): no generated prediction_request_id that propagates through all logs.

Business run_id values exist in DB logic; they should be preserved and supplemented with observability correlation IDs.

## 6) Files that may expose secrets in logs

Potential or latent risk areas (current and future):
- src/capital_auth.py
  - Handles identifier/password/api key and session tokens (CST, X-SECURITY-TOKEN).
- src/capital_rest_client.py
  - Handles authenticated requests and response error text.
- src/capital_ws_ohlc_client.py
  - Builds payloads containing cst/securityToken for websocket operations.
- src/dashboard_server.py
  - Reads Authorization header for API token auth checks.
- src/db.py and many CLI args
  - DSN values are widely passed around; any naive logging of full args can leak passwords.
- Subprocess callers (scheduler/validation/forecast/dashboard actions)
  - Command-line logging without sanitization could leak --postgres-dsn or token-like args.

Mitigation needed: centralized masking for dicts, DSNs, commands, and output tails.

## 7) Long-running services that need rotating file logs

Long-running services requiring stable rotating logs:
- src/main_prediction_scheduler.py
- src/main_validation_worker.py
- src/main_stream_ohlc.py
- src/main_auto_finetune_worker.py
- src/main_maintenance_worker.py
- src/dashboard_server.py
- src/main_backfill_historical_5m.py (can run lengthy and should write service log)

Most worker services already pass service_name; dashboard server currently does not initialize logging.

## 8) Subprocess callers that need command/output-tail logging

Subprocess-heavy modules needing standardized safe command + output tail logging:
- src/main_forecast_latest.py
  - Runs main_run_kronos_predict.py (including retry with --repair-ohlc), and shadow subprocess.
- src/main_prediction_scheduler.py
  - Runs main_forecast_latest.py in cycle, includes retry path on rate-limit-like output.
- src/main_validation_worker.py
  - Runs main_fetch_actual_for_forecast.py and main_validate_forecast_quality.py per due run.
- src/dashboard_server.py
  - Runs multiple actions for predict/fetch/validate/baselines.
- src/main_auto_finetune_worker.py
  - Runs configured finetune command and persists output tail.

## 9) Database operations that need failure logs

High-value DB operations needing explicit start/success/failure event logs:
- src/db.py
  - connect(), healthcheck(), run_migrations().
- src/main_db_migrate.py
  - migration CLI lifecycle.
- src/prediction_store.py
  - instrument upsert, OHLCV upsert, prediction run save, outcomes update, shadow status refresh.
- src/dashboard_db.py
  - snapshot and metrics queries.
- src/service_runtime.py
  - heartbeat write path (currently best-effort caller-side logging only).

## 10) Dashboard endpoints that need request logs

src/dashboard_server.py currently lacks request lifecycle logs. Needed coverage:
- Global request start/completed/error for all routes.
- Endpoint-level observability for:
  - /api/status
  - /api/predict
  - /api/fetch-actual
  - /api/validate-actual
  - /api/baselines
  - /api/model-performance
  - /api/model-versions
  - /api/walk-forward-experiments
  - /api/dataset-snapshots
  - /api/model-versions/{id}/evaluate-promotion

Needed fields: request_id, method, path, status_code, duration_ms, query_keys, safe payload summary, and subprocess output tail on failures.

## 11) Recommended files to change in this PR

Shared/logging infrastructure:
- src/logging_utils.py (new)
- src/subprocess_utils.py (new)
- src/config.py

Core runtime and data flow:
- src/capital_auth.py
- src/capital_rest_client.py
- src/capital_ws_ohlc_client.py
- src/main_stream_ohlc.py
- src/main_prediction_scheduler.py
- src/main_validation_worker.py
- src/main_forecast_latest.py
- src/main_run_kronos_predict.py
- src/prediction_store.py
- src/db.py
- src/main_db_migrate.py
- src/service_runtime.py

Dashboard:
- src/dashboard_server.py
- src/dashboard_db.py

One-off/operational scripts:
- src/main_fetch_historical.py
- src/main_fetch_historical_range.py
- src/main_fetch_actual_for_forecast.py
- src/main_validate_forecast_quality.py
- src/main_backfill_historical_5m.py
- src/main_auto_finetune_worker.py
- src/main_maintenance_worker.py

Testing and docs:
- tests/test_logging_utils.py (new)
- tests/test_config_logging.py (new)
- tests/test_subprocess_utils.py (new)
- tests/test_dashboard_request_logging.py (new)
- tests/test_scheduler_validation_logging_ids.py (new)
- README.md
- docs/LOGGING_IMPLEMENTATION.md (new)
- docs/LOGGING_IMPLEMENTATION_SUMMARY.md (new)

## Audit conclusion

The codebase already has a workable logging foundation (Rich logging + file logs for some services), but observability is uneven and mostly unstructured across prediction/validation/dashboard subprocess workflows. The primary gaps are:
- missing standardized structured events,
- weak correlation IDs,
- insufficient duration and operation-step logging,
- inconsistent subprocess observability,
- and missing centralized secret masking.

The next phases should implement shared secure logging helpers, then instrument key services while preserving current behavior and keeping the system data-only.
