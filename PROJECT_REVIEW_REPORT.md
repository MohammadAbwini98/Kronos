# PROJECT_REVIEW_REPORT.md

## 1. Executive Summary

Overall project health: Medium risk. The project is a coherent local Python data bridge with Capital.com ingestion, Kronos forecasting, PostgreSQL persistence, validation workers, maintenance workers, and a single-page Python-rendered dashboard. The code is readable and the intended workflow is clear, but several integration and business-logic seams can produce incorrect dashboard results, failed fresh installs, or misleading validation outcomes without throwing obvious errors.

Main risk areas:

- Dashboard UI/API contract mismatches.
- PostgreSQL configuration drift across Docker, `.env.example`, README, and code.
- Forecast validation logic duplicated with inconsistent rules.
- Weak database constraints and silent numeric coercion before persistence.
- Local dashboard security assumptions if bound outside localhost.
- Limited test coverage for end-to-end workflows, database migrations, and browser behavior.

Most critical issues found:

- App default PostgreSQL DSN does not match Docker credentials.
- The Baselines action button and Baselines tab panel share the same DOM `id`.
- Dashboard fetch/validate/baseline actions ignore the currently selected market and resolution.
- Frontend POST helpers show success even for HTTP 500 JSON responses.
- Forecast quality direction accuracy does not match database WIN/LOSS logic.
- Dashboard DB metrics mislabel a price error as a movement percentage.
- `/file` path containment uses unsafe string prefix matching.
- Invalid OHLC values can be coerced to zero before database persistence.

Recommended next actions:

- Fix the DSN mismatch, duplicate DOM id, failed-action handling, and selected-context handling first.
- Centralize direction/outcome calculations so reports, DB rows, and dashboard status agree.
- Add database constraints and reject invalid OHLC before insert/update.
- Add integration tests for migrations and dashboard API flows with seeded PostgreSQL data.
- Add a browser smoke test for dashboard tabs, controls, and failure states.

Review execution notes:

- Reviewed frontend dashboard HTML/JS, dashboard API server, Capital.com REST/WebSocket clients, scheduler, validation worker, auto-finetune worker, maintenance worker, PostgreSQL migrations, config files, README, and tests.
- Ran `.venv\Scripts\python.exe -m unittest discover -s tests -v`; all 16 existing tests passed.
- Did not call Capital.com APIs, run Docker, run Kronos inference, or apply migrations against a live database. Items needing those checks are marked `Needs verification`.
- Existing working tree was already dirty before this review. No source files were changed.

## 2. Critical Issues

### CR-001: Application default PostgreSQL DSN does not match Docker credentials

Severity: Critical

Area: Configuration / Database

File(s) affected:

- `src/db.py:13`
- `.env.example:12`
- `README.md:320`
- `docker-compose.yml:6-8`
- `start_dashboard.ps1:374-380`

Description:

The app default DSN is `postgresql://postgres:123@localhost:5432/capital_kronos`, while Docker creates `POSTGRES_USER=capital_kronos` and `POSTGRES_PASSWORD=capital_kronos`. `start_dashboard.ps1` runs migrations even when `POSTGRES_DSN` is missing, so a Docker-based setup can fail unless the user manually overrides the DSN.

Root cause:

Database credentials are duplicated and inconsistent across config, documentation, and runtime defaults.

Business or technical impact:

Fresh installs can fail at startup, migrations can fail, dashboard DB-backed features remain offline, and prediction persistence can fail despite the Docker container being healthy.

Recommended fix:

Use one canonical DSN. Either align `src/db.py`, `.env.example`, README, and Docker, or remove the hardcoded credential and require `POSTGRES_DSN`.

Verification steps:

- Run `docker compose up -d postgres`.
- Run `python src/main_db_migrate.py` with no `POSTGRES_DSN`.
- Confirm migrations succeed using the documented default path.

### CR-002: Baselines button and Baselines tab use the same DOM id

Severity: High

Area: Frontend

File(s) affected:

- `src/dashboard_ui.py:699`
- `src/dashboard_ui.py:741`
- `src/dashboard_ui.py:1465-1478`
- `src/dashboard_ui.py:1915`

Description:

The Run Baselines button and the Baselines tab panel both use `id="baselines"`. `document.getElementById('baselines')` can resolve to the button instead of the panel. `renderBaselines()` writes through `$('baselines').innerHTML`, so it can overwrite the button instead of rendering the tab content.

Root cause:

Duplicate HTML ids violate DOM uniqueness and mix action-control and content-panel responsibilities.

Business or technical impact:

The Baselines tab/action can render unpredictably, mutate the wrong DOM node, or fail to show baseline results.

Recommended fix:

Rename the action button to `runBaselines` and keep the tab panel as `baselines`, or rename the panel to `baselinesPanel` and update tab routing.

Verification steps:

- Open the dashboard.
- Click Run Baselines.
- Switch to the Baselines tab.
- Confirm the button remains intact and results render in the panel.

### CR-003: Dashboard action endpoints ignore selected market and resolution

Severity: High

Area: Frontend / Backend / Business Logic

File(s) affected:

- `src/dashboard_server.py:415-525`
- `src/dashboard_server.py:65-71`
- `src/dashboard_ui.py:1913-1915`

Description:

`_fetch_actual()`, `_validate_actual()`, and `_baselines()` call `_latest_metadata()` without passing the selected symbol/resolution. The UI sends empty POST payloads for these actions. If multiple markets or resolutions exist, actions can operate on fallback/latest metadata instead of the user's current selection.

Root cause:

The UI does not send selected context, and the backend action handlers use global latest metadata.

Business or technical impact:

Users can validate, fetch actuals, or generate baselines for the wrong forecast window, creating misleading quality reports and dashboard state.

Recommended fix:

Send `market` and `resolution` in POST payloads and use `_latest_metadata(symbol, resolution)` in action handlers. Return a clear 404/400 when no matching metadata exists.

Verification steps:

- Create forecasts for `ETHUSD MINUTE` and `ETHUSD MINUTE_5`.
- Select each resolution and run fetch/validate/baselines.
- Confirm output filenames and metadata stamps match the selected resolution.

### CR-004: Frontend treats failed POST actions as successful

Severity: High

Area: Frontend / API Contract

File(s) affected:

- `src/dashboard_ui.py:1706-1725`
- `src/dashboard_ui.py:1731-1763`
- `src/dashboard_server.py:409-413`
- `src/dashboard_server.py:436`
- `src/dashboard_server.py:471`

Description:

`postJson()` parses JSON but never checks `res.ok`. When the server returns HTTP 500 with JSON, the promise resolves normally. `runPrediction()` then shows `Prediction complete`, and the fetch/validate/baseline handlers show completion toasts even when the backend failed.

Root cause:

The frontend assumes any parseable JSON response is successful.

Business or technical impact:

Operators can believe predictions or validations succeeded when they actually failed.

Recommended fix:

In `postJson()`, throw when `!res.ok`, using `data.error || data.output || res.statusText`. Only show success toasts after successful HTTP status.

Verification steps:

- Force `/api/predict` to fail, for example with a missing model path.
- Click Run Prediction.
- Confirm the UI shows a failure toast and does not show `Prediction complete`.

### CR-005: Forecast quality direction accuracy does not match database WIN/LOSS logic

Severity: High

Area: Business Logic / Backend / Database

File(s) affected:

- `src/forecast_quality_validator.py:170-185`
- `src/prediction_store.py:354-412`
- `src/prediction_store.py:506-566`

Description:

Database outcomes save predicted direction candle-to-candle using the previous forecast close, with the first candle anchored to `last_input_close`. Actual direction uses previous actual close, with the first actual comparison anchored to `last_input_close`. The quality validator instead shifts only the actual series and computes forecast direction from `previous_actual_close`; it also excludes the first matched candle from direction accuracy.

Root cause:

Direction accuracy is implemented in two places with different anchor rules.

Business or technical impact:

The same forecast can show one direction accuracy in JSON reports and a different WIN/LOSS result in PostgreSQL/dashboard summaries.

Recommended fix:

Create one shared direction-comparison function that accepts `last_input_close`, forecast closes, and actual closes. Use it in both validation reports and database outcome updates.

Verification steps:

- Seed a small forecast/actual pair with known UP/DOWN/FLAT movements.
- Run `main_validate_forecast_quality.py` and `update_predictions_with_actuals()`.
- Confirm direction totals and wins/losses match exactly.

### CR-006: Latest validation metric is mislabeled and displayed as a percent

Severity: High

Area: Backend / Frontend / Business Logic

File(s) affected:

- `src/dashboard_db.py:253-257`
- `src/dashboard_db.py:281-297`
- `src/dashboard_ui.py:1419`
- `src/dashboard_ui.py:1460`

Description:

`latest_validation_metrics()` returns `AVG(ABS(o.forecast_close - o.actual_close))` as `max_abs_close_move_pct`. The UI labels it as `Expected move` and formats it as a percentage. The SQL expression is neither a max nor a percent.

Root cause:

A price-error metric is assigned a movement-percent field name.

Business or technical impact:

Risk and validation panels can display misleading percent values.

Recommended fix:

Return separate fields such as `avg_abs_close_error`, `max_abs_close_error`, and true `max_abs_close_move_pct`. Only percentage fields should be formatted as percent.

Verification steps:

- Insert an outcome with known forecast/actual close values.
- Load `/api/status`.
- Confirm JSON fields and UI labels match the actual metric semantics.

### CR-007: Dashboard file endpoint path guard can allow sibling-path reads if exposed

Severity: High

Area: Security

File(s) affected:

- `src/dashboard_server.py:329-345`
- `src/dashboard_server.py:531-535`

Description:

The `/file` endpoint checks `str(resolved).startswith(str(ROOT.resolve()))`. A sibling path whose absolute path begins with the same root string can pass the check. The dashboard defaults to localhost, but it supports arbitrary `--host` values.

Root cause:

Path containment is implemented with string prefix matching instead of path-aware containment.

Business or technical impact:

If the dashboard is bound to a shared network interface, a remote client may be able to attempt reads outside the project root when paths share the same prefix.

Recommended fix:

Use `resolved.relative_to(ROOT.resolve())` or `os.path.commonpath()`. Also restrict served artifact extensions and keep localhost binding unless authentication is added.

Verification steps:

- Create a sibling directory whose name starts with `capital_kronos_data_bridge`.
- Request `/file?path=<absolute sibling file>`.
- Confirm the fixed server returns 404.

### CR-008: Invalid OHLC values can be coerced to zero before database persistence

Severity: High

Area: Database / Backend / Data Integrity

File(s) affected:

- `src/prediction_store.py:28-31`
- `src/prediction_store.py:105-149`
- `src/kronos_mapper.py:148-165`

Description:

`_safe_float()` returns `0.0` for `NaN`, and `upsert_ohlcv_df()` applies it to open/high/low/close. Some callers validate earlier, but `upsert_ohlcv_df()` itself can silently convert invalid OHLC values into zeroes. The database OHLC invariant does not reject all-zero candles.

Root cause:

Persistence sanitization replaces invalid required values with a valid numeric sentinel instead of rejecting them.

Business or technical impact:

Bad candles can be stored, forecasted, displayed, and used for signal generation or fine-tuning.

Recommended fix:

Validate OHLC columns in `upsert_ohlcv_df()` before conversion. Reject null/non-finite OHLC. Only default optional volume/amount fields when intentional.

Verification steps:

- Call `upsert_ohlcv_df()` with `open = NaN`.
- Confirm it raises a validation error and inserts no candle.

## 3. Frontend Issues

### FE-001: Duplicate `baselines` id breaks Baselines rendering and action binding

Severity: High

Area: Frontend

File(s) affected:

- `src/dashboard_ui.py:699`
- `src/dashboard_ui.py:741`
- `src/dashboard_ui.py:1465-1478`
- `src/dashboard_ui.py:1915`

Description:

See CR-002.

Recommended fix:

Use unique ids for action buttons and tab panels.

### FE-002: POST action failures are shown as successful

Severity: High

Area: Frontend

File(s) affected:

- `src/dashboard_ui.py:1706-1763`

Description:

See CR-004.

Recommended fix:

Check `res.ok` and throw on non-2xx responses.

### FE-003: Fetch actuals, validate actuals, and baselines ignore selected market/resolution

Severity: High

Area: Frontend / API Binding

File(s) affected:

- `src/dashboard_ui.py:1913-1915`
- `src/dashboard_server.py:415-525`

Description:

See CR-003.

Recommended fix:

Include selected market/resolution in POST payloads.

### FE-004: Signal table column and filter semantics are inconsistent

Severity: Medium

Area: Frontend / API Binding

File(s) affected:

- `src/dashboard_ui.py:1286`
- `src/dashboard_ui.py:1331-1337`
- `src/dashboard_db.py:153-159`

Description:

The filter labeled `Direction` sends `UP`, `DOWN`, and `FLAT`, which the backend applies to `s.direction`. The table column labeled direction displays `r.signal`, which is `LONG`, `SHORT`, or `HOLD`.

Root cause:

Signal action and forecast direction are separate fields but are conflated in labels.

Impact:

Users can filter by UP but see LONG in the displayed column, which looks inconsistent.

Recommended fix:

Display both `Signal` and `Forecast Direction`, or rename labels to match the actual field.

### FE-005: Dashboard timezone is hardcoded to Asia/Amman

Severity: Medium

Area: Frontend / Configuration

File(s) affected:

- `src/dashboard_ui.py:763`
- `src/dashboard_server.py:50-52`
- `src/dashboard_db.py:14`
- `src/time_utils.py:12-17`

Description:

The project supports `CAPITAL_DISPLAY_TIMEZONE`, but dashboard UI and DB date filtering hardcode `Asia/Amman`.

Root cause:

Dashboard modules bypass the centralized `time_utils.display_timezone_name()`.

Impact:

Users who configure another timezone can see inconsistent CLI, JSON, and dashboard timestamps.

Recommended fix:

Use `time_utils.display_timezone_name()` in Python and inject the configured timezone into the dashboard JS.

### FE-006: Prediction controls rely on browser-only validation

Severity: Medium

Area: Frontend / Backend Validation

File(s) affected:

- `src/dashboard_ui.py:663-667`
- `src/dashboard_ui.py:1740-1747`
- `src/dashboard_server.py:367-396`

Description:

The UI uses `min`/`max` attributes for `predLen` and `lookback`, but the backend only casts values to int. Direct API calls can submit invalid ranges.

Root cause:

Validation exists only as browser hints.

Impact:

Bad requests can launch invalid subprocess commands and produce confusing backend errors.

Recommended fix:

Validate `pred_len`, `lookback`, `feature_set`, market, and resolution server-side before spawning a process.

### FE-007: Auto prediction is enabled by default

Severity: Medium

Area: Frontend / Performance / Operations

File(s) affected:

- `src/dashboard_ui.py:677-691`
- `src/dashboard_ui.py:1666-1684`

Description:

Auto-refresh defaults to 1 second and auto-predict defaults to checked. For `MINUTE`, the browser can trigger Kronos prediction at each candle boundary.

Root cause:

A high-cost operation is enabled by default.

Impact:

Unexpected model/API load, possible rate limits, and duplicated work with the scheduler.

Recommended fix:

Default auto-predict to off or require explicit confirmation.

## 4. Backend Issues

### BE-001: Dashboard action endpoints use global latest metadata

Severity: High

Area: Backend / API

File(s) affected:

- `src/dashboard_server.py:415-525`

Description:

See CR-003.

Recommended fix:

Accept and validate selected symbol/resolution payloads.

### BE-002: Dashboard prediction hardcodes demo environment and mid price side

Severity: Medium

Area: Backend / Configuration

File(s) affected:

- `src/dashboard_server.py:367-396`

Description:

`_predict()` always passes `--env demo` and `--price-side mid`, regardless of `.env`, `CAPITAL_ENV`, or other runtime settings.

Root cause:

Runtime config is hardcoded inside the HTTP handler.

Impact:

Users running live or bid/ask workflows from CLI may unknowingly run dashboard predictions against demo/mid data.

Recommended fix:

Read environment and price side from configuration or expose explicit dashboard controls.

### BE-003: Malformed POST JSON has no structured error response

Severity: Medium

Area: Backend / Exception Handling

File(s) affected:

- `src/dashboard_server.py:349-365`

Description:

`json.loads()` is called before route dispatch and is not wrapped. Malformed JSON can terminate the request handler instead of returning a clean 400 JSON response.

Root cause:

Missing request parsing error handling.

Impact:

Bad clients get poor API behavior and server logs become noisy.

Recommended fix:

Catch `json.JSONDecodeError` and return `400 {"error": "Invalid JSON"}`.

### BE-004: WebSocket keepalive task failures may not stop the stream cleanly

Severity: Medium

Area: Backend / Async / Reliability

File(s) affected:

- `src/capital_ws_ohlc_client.py:56-64`
- `src/capital_ws_ohlc_client.py:97-113`

Description:

`_keepalive()` raises inside a background task, but the task is not monitored while the main `async for` receives messages.

Root cause:

Background task failure is not coordinated with the main WebSocket loop.

Impact:

The stream can appear connected while keepalive has failed, delaying reconnection and stale-price detection.

Recommended fix:

Race receive and keepalive tasks with `asyncio.wait()` or close the WebSocket when keepalive fails.

### BE-005: Database write failure can stop WebSocket streaming

Severity: Medium

Area: Backend / Reliability

File(s) affected:

- `src/capital_ws_ohlc_client.py:126-133`
- `src/capital_ws_ohlc_client.py:189-197`

Description:

The WebSocket message handler writes raw events and OHLC rows to PostgreSQL. If PostgreSQL is unavailable or a constraint fails, the exception propagates and stops the stream.

Root cause:

Database persistence is tightly coupled to streaming ingestion.

Impact:

A transient DB issue can stop live file-based streaming and make the dashboard stale.

Recommended fix:

Wrap DB writes separately, mark heartbeat degraded, and continue file output when possible.

### BE-006: Scheduler interval accepts zero or negative values

Severity: Medium

Area: Backend / Validation

File(s) affected:

- `src/main_prediction_scheduler.py:38`
- `src/main_prediction_scheduler.py:63-67`

Description:

`--interval-minutes` is parsed as an int but not validated. Zero causes division by zero in `_sleep_to_next_boundary()`.

Root cause:

Missing CLI/environment validation.

Impact:

A bad environment variable can crash the scheduler after the first run.

Recommended fix:

Require `interval_minutes >= 1`.

### BE-007: Fine-tune commands use `shell=True`

Severity: Medium

Area: Backend / Security

File(s) affected:

- `src/main_auto_finetune_worker.py:262-270`
- `src/main_finetune_kronos.py:26-30`

Description:

Fine-tune command templates are rendered into a single shell command. Placeholder values are inserted directly.

Root cause:

Command execution is string-based instead of argv-based.

Impact:

Misconfigured paths or symbols containing shell metacharacters can execute unintended shell operations.

Recommended fix:

Prefer argv execution, or strictly validate/quote all placeholder values.

### BE-008: Database persistence can fail an otherwise valid forecast

Severity: Medium

Area: Backend / Reliability

File(s) affected:

- `src/main_run_kronos_predict.py:491-502`
- `src/main_run_kronos_predict.py:570-571`
- `src/main_forecast_latest.py:111-117`

Description:

`main_run_kronos_predict.py` saves to PostgreSQL by default. If DB is unavailable, the command can fail after model inference and artifact generation steps.

Root cause:

Forecast generation and DB persistence are not separated into recoverable stages.

Impact:

A DB outage can cause the whole forecast run to be reported as failed.

Recommended fix:

Write artifacts first, then attempt DB persistence with a recoverable warning or explicit strict mode.

## 5. Database Issues

### DB-001: Docker and application DSN defaults are inconsistent

Severity: Critical

Area: Database / Configuration

File(s) affected:

- `docker-compose.yml:6-8`
- `src/db.py:13`
- `.env.example:12`

Description:

See CR-001.

Recommended fix:

Unify database credentials and document one setup path.

### DB-002: Core tables lack status and enum-like CHECK constraints

Severity: Medium

Area: Database / Data Integrity

File(s) affected:

- `migrations/001_init.sql:62-91`
- `migrations/001_init.sql:119-137`
- `migrations/001_init.sql:140-158`
- `migrations/002_signals_trade_fields.sql:20-26`

Description:

Columns such as `run_status`, `signal`, `direction`, `status`, `resolution`, and `price_side` are free text while application code assumes fixed values.

Root cause:

Domain values are enforced in application code only.

Impact:

Misspelled or unexpected statuses can break filters, rollups, and dashboard labels.

Recommended fix:

Add CHECK constraints or PostgreSQL enums after normalizing existing data.

### DB-003: Numeric ranges are not constrained

Severity: Medium

Area: Database / Data Integrity

File(s) affected:

- `migrations/001_init.sql:21-41`
- `migrations/001_init.sql:97-115`
- `migrations/001_init.sql:119-137`

Description:

The schema does not enforce positive prices, nonnegative volume/amount, confidence between 0 and 1, or positive row counts.

Root cause:

Limited database-level validation.

Impact:

Invalid data can enter through future scripts, manual writes, or partially validated paths.

Recommended fix:

Add CHECK constraints for expected numeric domains.

### DB-004: Outcome archive removes rows from live summaries

Severity: Medium

Area: Database / Reporting

File(s) affected:

- `src/main_maintenance_worker.py:52-123`
- `src/prediction_store.py:595-640`
- `src/dashboard_db.py:396-405`

Description:

The maintenance worker deletes old validated rows from `prediction_outcomes` after copying them to `prediction_outcomes_archive`. Dashboard summaries and `prediction_summary()` only read live outcomes.

Root cause:

Archive rows are not included in reporting queries and no aggregate rollups are stored before deletion.

Impact:

Long-running dashboards can show incomplete historical performance as outcomes age out.

Recommended fix:

Persist outcome rollups on `prediction_runs` or query live + archive tables for historical summaries.

### DB-005: Signal filter query aggregates all outcomes before filtering

Severity: Medium

Area: Database / Performance

File(s) affected:

- `src/dashboard_db.py:171-223`
- `migrations/005_signals_filter_indexes.sql:1-7`

Description:

`query_signals()` builds an outcome rollup over all `prediction_outcomes` before applying signal filters.

Root cause:

The query does not prefilter candidate run ids before aggregating outcomes.

Impact:

Signals pagination can slow down as outcomes grow.

Recommended fix:

Filter candidate signals/runs first, then aggregate outcomes for those run ids. Add an index on `prediction_outcomes(run_id, status)`.

## 6. Logical and Workflow Issues

### WF-001: Direction accuracy differs between validation report and DB outcomes

Severity: High

Area: Business Logic

File(s) affected:

- `src/forecast_quality_validator.py:170-185`
- `src/prediction_store.py:506-566`

Description:

See CR-005.

Recommended fix:

Use one shared direction-comparison implementation.

### WF-002: Tie outcomes are classified as WIN

Severity: Medium

Area: Business Logic

File(s) affected:

- `src/dashboard_db.py:62-68`
- `src/dashboard_db.py:122-130`
- `src/dashboard_db.py:335-340`
- `src/prediction_store.py:573-580`
- `migrations/003_backfill_signal_status.sql:12-17`

Description:

When wins equal losses and at least one candle is validated, signal status becomes `WIN`.

Root cause:

The rule uses `wins >= losses`.

Impact:

Partially validated or tied outcomes can be overstated as successful.

Recommended fix:

Define explicit tie behavior such as `MIXED`, `BREAKEVEN`, or `PARTIAL`.

### WF-003: Latest metadata selection can mix artifacts from unrelated runs

Severity: High

Area: Workflow / API

File(s) affected:

- `src/dashboard_server.py:65-71`
- `src/dashboard_server.py:397-408`

Description:

After prediction, `_predict()` searches by glob and falls back to any latest metadata file. If the requested market differs from selected epic or another run finishes nearby, the generated report can use the wrong metadata.

Root cause:

The subprocess does not return an exact metadata path through a structured contract.

Impact:

Dashboard report links and state can point to the wrong forecast.

Recommended fix:

Have `main_forecast_latest.py` emit structured JSON with the exact metadata path, or pass an explicit metadata-output path from the dashboard.

### WF-004: Default resolution differs across entry points

Severity: Low

Area: Workflow / Configuration

File(s) affected:

- `src/dashboard_ui.py:655-657`
- `start_dashboard.ps1:7`
- `src/config.py:52`
- `README.md:83-193`

Description:

Dashboard and supervisor default to `MINUTE`, while config defaults and many README examples use `MINUTE_5`.

Root cause:

Entry points have different defaults without a single documented reason.

Impact:

Users can accidentally compare forecasts and validations from different resolutions.

Recommended fix:

Align defaults or document why dashboard/live workflows use `MINUTE`.

### WF-005: Partial actual validation may include incomplete candles

Severity: Medium

Area: Business Logic

File(s) affected:

- `src/main_fetch_actual_for_forecast.py:73-103`
- `src/main_validation_worker.py:29-46`

Description:

`--allow-partial` uses wall-clock `now()` as the effective end and filters actual rows up to that timestamp. Depending on Capital.com behavior, this can include an in-progress candle.

Root cause:

Partial validation is not floored to the last fully closed candle boundary.

Impact:

Outcomes may be marked WIN/LOSS before the actual candle is finalized.

Recommended fix:

For partial validation, floor `now()` to the previous closed candle boundary for the selected resolution.

Needs verification:

- Confirm whether Capital.com historical `/prices` returns the current in-progress candle.

## 7. Security Findings

### SEC-001: `/file` path containment uses unsafe string prefix matching

Severity: High

Area: Security

File(s) affected:

- `src/dashboard_server.py:329-345`

Description:

See CR-007.

Recommended fix:

Use path-aware containment and restrict served artifact types.

### SEC-002: Dashboard has no authentication or CSRF protection

Severity: Medium

Area: Security

File(s) affected:

- `src/dashboard_server.py:531-541`
- `src/dashboard_server.py:349-365`

Description:

The dashboard defaults to `127.0.0.1`, but `--host` can bind it elsewhere. If exposed, any reachable client can trigger predictions, fetch project files through `/file`, and run long local subprocesses.

Root cause:

The dashboard is designed as a local tool and has no auth layer.

Impact:

Network exposure can lead to unauthorized artifact access and resource consumption.

Recommended fix:

Warn or refuse when binding to non-loopback hosts unless a token/auth setting is configured.

### SEC-003: Shell-based fine-tune execution can execute unintended commands

Severity: Medium

Area: Security

File(s) affected:

- `src/main_auto_finetune_worker.py:262-270`
- `src/main_finetune_kronos.py:26-30`

Description:

See BE-007.

Recommended fix:

Avoid `shell=True` for templated commands or validate/quote placeholders strictly.

### SEC-004: Local `.env` contains configured credentials

Severity: Low

Area: Security / Configuration

File(s) affected:

- `.env`
- `.gitignore:1`

Description:

A local `.env` exists and contains configured Capital.com credentials. `.gitignore` correctly ignores `.env`, but future commits should be checked carefully.

Root cause:

Plaintext local development credentials are present.

Impact:

Accidental commit or file sharing would expose credentials.

Recommended fix:

Keep `.env` ignored and consider secret scanning before commits.

## 8. Performance Findings

### PERF-001: Dashboard default 1-second polling hits heavy endpoints

Severity: Medium

Area: Frontend / Backend Performance

File(s) affected:

- `src/dashboard_ui.py:677-685`
- `src/dashboard_ui.py:1687-1697`
- `src/dashboard_db.py:300-453`
- `src/dashboard_db.py:100-238`

Description:

Each refresh calls `/api/status` and `/api/signals`. These run multiple DB queries and an outcome aggregate. The default refresh interval is 1 second.

Root cause:

Polling cadence is aggressive for database-backed data.

Impact:

Avoidable database load, especially as `prediction_outcomes` grows.

Recommended fix:

Increase default refresh interval or split live quote refresh from heavier dashboard summaries.

### PERF-002: Signals query aggregates all outcomes

Severity: Medium

Area: Database Performance

File(s) affected:

- `src/dashboard_db.py:171-223`

Description:

See DB-005.

Recommended fix:

Prefilter candidate runs and add `prediction_outcomes(run_id, status)`.

### PERF-003: WebSocket row append rewrites rolling CSV every message

Severity: Low

Area: Backend Performance

File(s) affected:

- `src/capital_ws_ohlc_client.py:178-188`

Description:

Each OHLC message rewrites the full rolling CSV. With `max_rows=512` this is acceptable, but it scales poorly if increased.

Root cause:

Simple full-file rewrite approach.

Impact:

Low at current row count; potentially costly at larger windows or higher frequency.

Recommended fix:

Document the 512-row assumption or switch to append plus periodic compaction for larger windows.

### PERF-004: Charts redraw on every status refresh

Severity: Low

Area: Frontend Performance

File(s) affected:

- `src/dashboard_ui.py:1641-1644`

Description:

`drawCloseChart()` and `drawCandleChart()` run on every render, including background refreshes, even if chart data did not change.

Root cause:

No chart-data diff key is used.

Impact:

Unnecessary CPU work on 1-second refresh, especially on mobile.

Recommended fix:

Track chart data keys and redraw only when data or canvas size changes.

## 9. Testing Gaps

Existing tests:

- 16 unittest tests pass.
- Covered areas include auto-finetune promotion decisions, invalid fine-tune template skip behavior, heartbeat stale derivation, status warning generation, and auto-finetuned model selection.

Missing unit tests:

- `prediction_store.direction_from_prices()` and `update_predictions_with_actuals()` first-candle and tie behavior.
- `forecast_quality_validator.validate_forecast_quality()` direction accuracy against known paths.
- `dashboard_db.latest_validation_metrics()` metric names and calculations.
- `upsert_ohlcv_df()` rejection of NaN/non-finite OHLC values.
- `main_prediction_scheduler._sleep_to_next_boundary()` invalid interval handling.

Missing integration tests:

- Fresh Docker PostgreSQL migration with documented DSN.
- `/api/status`, `/api/signals`, `/api/predict`, `/api/fetch-actual`, `/api/validate-actual`, and `/api/baselines` against seeded data.
- Dashboard selected market/resolution propagation to action endpoints.
- Archive worker behavior and summary stability before/after archiving.

Missing frontend tests:

- DOM id uniqueness test for dashboard HTML.
- Baselines button/tab smoke test.
- Failed POST response handling test.
- Signal filter/table semantic test.
- Mobile/responsive smoke test.

Missing database validation tests:

- CHECK constraints for statuses, directions, prices, confidence, volume, and amount.
- Query performance checks with large `prediction_outcomes` volume.
- Migration idempotency from empty and partially migrated databases.

Recommended test cases:

- Seed one forecast with known closes and assert JSON validation matches DB outcomes.
- Seed tied outcomes and assert signal status follows the chosen tie rule.
- Simulate `/api/predict` returning 500 and assert the UI exposes failure.
- Run migrations using the Docker DSN from `.env.example`.
- Request `/file` with a sibling absolute path and assert 404.

## 10. Recommended Fix Plan

Phase 1: Critical and blocking issues

- Align PostgreSQL DSN defaults.
- Fix duplicate `baselines` DOM id.
- Make dashboard POST actions use selected market/resolution.
- Make frontend throw on non-2xx POST responses.
- Fix `/file` path containment.

Phase 2: Functional/logical correctness

- Unify direction accuracy and WIN/LOSS logic.
- Fix `latest_validation_metrics()` metric names/calculations.
- Define tie behavior for signal outcomes.
- Fix latest metadata/report selection to use exact subprocess output paths.
- Make dashboard timezone honor `CAPITAL_DISPLAY_TIMEZONE`.

Phase 3: Performance and database optimization

- Add `prediction_outcomes(run_id, status)` index.
- Refactor signal query to aggregate only filtered candidate runs.
- Reduce default dashboard polling or split live quote polling from heavy summaries.
- Avoid unnecessary chart redraws.

Phase 4: Security hardening

- Add non-loopback host warning or token requirement.
- Restrict `/file` to known artifact directories and extensions.
- Avoid shell-based fine-tune command execution or strictly validate placeholders.
- Keep `.env` ignored and secret-scan before commits.

Phase 5: Refactoring and maintainability

- Centralize resolution, price side, timezone, status, signal, and direction constants.
- Separate dashboard API validation from subprocess orchestration.
- Separate forecast generation from DB persistence failure handling.
- Move shared direction/outcome rules into one module.

Phase 6: Testing and regression prevention

- Add unit tests for direction/outcome rules and metric semantics.
- Add integration tests for migrations and dashboard API endpoints.
- Add frontend smoke tests for dashboard tabs/actions/error states.
- Add database constraint tests and archive-summary tests.

## 11. Final Checklist

| ID | Severity | Area | Issue | File/Location | Recommended Action | Status |
|----|----------|------|-------|---------------|--------------------|--------|
| CR-001 | Critical | Configuration / Database | App DSN mismatches Docker credentials | `src/db.py:13`, `docker-compose.yml:6-8`, `.env.example:12` | Align DSN defaults or require explicit `POSTGRES_DSN` | Open |
| CR-002 | High | Frontend | Duplicate `baselines` DOM id | `src/dashboard_ui.py:699`, `src/dashboard_ui.py:741` | Rename button or panel id | Open |
| CR-003 | High | Frontend / Backend | Action endpoints ignore selected market/resolution | `src/dashboard_server.py:415-525`, `src/dashboard_ui.py:1913-1915` | Send and use selected context | Open |
| CR-004 | High | Frontend | Failed POST actions shown as success | `src/dashboard_ui.py:1706-1763` | Check `res.ok` and throw on non-2xx | Open |
| CR-005 | High | Business Logic | Validation accuracy differs from DB WIN/LOSS | `src/forecast_quality_validator.py:170-185`, `src/prediction_store.py:506-566` | Centralize direction comparison | Open |
| CR-006 | High | Backend / Frontend | Price error mislabeled as movement percent | `src/dashboard_db.py:253-257`, `src/dashboard_ui.py:1419` | Rename and recalculate metrics | Open |
| CR-007 | High | Security | `/file` path guard uses unsafe prefix check | `src/dashboard_server.py:329-345` | Use `Path.relative_to()` containment | Open |
| CR-008 | High | Database | NaN OHLC can be coerced to zero | `src/prediction_store.py:28-31`, `src/prediction_store.py:105-149` | Reject invalid OHLC before persistence | Open |
| FE-004 | Medium | Frontend | Signal/direction labels and filters are inconsistent | `src/dashboard_ui.py:1286`, `src/dashboard_ui.py:1331-1337` | Display separate signal and direction columns | Open |
| FE-005 | Medium | Frontend / Config | Dashboard timezone is hardcoded | `src/dashboard_ui.py:763`, `src/dashboard_db.py:14` | Use `CAPITAL_DISPLAY_TIMEZONE` everywhere | Open |
| FE-006 | Medium | Frontend / Backend | Prediction form lacks server-side range validation | `src/dashboard_server.py:367-396` | Validate payload and return 400 | Open |
| FE-007 | Medium | Performance | Auto-predict enabled by default | `src/dashboard_ui.py:677-691`, `src/dashboard_ui.py:1666-1684` | Default off or require confirmation | Open |
| BE-002 | Medium | Backend / Config | Dashboard hardcodes demo and mid | `src/dashboard_server.py:367-396` | Read env/config or expose controls | Open |
| BE-003 | Medium | Backend | Malformed POST JSON has no structured 400 | `src/dashboard_server.py:349-365` | Catch JSON parse errors | Open |
| BE-004 | Medium | Backend / Async | WebSocket keepalive task failures are not supervised | `src/capital_ws_ohlc_client.py:56-64`, `src/capital_ws_ohlc_client.py:97-113` | Propagate keepalive failures to reconnect loop | Open |
| BE-005 | Medium | Backend | DB write failure stops WebSocket stream | `src/capital_ws_ohlc_client.py:126-133`, `src/capital_ws_ohlc_client.py:189-197` | Decouple DB persistence from streaming | Open |
| BE-006 | Medium | Backend | Scheduler interval allows zero | `src/main_prediction_scheduler.py:38`, `src/main_prediction_scheduler.py:63-67` | Require interval >= 1 | Open |
| BE-007 | Medium | Security | Fine-tune command uses `shell=True` | `src/main_auto_finetune_worker.py:262-270`, `src/main_finetune_kronos.py:26-30` | Use argv execution or strict validation | Open |
| BE-008 | Medium | Reliability | DB persistence failure can fail completed forecast | `src/main_run_kronos_predict.py:491-502` | Separate artifact generation from DB save | Open |
| DB-002 | Medium | Database | Missing CHECK constraints for domain fields | `migrations/001_init.sql`, `migrations/002_signals_trade_fields.sql` | Add enum/CHECK constraints | Open |
| DB-003 | Medium | Database | Missing numeric range constraints | `migrations/001_init.sql` | Add nonnegative/range checks | Open |
| DB-004 | Medium | Database / Reporting | Archived outcomes disappear from summaries | `src/main_maintenance_worker.py:52-123`, `src/prediction_store.py:595-640` | Include archive or persist rollups | Open |
| DB-005 | Medium | Performance | Signals query aggregates all outcomes | `src/dashboard_db.py:171-223` | Prefilter runs and index outcomes by run/status | Open |
| WF-002 | Medium | Business Logic | Tied outcomes count as WIN | `src/prediction_store.py:573-580`, `src/dashboard_db.py:62-68` | Define and implement explicit tie state | Open |
| WF-003 | High | Workflow | Dashboard can select wrong metadata after prediction | `src/dashboard_server.py:397-408` | Return exact metadata path from subprocess | Open |
| WF-004 | Low | Configuration | Default resolution differs across entry points | `src/dashboard_ui.py:655-657`, `src/config.py:52`, `start_dashboard.ps1:7` | Align or document defaults | Open |
| WF-005 | Medium | Business Logic | Partial validation may include open candles | `src/main_fetch_actual_for_forecast.py:73-103` | Use last closed candle boundary | Needs verification |
| SEC-002 | Medium | Security | Dashboard has no auth if exposed beyond localhost | `src/dashboard_server.py:531-541` | Add host warning/token for remote binding | Open |
| SEC-004 | Low | Security | Local `.env` contains credentials | `.env`, `.gitignore:1` | Keep ignored and secret-scan before commits | Open |
| PERF-001 | Medium | Performance | 1-second polling hits heavy endpoints | `src/dashboard_ui.py:677-685`, `src/dashboard_db.py:300-453` | Increase interval or split polling | Open |
| PERF-003 | Low | Performance | WebSocket rewrites rolling CSV every message | `src/capital_ws_ohlc_client.py:178-188` | Keep bounded or switch to append/compact | Open |
| PERF-004 | Low | Frontend Performance | Charts redraw every refresh | `src/dashboard_ui.py:1641-1644` | Redraw only on data or size changes | Open |
| TEST-001 | Medium | Testing | No end-to-end DB/API tests for dashboard workflows | `tests/` | Add seeded integration tests | Open |
| TEST-002 | Medium | Testing | No frontend smoke tests for dashboard tabs/actions | `tests/` | Add browser/DOM smoke tests | Open |
| TEST-003 | Medium | Testing | No migration/constraint validation tests | `migrations/`, `tests/` | Add migration idempotency and constraint tests | Open |
