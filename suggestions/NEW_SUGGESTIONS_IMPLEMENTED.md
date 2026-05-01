# New Suggestions and Implementation Notes

This document contains additional suggestions beyond the original implementation list, and confirms how they were addressed.

## Suggestion A: Heartbeat Freshness Guard
- Problem: A worker can show `OK` even when it has silently stopped updating heartbeats.
- Suggestion: Add heartbeat age checks and treat old heartbeats as stale.
- Implemented:
  - Added worker heartbeat staleness evaluation (`>180s`) and `STALE` status derivation in `dashboard_db` snapshot output.
  - Added stale-worker warnings in dashboard API status payload.
  - Added stale heartbeat age display in the UI worker cards.

## Suggestion B: Stronger Auto-Finetune Command Safety
- Problem: Misconfigured finetune command templates can run with missing paths and produce hard-to-debug failures.
- Suggestion: Require `KRONOS_FINETUNE_COMMAND` template placeholders for dataset and model target.
- Implemented:
  - Enforced `{dataset}` and `{model_dir}` placeholders before command execution.
  - Added explicit skip reason and hint in auto-finetune status when template is invalid.

## Suggestion C: Promotion Must Beat Prior Promoted Baseline
- Problem: A newly trained model should not be promoted if its live direction accuracy does not improve versus the previously promoted model baseline.
- Suggestion: Add relative promotion gating on top of minimum-threshold checks.
- Implemented:
  - Added `promoted_direction_accuracy_pct` tracking in auto-finetune status.
  - Promotion now requires minimum thresholds and improvement over prior promoted baseline (when available).
  - Production prediction selection only uses auto-finetuned model when promotion status is approved.

## Suggestion D: Supervisor Configurability
- Problem: Ops teams need explicit controls for worker restart behavior.
- Suggestion: Add restart-policy env controls in startup script.
- Implemented:
  - Added `WORKER_RESTART_MAX_ATTEMPTS`.
  - Added `WORKER_MONITOR_INTERVAL_SECONDS`.
  - Added optional maintenance worker switch `ENABLE_MAINTENANCE_WORKER`.

## Practical Result
- Dashboard now distinguishes worker errors from stale heartbeats.
- Auto-finetune promotion is safer and less likely to deploy weaker models.
- Startup orchestration is more controllable and resilient in production-like runs.
