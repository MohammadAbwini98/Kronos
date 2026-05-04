# Kronos Full Repo Audit and Implementation Plan (Phase 0)

## 1. Document Purpose

This document is the mandatory Phase 0 deliverable for the repository-wide audit of the Capital Kronos Data Bridge and local Kronos integration.

It records:
- full-repo audit scope and current-state findings,
- non-negotiable system constraints,
- known issue baseline that must be preserved in implementation planning,
- phased implementation plan (Phase 1 through Phase 9),
- validation gates and acceptance criteria before code changes proceed.

Current status:
- Audit completed across bridge source, migrations, tests, docs/scripts, and local Kronos model/finetune internals.
- No production behavior changes applied as part of Phase 0.

## 2. Non-Negotiable Constraints

The implementation must preserve these constraints:
- Data-only analytical boundary: no trade execution and no order/position/working-order operations.
- Do not call Capital.com trading endpoints such as positions, orders, or workingorders.
- Keep PostgreSQL as canonical state for forecasts, outcomes, signals, statuses, and model lifecycle metadata.
- Preserve backward-compatible CLI usage unless explicitly versioned.
- Keep worker orchestration stable under start_dashboard.ps1 process management.

## 3. Audit Scope and Coverage

Audit coverage included:
- All source modules under src.
- All SQL migrations under migrations.
- All test modules under tests.
- Runtime and startup scripts, including start_dashboard.ps1.
- Configuration and deployment files, including .env.example and docker-compose.yml.
- Review and planning docs (README, PROJECT_REVIEW_REPORT, CODE_REVIEW_PREDICTION_SIGNAL_IMPROVEMENTS, PL docs).
- Local Kronos repository internals (model, finetune pipeline, tests, examples) for capability alignment.

Primary subsystems verified:
- Capital REST and WebSocket ingestion.
- Prediction scheduler and one-shot prediction runners.
- Forecast persistence, signal generation, and outcome updates.
- Validation worker timing and scoring paths.
- Auto-finetune worker, model registry, walk-forward and shadow evaluation paths.
- Dashboard API/backend query layer and UI behavior.
- Supervisor/heartbeat/maintenance worker coordination.

## 4. Current-State Architecture Snapshot

Core runtime pattern:
- Local Python worker monolith orchestrated by PowerShell supervisor.
- PostgreSQL system-of-record.
- Artifacts emitted to output for CSV/JSON reports and metadata.
- Dashboard server exposes status, signals, actions, and artifact views.

Key processing pipeline:
- Ingestion: Capital REST/WebSocket -> ohlcv_candles/live quotes.
- Forecasting: scheduler/CLI -> prediction_runs + forecast_candles + signals.
- Validation: due-run worker -> prediction_outcomes + status updates.
- Model lifecycle: auto-finetune + registry + walk-forward/shadow evidence.
- Presentation: dashboard DB/API/UI aggregation and warnings.

## 5. Known Issues Baseline (Must Be Included in Phase Execution)

These are the known issue anchors that must remain explicitly addressed in implementation:

1. PostgreSQL DSN mismatch between defaults and Docker credentials.
2. Long-range historical fetch behavior is not fully aligned with canonical DB upsert expectations.
3. Spread/amount and source-quality semantics are underspecified in schema and ingestion mapping.
4. Promotion evidence is not candidate-isolated end-to-end (walk-forward and gate usage gaps).
5. Dashboard action coupling and API/UI contract mismatches can trigger wrong-context operations.
6. Forecast scoring and direction logic are duplicated with inconsistent anchoring between validation/reporting and DB outcomes.
7. Frontend error handling can treat HTTP error responses as success in key actions.
8. Security hardening gap in dashboard file-path containment logic.

## 6. Detailed Audit Findings

### Critical

- DSN/config drift can break fresh setup and migration flows.
- Candidate model evaluation/promotion integrity is incomplete:
  - walk-forward currently baseline-centric,
  - promotion gates rely on incomplete or non-candidate metrics in key paths.
- Action context mismatch in dashboard endpoints can fetch/validate against unintended latest metadata.
- Scoring inconsistency between validator/report path and DB outcome path produces metric drift.
- Path containment implementation in file-serving endpoint requires hardening.

### High

- Signal generation remains a compact terminal-move heuristic; lacks stronger horizon-aware risk evaluation.
- Dataset quality_filter is accepted in metadata but not strictly enforced in exported datasets.
- Shadow evaluation semantics can drift from primary-window signal status semantics.
- Hardcoded defaults (market/resolution/timezone) still influence runtime behavior across layers.
- Metric labeling in dashboard paths includes semantic mismatch (error vs movement percentage representation).
- Silent coercion patterns for numeric ingestion paths can hide upstream data-quality issues.

### Medium

- Live stream persistence path has avoidable IO overhead patterns under sustained flow.
- Forecast metadata association by latest matching artifact can race under overlapping runs.
- Worker/supervisor operational boundaries and stale-detection behavior need stronger end-to-end verification.
- Maintenance archival lifecycle is functionally present but needs stricter completeness checks.

## 7. Phase 1 to Phase 9 Implementation Plan

## Phase 1: Data Mapping and Schema Hardening

Objectives:
- Resolve DSN/config alignment and migration consistency.
- Strengthen ingestion/storage schema for spread/amount/source-quality semantics.
- Eliminate silent invalid OHLC persistence paths.

Planned changes:
- Align default DSN behavior across config, .env.example, Docker, and startup script.
- Introduce/extend schema fields for spread and amount semantics with explicit provenance.
- Ensure long-range fetch workflows update canonical DB paths consistently.
- Enforce required OHLC validation before persistence.

Validation:
- Migration dry-run on clean database.
- Unit tests for mapping/upsert integrity and invalid-candle rejection.
- Setup smoke test confirming coherent DSN behavior.

Exit criteria:
- Clean install path is deterministic.
- Ingestion mappings preserve source semantics without silent corruption.

## Phase 2: Input Validation and Contract Enforcement

Objectives:
- Centralize request/CLI validation.
- Enforce symbol/resolution context fidelity for dashboard actions.

Planned changes:
- Add strict server-side validation for predict/fetch/validate/baseline action payloads.
- Require selected market/resolution propagation from UI to backend actions.
- Normalize validation errors with consistent response structure.

Validation:
- API tests for invalid payloads and context propagation.
- Regression tests for action routing under multi-market/multi-resolution data.

Exit criteria:
- Actions never operate on unintended fallback context.

## Phase 3: Model Usage and Forecast Metadata Integrity

Objectives:
- Improve model-run parameter consistency and traceability.
- Strengthen forecast run metadata for reproducibility.

Planned changes:
- Ensure sample_count/temperature/top_p are consistently wired where intended.
- Expand persisted run/model metadata (versioning, feature set linkage, provenance fields).
- Harden forecast-run index linkage to canonical run/model identifiers.

Validation:
- Unit tests for parameter forwarding and metadata completeness.
- Reproducibility checks for repeated runs under fixed inputs.

Exit criteria:
- Forecast artifacts and DB records can be traced to exact model/run configuration.

## Phase 4: Signal Engine Upgrade

Objectives:
- Replace the minimal terminal-close heuristic with horizon-aware scoring logic.

Planned changes:
- Redesign signal decision path to use path-level/horizon metrics and cost-aware thresholds.
- Preserve HOLD behavior semantics while reducing false positives.
- Store quality/confidence components used by the decision function.

Validation:
- Signal regression tests covering LONG/SHORT/HOLD edge cases.
- Back-compare old vs new signal outputs on representative windows.

Exit criteria:
- Signal decisions are explainable, cost-aware, and more robust than terminal-close-only logic.

## Phase 5: Canonical Validation Metrics

Objectives:
- Remove scoring divergence across validator, persistence, and dashboard summaries.

Planned changes:
- Establish one canonical scoring implementation shared by all paths.
- Align direction anchoring and first-horizon treatment consistently.
- Correct metric naming/semantics in query and UI layers.

Validation:
- Golden-case tests that assert identical direction/win-loss outcomes across all scoring consumers.
- Dashboard/API contract tests for corrected metric semantics.

Exit criteria:
- No metric drift between validation reports, DB outcomes, and dashboard views.

## Phase 6: Dataset Builder and Quality Enforcement

Objectives:
- Make dataset snapshots quality-aware in actual row selection, not metadata only.

Planned changes:
- Enforce quality_filter in snapshot export logic.
- Persist realized quality diagnostics and source composition details.
- Improve missing-volume/amount handling semantics for live vs historical parity.

Validation:
- Dataset tests proving filters change exported row sets correctly.
- Quality-grade consistency tests against expected threshold behavior.

Exit criteria:
- Dataset snapshots are auditable and quality-filter behavior is deterministic.

## Phase 7: Model Lifecycle and Promotion Governance

Objectives:
- Ensure candidate approval is based on candidate evidence only.

Planned changes:
- Make walk-forward evaluate selected candidate model explicitly.
- Rework promotion gate inputs to candidate-isolated metrics.
- Remove naming-based implicit promotion effects.
- Align shadow/primary status semantics for model comparison.

Validation:
- Promotion gate branch tests (pass/fail/warn) with candidate-only evidence.
- Walk-forward tests verifying model_version_id is truly exercised.

Exit criteria:
- No candidate can be approved/promoted without explicit candidate evaluation evidence.

## Phase 8: Dashboard and Scheduler Reliability Hardening

Objectives:
- Remove UI/API coupling faults and operational race conditions.

Planned changes:
- Fix duplicate UI ID/selector issues and response error handling behavior.
- Harden file-serving containment checks with path-safe logic.
- Replace latest-file artifact association patterns with deterministic run-bound metadata linkage.
- Preserve worker stale-warning accuracy and status clarity.

Validation:
- API and UI integration tests for predict/fetch/validate/baseline flows.
- Concurrency/regression tests around run artifact association.

Exit criteria:
- Dashboard actions are context-correct, failure-transparent, and race-resilient.

## Phase 9: Test Expansion, Verification, and Release Readiness

Objectives:
- Establish confidence gates for all high-risk behaviors and regression boundaries.

Planned changes:
- Expand unit/integration coverage for scoring, promotion, walk-forward, dataset filters, and dashboard action contracts.
- Add migration integrity and clean-install verification checks.
- Execute full verification runbook and document outcomes.

Validation:
- Full test suite pass.
- Migration pass on clean DB.
- End-to-end operational smoke pass across workers + dashboard.

Exit criteria:
- All phase acceptance criteria satisfied.
- No unresolved critical findings.

## 8. Phase Gating and Execution Order

Recommended execution order:
- Complete Phase 1 through Phase 2 before any production model governance updates.
- Complete Phase 5 before finalizing Phase 7 gate logic.
- Complete Phase 8 before final release verification in Phase 9.

Mandatory gate between phases:
- Each phase requires tests and acceptance criteria completed before moving to the next.

## 9. Deliverables

Phase 0 deliverable (this file):
- docs/kronos_full_repo_audit_and_implementation_plan.md

Post-implementation deliverable:
- docs/kronos_implementation_summary.md

## 10. Phase 0 Completion Checklist

- Full repository audit completed (bridge + relevant Kronos internals).
- Data-only safety boundary confirmed and retained.
- Known issue baseline captured and mapped to implementation phases.
- Phase 1 to 9 plan documented with objectives, validations, and exit criteria.
- No premature code implementation executed in Phase 0.
