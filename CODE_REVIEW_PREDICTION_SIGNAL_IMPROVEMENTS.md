# CODE_REVIEW_PREDICTION_SIGNAL_IMPROVEMENTS.md

## 1. Executive Summary

Overall project health for prediction and signal quality: High risk.

The codebase has a solid local-monolith structure for ingestion, forecasting, persistence, validation, shadow evaluation, model registration, and dashboarding. The main problems are not readability or missing components; they are incorrect evaluation boundaries and incomplete decision logic. Several parts of the system present model-comparison, walk-forward, and promotion workflows as if they are production-ready, but the current implementations do not actually measure the candidate model on isolated evidence.

The most important pattern across the review is this:

- Signal generation is still driven by a very small heuristic.
- Promotion and walk-forward surfaces expose metrics that are incomplete or disconnected from the candidate model.
- Shadow/model-comparison paths still contain status semantics that drift away from the live signal semantics.

That combination means the system can generate live signals, store outcomes, and show model-performance dashboards, while still making incorrect decisions about which model is actually better and why.

Review scope:

- Reviewed prediction, signal, scoring, dashboard, streaming, feature, dataset, backfill, validation, maintenance, and promotion-related modules.
- Reviewed migrations relevant to signal/outcome/model-evaluation flows.
- Did not run live Capital.com traffic, Kronos fine-tuning, or full walk-forward experiments during this review phase.
- Did not change runtime code. This report is the only artifact created.

Recommended implementation order:

1. Repair candidate evaluation and promotion logic before training or promoting any new model.
2. Align shadow/model-performance status semantics with the new primary-window signal semantics.
3. Replace the terminal-close signal heuristic with a horizon-aware, risk-aware decision layer.
4. Fix dataset-quality enforcement and live data-shape consistency before trusting new training data.
5. Add regression tests around promotion, walk-forward, and shadow evaluation before further feature work.

## 2. Critical Issues

### CR-001: Walk-forward experiments do not evaluate the selected model

Severity: Critical

Area: Backtesting / Model Validation / Promotion Readiness

Files and methods involved:

- `src/walk_forward.py:78-140` `create_walk_forward_experiment(...)`
- `src/walk_forward.py:147-237` `run_walk_forward_experiment(...)`

What is happening:

- The experiment schema accepts and stores `model_version_id`.
- `run_walk_forward_experiment(...)` never uses that model identifier.
- Each window only evaluates `_baseline_forecast(...)` outputs for the configured baseline methods.
- The run is still marked `COMPLETED` and returned as a finished walk-forward experiment.
- `beats_naive_rate_pct` is left as `None` in both the run summary and the query payload.

Why this matters:

The system currently exposes a walk-forward capability that does not test Kronos or any candidate model at all. Any report or dashboard output built from this flow is baseline-only evidence presented through a model-validation interface. That is a hard blocker for trustworthy promotion decisions.

Recommendation:

- Introduce a model-runner abstraction that can execute the requested `model_version_id` per window.
- Persist separate metrics for candidate, active baseline, and naive baseline per window.
- Compute and store `beats_naive_rate_pct` instead of returning `None`.
- Do not mark a walk-forward experiment `COMPLETED` unless candidate-model windows were actually evaluated.

### CR-002: Promotion gates are disconnected from candidate-model evidence

Severity: Critical

Area: Model Registry / Promotion Logic

Files and methods involved:

- `src/model_registry.py:146-175` `_active_metrics(...)`
- `src/model_registry.py:177-290` `model_performance(...)`
- `src/model_registry.py:293-360` `evaluate_promotion(...)`

What is happening:

- `model_performance(...)` builds active metrics from aggregate `prediction_outcomes`, but horizon payloads only populate `active_accuracy_pct`; `shadow_accuracy_pct` and `baseline_accuracy_pct` remain `None`.
- `evaluate_promotion(...)` hardcodes `shadow_mape = None`.
- The horizon gate checks required horizons against `active_accuracy_pct`, not candidate/shadow horizon accuracy.
- `baseline_beat_rate` is always evaluated with a `None` metric.

Why this matters:

The promotion system cannot currently answer the real question: whether the candidate model outperforms the active model and baselines on candidate-specific evidence. Some gates are effectively unevaluable, some are evaluated against the wrong series, and the resulting gate table can look formal while being logically invalid.

Recommendation:

- Build candidate-specific aggregates from `shadow_evaluations` and baseline-evaluation artifacts.
- Compute candidate MAPE/RMSE and candidate per-horizon accuracy directly.
- Evaluate required horizons against candidate metrics, not active metrics.
- Replace placeholder `None` gate inputs with real baseline-beat calculations, or omit the gate until implemented.

### CR-003: Auto-finetune promotion can approve a candidate using incumbent-model metrics

Severity: Critical

Area: Auto Fine-Tuning / Candidate Approval

Files and methods involved:

- `src/main_auto_finetune_worker.py:139-171` `_latest_live_metrics(...)`
- `src/main_auto_finetune_worker.py:239-240` training/evaluation dataset assignment
- `src/main_auto_finetune_worker.py:247-296` `_promotion_decision(...)` and `register_model_version(...)`
- `src/main_auto_finetune_worker.py:357-390` post-training promotion update

What is happening:

- The worker assigns `training_dataset_id` and `evaluation_dataset_id` to the same snapshot.
- Promotion decisions are driven by `_latest_live_metrics(...)`, which aggregates validated live outcomes for the symbol/resolution, not isolated candidate-model evidence.
- The worker can register the candidate model version as `approved` when those aggregate live metrics cross the threshold.

Why this matters:

This allows a newly trained candidate to inherit the incumbent model's live track record. In practice, a candidate can be approved without demonstrating its own out-of-sample or shadow performance. That is the single highest-risk path in the current training/promotion flow.

Recommendation:

- Create disjoint training and evaluation datasets.
- Require candidate evaluation on holdout windows and/or shadow runs before approval.
- Remove approval-by-incumbent-metric logic from the worker.
- Route all final approvals through repaired promotion gates rather than direct worker-side status changes.

### CR-004: Shadow evaluation still uses the old aggregate signal-status semantics

Severity: Critical

Area: Shadow Evaluation / Signal Outcome Semantics

Files and methods involved:

- `src/prediction_store.py:735-792` `_upsert_shadow_evaluation(...)`

What is happening:

- The query selects `s.status AS active_status` from `signals`.
- The function then ignores that persisted status and recomputes `active_status` via `signal_status_from_counts(active_wins, active_losses)`.

Why this matters:

The repository already moved live signal status to a primary-window interpretation. This function reintroduces the old aggregate-wins/losses logic inside the shadow-comparison path, so model comparisons can silently diverge from the status semantics now used by live signals and the dashboard.

Recommendation:

- Use the persisted `signals.status` value as the active status for shadow comparisons.
- If shadow status also needs to be primary-window based, derive both active and shadow status from the same horizon-1 rule.
- Add a regression test that proves shadow disagreement and model-performance tables match the live signal semantics.

## 3. High Issues

### HI-001: Signal generation is a terminal-close heuristic, not a trade-quality evaluator

Severity: High

Area: Signal Logic / False-Signal Reduction

Files and methods involved:

- `src/prediction_store.py:303-333` `_signal_from_forecast(...)`

What is happening:

- The signal decision only compares `final_close` to `last_input_close`.
- Confidence is a linear transform of terminal move magnitude divided by `cost_threshold_pct * 4`.
- The logic does not inspect forecast path quality, horizon agreement, volatility regime, candle dispersion, multi-timeframe context, or risk/reward profile.

Why this matters:

This is too weak to support the project's stated goals around prediction accuracy, signal quality, false-signal reduction, and volatility-aware behavior. It also explains why HOLD behavior is highly sensitive to a single minimum-confidence threshold.

Recommendation:

- Score the full forecast path, not only the last predicted close.
- Require consistency across early horizons before emitting LONG or SHORT.
- Normalize expected edge by volatility and spread/cost regime.
- Add explicit risk/reward gating using projected TP/SL geometry and primary-window edge.

### HI-002: Dataset `quality_filter` is accepted and stored, but never enforced

Severity: High

Area: Dataset Management / Training Integrity

Files and methods involved:

- `src/dataset_snapshots.py:75-122` `create_dataset_snapshot(...)`
- `src/dashboard_server.py:731-742` dataset snapshot API path
- `src/main_auto_finetune_worker.py:228-240` snapshot creation for auto-finetune

What is happening:

- `quality_filter` is accepted in the API and persisted into snapshot metadata.
- `create_dataset_snapshot(...)` loads candles and calculates quality, but never applies the requested quality constraints to the rows being exported.

Why this matters:

The system can claim to be building curated training, validation, promotion, or backtest datasets while actually exporting the full raw interval. That undermines reproducibility and any later claims about data-quality-aware training.

Recommendation:

- Implement real row/window filtering based on minimum grade, gap count, duplicate count, staleness, and source mix.
- Include the realized filter outcome in snapshot metadata.
- Fail fast when a requested quality filter would produce an unusable dataset.

### HI-003: Live WebSocket ingestion degrades both throughput and feature fidelity

Severity: High

Area: Live Data Pipeline / Training-Serving Consistency

Files and methods involved:

- `src/capital_ws_ohlc_client.py:255-271` `_append_row(...)`
- `src/kronos_mapper.py:114-145` `ws_ohlc_to_kronos_row(...)`

What is happening:

- Every incoming OHLC row is converted to a one-row DataFrame, concatenated into an in-memory DataFrame, sorted, deduplicated, and written back to the full CSV file.
- WebSocket-mapped OHLC rows set `volume` and `amount` to `0.0`.

Why this matters:

- The append path is unnecessarily expensive for a continuously running stream.
- The live data shape diverges from historical REST data because liquidity-related fields collapse to zero.
- Any downstream quality scoring or feature generation that depends on volume/amount sees a structurally different live regime than the training data.

Recommendation:

- Move to buffered append-only persistence or a ring-buffer writer instead of full-frame CSV rewrites.
- Preserve broker volume/amount when available; otherwise mark them explicitly unavailable rather than silently zeroing them.
- Reflect missing-volume state in feature engineering and data-quality grading.

### HI-004: Model promotion state is partly driven by naming conventions instead of workflow evidence

Severity: High

Area: Model Registry / Lineage Integrity

Files and methods involved:

- `src/prediction_store.py:387-401` `save_prediction_run(...)`
- `src/model_registry.py:34-90` `register_model_version(...)`

What is happening:

- Every prediction run re-registers the model version.
- `save_prediction_run(...)` sets `promotion_status="promoted"` whenever `model_name.lower().endswith("base")`.
- `register_model_version(...)` preserves an already promoted state on future upserts.

Why this matters:

Promotion state becomes a side effect of model naming plus ordinary prediction persistence, rather than a separate governance decision. Once a version lands in `promoted`, later writes will keep that state even if supporting evidence changes.

Recommendation:

- Separate model registration from model promotion.
- Remove naming-based promotion defaults.
- Make promotion an explicit state transition driven only by validated gate results.

### HI-005: Forecast metadata association is race-prone under concurrent prediction runs

Severity: High

Area: Orchestration / Run Integrity

Files and methods involved:

- `src/main_forecast_latest.py:211-226`

What is happening:

- After running `main_run_kronos_predict.py`, the orchestrator selects the metadata file by taking the lexicographically latest matching `forecast_metadata_*.json` file from the output directory.

Why this matters:

In a system with a scheduler, dashboard-triggered predictions, and shadow runs, selecting the latest file from disk is not a reliable way to associate post-processing with the run that just completed. Data-quality persistence and shadow-model attachment can be written against the wrong run if two predictions overlap.

Recommendation:

- Have the prediction subprocess return the exact metadata path it created.
- Or generate a unique run stamp in the parent and pass it through explicitly so all artifacts are deterministic and run-scoped.

## 4. Medium Issues

### MI-001: Feature engineering is too shallow for the repo's stated signal ambitions

Severity: Medium

Area: Feature Design / Regime Detection / Multi-Timeframe Context

Files and methods involved:

- `src/feature_engineering.py:96-109` `generate_features(...)`

What is happening:

- The feature set is currently single-timeframe and mostly local to each candle sequence.
- `source_quality_score` is hardcoded to `1.0`.
- There is no explicit higher-timeframe trend state, no volatility regime bucket, no spread/cost proxy, and no market-structure confirmation feature.

Why this matters:

The repository goals mention market regime detection, multi-timeframe confirmation, and improved false-signal filtering. The current feature layer is not yet rich enough to support those goals in a principled way.

Recommendation:

- Add higher-timeframe trend context, regime labels, liquidity/staleness features, and explicit data-source-quality features.
- Ensure live and historical feature computation use the same missing-data semantics.

### MI-002: Validation throughput is limited by serial subprocess orchestration

Severity: Medium

Area: Validation Operations / Freshness

Files and methods involved:

- `src/main_validation_worker.py:68-129` `_validate_run(...)` and `_run_validation_cycle(...)`

What is happening:

- Each due run fetches actuals through one subprocess and validates through another.
- Runs are processed serially in a loop.
- The worker stops early only on rate-limit detection; there is no per-run retry/backoff strategy or batched data fetch.

Why this matters:

As run volume grows, validation freshness will lag. That delay feeds back into stale dashboard metrics, slower promotion evidence, and slower correction of signal statuses.

Recommendation:

- Batch actual-candle fetches where possible.
- Collapse fetch+validate into a shared library path where subprocess isolation is not required.
- Add structured retry handling for transient API failures.

### MI-003: Dashboard control-plane jobs are synchronous and authentication is opt-in

Severity: Medium

Area: Operations / Dashboard Safety

Files and methods involved:

- `src/dashboard_server.py:135-162` `_require_auth(...)` and `_run(...)`
- `src/dashboard_server.py:807` server bootstrap

What is happening:

- Dashboard actions execute long-running subprocesses directly inside request-handling threads.
- If `DASHBOARD_API_TOKEN` is unset, all dashboard actions are accepted.

Why this matters:

This is not the main prediction-quality defect, but it raises the odds of overlapping manual actions, run-association races, and unsafe exposure if the server is ever bound beyond localhost.

Recommendation:

- Move long-running actions to a queued worker model.
- Fail closed when auth is not configured, or enforce localhost-only binding explicitly.

## 5. Testing Gaps

The current test suite covers several worker and storage paths, but the highest-risk review findings are lightly covered or uncovered.

Priority gaps:

- No walk-forward tests proving the requested `model_version_id` is actually evaluated.
- No promotion-gate tests proving candidate metrics, baseline beat rate, and per-horizon gates are computed from the correct evidence.
- No regression test for `_upsert_shadow_evaluation(...)` after the move to primary-window signal status.
- No concurrency test for `main_forecast_latest.py` artifact association.
- No dataset-snapshot tests proving `quality_filter` changes the exported row set.

## 6. Recommended Implementation Sequence

1. Freeze auto-promotion of candidate models until CR-001 through CR-004 are fixed.
2. Repair `walk_forward.py`, `model_registry.py`, and `main_auto_finetune_worker.py` as one evaluation-governance slice.
3. Align shadow evaluation and model-performance summaries with persisted primary-window signal status.
4. Replace `_signal_from_forecast(...)` with a horizon-aware signal engine that consumes path, volatility, and risk/reward evidence.
5. Enforce dataset quality filters and fix live data-shape consistency before using more auto-finetune output.
6. Add targeted regression tests for promotion, walk-forward, shadow status, and run-artifact association.

## 7. Final Assessment

This repository is close to being a solid experimentation and live-signal platform, but the current evaluation layer overstates how much trustworthy model-selection evidence it actually has. The highest-value next step is not adding more heuristics or UI. It is repairing the measurement system so that candidate models, live signals, and promotion decisions all speak the same language and are backed by isolated evidence.