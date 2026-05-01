# PL-001 Execution Suggestions

## What Was Completed

The PL-001 plan items were implemented and verified against the current codebase.

- Heartbeat freshness guard behavior is present and preserved:
  - stale worker threshold remains 180 seconds.
  - default worker states remain present for prediction scheduler, validation worker, websocket stream, auto-finetune worker, and maintenance worker.
  - stale `OK` workers are converted to `STALE`, while explicit `ERROR` and `MISSING` statuses are preserved.
  - `/api/status` warning generation and dashboard worker-card stale/age display behavior are covered by tests.
- Auto-finetune safety behavior is present and preserved:
  - empty `KRONOS_FINETUNE_COMMAND` continues to skip execution.
  - missing `{dataset}` or `{model_dir}` in template continues to skip execution with `invalid_finetune_command_template`.
  - optional `{symbol}` and `{resolution}` placeholders remain supported.
- Promotion gating behavior is present and preserved:
  - promotion still depends on model readiness, minimum matched candles, minimum direction accuracy, and improvement vs prior promoted baseline.
  - production model selection still ignores unapproved or incomplete auto-finetuned models.
- Supervisor configurability remains present:
  - `WORKER_RESTART_MAX_ATTEMPTS` default is 20.
  - `WORKER_MONITOR_INTERVAL_SECONDS` default is 5.
  - `ENABLE_MAINTENANCE_WORKER` still controls maintenance worker launch.

## Repository Changes Applied

### 1) Added Focused Tests

Created a new `tests/` suite to cover the high-risk PL-001 behaviors:

- `tests/test_dashboard_db.py`
  - `_seconds_since` for `None`, timezone-aware, naive, ISO string, and invalid values.
  - stale worker status derivation for old `OK` heartbeat rows.
- `tests/test_dashboard_server_status_warnings.py`
  - `/api/status` warning generation for stale websocket, stale workers, missing required workers, and worker errors.
- `tests/test_auto_finetune_worker.py`
  - `_promotion_decision` branch coverage for all specified outcomes.
  - invalid finetune command template path ensuring skip and no subprocess execution.
- `tests/test_main_run_kronos_predict.py`
  - `_auto_finetuned_model_dir` gating for missing/pending/rejected/unready states and approved+ready selection.

### 2) Updated Operator Configuration Reference

Updated `.env.example` to include the missing variables requested by PL-001:

- supervisor controls
- auto-finetune controls
- promotion thresholds
- maintenance/cleanup cadence controls
- logging/rotation controls

### 3) Updated README Operational Guidance

Added documentation for:

- operational environment variable quick reference.
- auto-finetune command template requirements and example (`{dataset}` and `{model_dir}` required; `{symbol}` and `{resolution}` optional).
- startup supervisor behavior: preflight checks, managed workers, restart policy, monitor interval, maintenance toggle, and auto-finetune toggle.

## Validation Run

Executed test suite:

- `\.venv\Scripts\python.exe -m unittest discover -s tests -v`
- Result: all tests pass.

## Suggested Next Improvements

1. Add a CI check that runs `python -m unittest discover -s tests -v` on every push/PR to prevent regressions in safety gates.
2. Add one integration-style test that validates `output/auto_finetune_status.json` status transitions across multiple simulated cycles.
3. Add a lightweight PowerShell test (or scriptable smoke check) for `start_dashboard.ps1` toggles (`ENABLE_MAINTENANCE_WORKER=false`, custom monitor interval, low restart limits).
4. Add a short runbook section mapping each `/api/status.status_warnings` message to operator action.
