# MODEL_PREDICTION_IMPLEMENTATION_PLAN.md

# Model Prediction Implementation Plan

## Summary

This plan fixes prediction trust before model optimization. The first priority is to make forecast validation, executed-trade metrics, candle integrity, and execution gating auditable and impossible to confuse. Fine-tuning and model changes are intentionally delayed until Phase 1 and Phase 2 prove that inputs, outcomes, and metrics are trustworthy.

All phases must preserve these rules:

- Do not optimize win rate before metrics are trustworthy.
- Do not treat forecast directional accuracy as executed trade profitability.
- Do not count HOLD, skipped, WATCH, or blocked predictions as wins.
- Do not evaluate partial future windows as final outcomes.
- Do not use future candles in features, labels, filters, thresholds, or regime logic.
- Keep all changes measurable and reversible.

## Phase 1: Measurement, Validation, and Metric Trust

### 1. Goal

Make forecast quality, signal quality, and executed-trade profitability separately measurable, auditable, and durable before changing model behavior or execution thresholds.

### 2. Root causes addressed

RC5, RC6, RC7, RC9, RC10, RC12; supports investigation of S4 and S5.

### 3. Files likely to change

- `src/prediction_store.py`
- `src/forecast_quality_validator.py`
- `src/forecast_scoring.py`
- `src/trade_execution.py`
- `src/dashboard_db.py`
- `src/dashboard_server.py`
- `src/dashboard_ui.py`
- `migrations/*.sql`
- `tests/test_forecast_scoring.py`
- `tests/test_dashboard_db.py`
- `tests/test_trade_execution.py`

### 4. Database migrations likely needed

Add immutable execution outcome fields to `executed_trades` or a linked trade outcome table:

- `final_outcome`
- `realized_gross_pnl`
- `realized_net_pnl`
- `entry_price`
- `exit_price`
- `entry_spread`
- `exit_spread`
- `estimated_fees`
- `estimated_slippage`
- `close_reason`
- `closed_at`
- `outcome_finalized_at`
- `validation_status_at_execution`
- `validation_score_at_execution`
- `execution_decision_reason`

Add forecast validation status fields that separate:

- partial validation progress
- final validation result
- terminal-horizon outcome
- path/TP/SL outcome
- per-horizon diagnostic outcomes

### 5. New services/classes/functions likely needed

- `ForecastMetricService`: computes forecast-only metrics by symbol, resolution, model, horizon, and time range.
- `SignalQualityService`: computes signal-level quality without mixing skipped or HOLD rows into wins.
- `ExecutedTradePerformanceService`: computes closed-trade win rate, expectancy, average win/loss, drawdown, spread impact, and slippage impact only from finalized executions.
- `BaselineComparisonService`: compares Kronos forecasts against last-close, random-direction, moving-average, momentum, and mean-reversion baselines using identical timestamps and actual candles.
- `TradeOutcomeFinalizer`: persists immutable execution outcomes when broker close data is available.
- `ValidationStatusClassifier`: separates `PARTIAL`, `FINAL_WIN`, `FINAL_LOSS`, `INSUFFICIENT_FUTURE`, and `VALIDATION_UNAVAILABLE`.

### 6. Tests to add

- Forecast directional hit rate excludes pending and partial final windows.
- HOLD, skipped, blocked, WATCH, WEAK_LONG, and WEAK_SHORT are never counted as wins.
- Executed trade win rate uses only closed trades with finalized net P/L.
- Forecast terminal outcome and path/TP/SL outcome are computed and stored separately.
- Baselines are evaluated on the same timestamps, horizons, and actual candles as Kronos.
- Partial future windows produce partial/progress status only, never final metrics.
- Dashboard summary keeps forecast accuracy, signal quality, and executed performance separate.

### 7. Logging/audit data to add

- Forecast validation event with `run_id`, horizon, validation mode, final/partial status, actual window completeness, and baseline comparison.
- Trade outcome finalization event with immutable realized P/L, spread, slippage, fee estimates, and close reason.
- Dashboard metric source audit showing which table and filters generated each displayed metric.
- Baseline comparison audit by run, symbol, resolution, model version, horizon, and cost assumptions.

### 8. Acceptance criteria

- Dashboard no longer presents forecast win rate as executed trade win rate.
- Executed trade win rate is shown only from closed executed trades with finalized outcome fields.
- Forecast quality displays directional forecast hit rate separately from signal quality and trade profitability.
- Partial actual windows never update final win/loss metrics.
- Terminal-vs-path validation is visible and stored separately.
- Baseline comparison exists for validated runs and is filterable by symbol, resolution, model, horizon, and date range.
- Existing tests pass or failures are documented with exact causes.

### 9. Rollback notes

- Keep new outcome fields additive and nullable during rollout.
- Preserve existing dashboard fields until replacement metrics are verified.
- Feature-flag new dashboard metric panels if needed.
- Do not delete historical prediction outcome rows.

### 10. Risk level

High. This changes metric definitions and dashboard interpretation, but should be implemented additively to avoid disrupting live prediction and execution.

### 11. What must NOT be changed in this phase

- Do not fine-tune Kronos.
- Do not change prediction scheduling.
- Do not change execution thresholds except to persist validation/execution state.
- Do not change candle ingestion behavior.
- Do not optimize signal thresholds or win rate.

## Phase 2: Data and Model Input Correctness

### 1. Goal

Ensure every live prediction is based on a continuous, closed, correctly aligned candle window with trustworthy OHLCV/OHLCVA fields and auditable source composition.

### 2. Root causes addressed

RC1, RC2, RC3, RC4, RC11, RC12; investigates S1, S2, and S3.

### 3. Files likely to change

- `src/main_prediction_scheduler.py`
- `src/main_forecast_latest.py`
- `src/main_run_kronos_predict.py`
- `src/kronos_mapper.py`
- `src/prediction_store.py`
- `src/data_quality.py`
- `src/candle_context.py`
- `src/dashboard_server.py`
- `src/dashboard_ui.py`
- `tests/test_prediction_scheduler_websocket_gate.py`
- `tests/test_prediction_store_sources.py`
- `tests/test_main_run_kronos_predict.py`
- `tests/test_dashboard_ui_contract.py`

### 4. Database migrations likely needed

Add or extend audit fields on prediction runs or related metadata:

- `input_missing_candle_count`
- `input_largest_gap_minutes`
- `input_gap_list_json`
- `input_source_counts_json`
- `input_last_timestamp`
- `input_expected_last_timestamp`
- `input_closed_candle_verified`
- `input_feature_columns_json`
- `amount_mode`
- `forecast_timestamp_verified`

Optional candle-source integrity fields:

- `volume_source`
- `amount_source`
- `is_closed`
- `last_ws_update_at`
- `rest_preserved_fields_json`

### 5. New services/classes/functions likely needed

- `PredictionInputGate`: validates closed-candle alignment, exact cadence, no gaps, no duplicates, row count, source policy, and terminal timestamp.
- `CandleSourceAudit`: computes source counts and mixed-source risk for each input window.
- `ClosedCandleAlignmentChecker`: verifies last input timestamp equals the expected closed candle boundary.
- `ForecastTimestampEqualityChecker`: asserts each forecast timestamp equals `last_input_timestamp + horizon_index * resolution`.
- `AmountModeResolver`: chooses derived `close * volume` amount or explicit OHLCV-only mode.
- `SafeOhlcvUpsertPolicy`: prevents WebSocket null volume/amount from overwriting non-null REST values.

### 6. Tests to add

- Prediction is hard-blocked when missing candle count is greater than zero for strict live mode.
- Prediction is hard-blocked when largest gap exceeds one resolution interval.
- Prediction is hard-blocked when the terminal candle is stale, unclosed, duplicated, or not aligned to the expected boundary.
- WebSocket OHLC upsert does not overwrite existing non-null REST volume or amount with null/zero values.
- Source-count metadata is persisted for every prediction run.
- Dashboard manual lookback either passes matching `--max` or rejects values above the supported context limit.
- Forecast timestamps must exactly equal generated future timestamps.
- Partial actual fetch cannot mark final validation complete.

### 7. Logging/audit data to add

- `prediction_input_gate.pass` and `prediction_input_gate.block` events with all blocking reasons.
- Per-run gap list, source counts, feature columns, amount mode, and terminal timestamp.
- WebSocket candle overwrite-prevention logs showing preserved REST fields.
- Forecast timestamp equality audit with generated vs persisted timestamp hashes.
- Dashboard manual prediction audit showing requested lookback, effective lookback, and model max context.

### 8. Acceptance criteria

- Live predictions are blocked on material candle gaps, stale terminal candles, duplicate timestamps, unclosed terminal candles, or failed timestamp equality.
- WebSocket null volume/amount cannot degrade richer REST candle fields.
- Every prediction run records source counts, gap metadata, feature columns, amount mode, and terminal timestamp.
- The dashboard cannot silently request lookback greater than the effective `--max`.
- Amount handling is explicit: either derived OHLCVA is enabled and measured, or OHLCV-only mode is declared and tested.
- Forecast timestamp equality is enforced before persistence.

### 9. Rollback notes

- Keep new input gates configurable with strict live defaults and emergency bypass only for research/offline modes.
- Preserve existing REST and WebSocket ingestion paths.
- Make amount derivation mode reversible via configuration.
- Store audit metadata additively before relying on it for hard blocking in production.

### 10. Risk level

Critical. Blocking bad inputs may reduce prediction frequency, but this is required before measuring or improving model performance.

### 11. What must NOT be changed in this phase

- Do not fine-tune Kronos.
- Do not alter signal execution policy except where partial validation state must be protected.
- Do not treat derived amount as proven better until Phase 4 comparison.
- Do not mix REST and WebSocket candles without source-count auditing.
- Do not evaluate unclosed or partial candles as final actuals.

## Phase 3: Signal Filtering and Execution Gating

### 1. Goal

Prevent weak, blocked, unavailable, or unvalidated signals from becoming executed trades, and require expected edge to survive validation, spread, fees, slippage, and regime blockers.

### 2. Root causes addressed

RC6, RC7, RC8, RC9; supports S4 and S5.

### 3. Files likely to change

- `src/trade_execution.py`
- `src/signal_config.py`
- `src/signal_blockers.py`
- `src/main_validate_signal_context.py`
- `src/signal_validation_store.py`
- `src/prediction_store.py`
- `src/dashboard_db.py`
- `src/dashboard_ui.py`
- `tests/test_trade_execution.py`
- `tests/test_signal_validation_pipeline.py`
- `tests/test_signal_improvements.py`

### 4. Database migrations likely needed

Add execution decision audit fields:

- `execution_blocked_reason`
- `execution_gate_version`
- `raw_signal`
- `validation_status_at_decision`
- `validation_score_at_decision`
- `expected_move_pct`
- `expected_net_edge_pct`
- `spread_pct_at_decision`
- `fee_pct_assumption`
- `slippage_pct_assumption`
- `regime_blockers_json`

### 5. New services/classes/functions likely needed

- `ExecutionGate`: single allow/deny authority for trade execution.
- `ValidationDirectionMatcher`: ensures raw signal direction matches validation status direction.
- `ExpectedEdgeCalculator`: computes movement after spread, fees, slippage, and safety margin.
- `NoTradeZonePolicy`: blocks trades where expected edge is too close to costs or uncertainty.
- `RegimeExecutionBlocker`: blocks low-volume, high-spread, high-volatility, choppy, or untrusted regimes.
- `ExecutionDecisionAuditor`: persists all allow/block reasons.

### 6. Tests to add

- No execution for `BLOCKED`, `HOLD`, `WATCH`, `VALIDATION_UNAVAILABLE`, `WEAK_LONG`, or `WEAK_SHORT`.
- Execution allowed only for approved directional validation statuses with minimum validation score.
- Raw LONG cannot execute if validation status is SHORT, WEAK_SHORT, HOLD, WATCH, or BLOCKED.
- Raw SHORT cannot execute if validation status is LONG, WEAK_LONG, HOLD, WATCH, or BLOCKED.
- Expected edge must exceed spread, fees, slippage, and configured safety margin.
- Missing spread or stale spread blocks execution unless explicitly configured for offline research.
- Regime blockers prevent execution and appear in dashboard/audit output.
- Execution decisions are persisted even when blocked.

### 7. Logging/audit data to add

- Every execution evaluation logs allow/block result, raw signal, validation status, score, spread, costs, edge, regime blockers, and gate version.
- Blocked trades are auditable without creating broker orders.
- Dashboard exposes execution decision reasons for latest signals.
- Spread/slippage assumptions are stored with each decision.

### 8. Acceptance criteria

- Validation status is a hard execution gate.
- `BLOCKED`, `HOLD`, `WATCH`, `VALIDATION_UNAVAILABLE`, `WEAK_LONG`, and `WEAK_SHORT` never execute.
- Minimum validation score is enforced.
- Direction mismatch between raw signal and validation status blocks execution.
- Expected edge must remain positive after spread, fees, slippage, and safety margin.
- No-trade zone and regime blockers are visible and tested.
- Executed trades persist validation and decision context at execution time.

### 9. Rollback notes

- Keep execution gate versioned.
- Allow rollback to previous gate only through explicit configuration and log warning.
- Preserve blocked-decision audit rows for comparison.
- Do not delete existing historical executed trades.

### 10. Risk level

Critical. This may sharply reduce trade count, but it directly prevents validation-bypassed execution.

### 11. What must NOT be changed in this phase

- Do not loosen thresholds to increase activity.
- Do not treat heuristic confidence as calibrated probability.
- Do not change model inputs.
- Do not fine-tune Kronos.
- Do not convert blocked/skipped decisions into wins.

## Phase 4: Model Improvements

### 1. Goal

Improve model and feature performance only after validation metrics and data correctness are trusted.

### 2. Root causes addressed

RC4, RC5, RC6, RC7; informed by S5.

### 3. Files likely to change

- `src/main_run_kronos_predict.py`
- `src/main_prepare_kronos_input.py`
- `src/feature_engineering.py`
- `src/baseline_forecasts.py`
- `src/main_generate_baseline_forecasts.py`
- `src/model_registry.py`
- `src/main_kronos_auto_finetune.py`
- `src/main_prepare_finetune_dataset.py`
- `src/main_finetune_kronos.py`
- `tests/test_main_run_kronos_predict.py`
- `tests/test_model_registry_performance.py`
- `tests/test_kronos_auto_finetune.py`

### 4. Database migrations likely needed

Add experiment/model comparison metadata if not already sufficient:

- `feature_set_name`
- `amount_mode`
- `horizon_policy`
- `regime_feature_version`
- `calibration_version`
- `training_data_start`
- `training_data_end`
- `validation_data_start`
- `validation_data_end`
- `leakage_check_status`
- `baseline_comparison_summary_json`

### 5. New services/classes/functions likely needed

- `FeatureSetRegistry`: tracks OHLCV, derived OHLCVA, multi-timeframe, and regime-enhanced input variants.
- `HorizonSkillEvaluator`: measures skill by terminal horizon, per-horizon direction, and path outcome.
- `RegimeFeatureBuilder`: builds regime inputs using only past candles.
- `ConfidenceCalibrator`: maps heuristic scores to empirical probabilities by symbol, horizon, and regime.
- `LeakageSafeDatasetBuilder`: creates time-split datasets without future leakage.
- `ModelPromotionEvaluator`: promotes models only when they beat baselines after costs.

### 6. Tests to add

- OHLCV and derived OHLCVA variants are evaluated on identical windows.
- Derived amount uses only current/past candle fields, never future actuals.
- Multi-timeframe and regime features use closed candles only.
- Horizon-specific metrics are calculated separately and cannot be merged into one misleading score.
- Confidence calibration bins compare predicted confidence to realized outcome frequency.
- Fine-tuning datasets enforce time-based splits and leakage checks.
- Model promotion requires baseline outperformance after costs.

### 7. Logging/audit data to add

- Experiment run metadata with model, feature set, amount mode, horizon policy, and validation split.
- Baseline comparison summary for every candidate model or feature variant.
- Calibration report with confidence buckets and realized hit rates.
- Leakage-check result before any fine-tuning run is accepted.
- Model promotion/rejection reason.

### 8. Acceptance criteria

- No model improvement work begins until Phase 1 and Phase 2 acceptance criteria are met.
- OHLCV vs derived OHLCVA comparison is measured before selecting a production mode.
- Horizon-specific skill is known before changing the trading horizon.
- Multi-timeframe/regime-enhanced inputs are tested without leakage.
- Confidence is calibrated against rolling live or leakage-safe historical outcomes.
- Fine-tuning is only considered after baseline outperformance and leakage-safe validation.

### 9. Rollback notes

- Keep old model and feature set selectable.
- Version every feature set and calibration map.
- Promote new models behind explicit registry status.
- Preserve old prediction path until replacement is proven.

### 10. Risk level

High. Model changes can create false improvement if measurement or data quality is weak, so this phase must remain gated by earlier phases.

### 11. What must NOT be changed in this phase

- Do not fine-tune before Phase 1 and Phase 2 are complete.
- Do not use future candles in features, labels, filters, thresholds, or regime tags.
- Do not optimize thresholds on the same period used for reporting.
- Do not promote a model that only improves forecast hit rate but worsens executed expectancy after costs.
- Do not collapse terminal, path, and per-horizon validation into one metric.

## Phase 5: Dashboard and Reporting Trust

### 1. Goal

Make dashboard and reports impossible to misread by clearly separating forecast accuracy, signal quality, validation state, execution decisions, and closed-trade profitability.

### 2. Root causes addressed

RC5, RC6, RC7, RC9, RC10, RC11, RC12; surfaces S1-S5 diagnostics.

### 3. Files likely to change

- `src/dashboard_ui.py`
- `src/dashboard_db.py`
- `src/dashboard_server.py`
- `src/prediction_log_report.py`
- `src/main_generate_prediction_log_report.py`
- `src/main_signal_validation_report.py`
- `src/main_cumulative_forecast_report.py`
- `docs/DASHBOARD_FUNCTIONALITY_AUDIT.md`
- `tests/test_dashboard_ui_contract.py`
- `tests/test_dashboard_db.py`
- `tests/test_dashboard_server_status_warnings.py`

### 4. Database migrations likely needed

No major dashboard-only migration should be required if Phases 1-3 add the needed fields. If missing, add read-optimized summary/materialized fields for:

- forecast directional hit rate
- signal quality outcomes
- executed trade net P/L
- expectancy
- average win/loss
- drawdown
- spread impact
- slippage impact
- validation blockers
- execution decision reasons
- stale/partial/latest prediction state

### 5. New services/classes/functions likely needed

- `DashboardMetricPresenter`: labels and groups metrics by source and meaning.
- `PredictionStatePresenter`: classifies latest prediction as latest, stale, partial, blocked, or validation-unavailable.
- `ValidationBlockerPresenter`: exposes blockers and score components.
- `ExecutionDecisionPresenter`: exposes why a signal executed or did not execute.
- `PerformanceReportService`: creates forecast, signal, and executed-trade report sections without metric mixing.

### 6. Tests to add

- Forecast win rate label is replaced with directional forecast hit rate.
- Executed trade win rate is sourced only from closed finalized executions.
- Dashboard cards expose expectancy, average win/loss, drawdown, spread impact, and slippage impact.
- Validation blockers are visible for blocked, WATCH, HOLD, and unavailable states.
- Execution decision reasons are visible for executed and non-executed signals.
- Stale, partial, latest, and validation-unavailable prediction states render distinctly.
- Manual prediction UI cannot silently request lookback above effective model context.
- Dashboard API contracts are updated and covered by contract tests.

### 7. Logging/audit data to add

- Dashboard metric query audit with source table, filters, and computed metric type.
- UI/API warning when partial validation is displayed.
- UI/API warning when forecast metrics have insufficient samples.
- Dashboard status audit for stale prediction, blocked prediction, partial future window, and source-mixed input window.

### 8. Acceptance criteria

- Dashboard uses “directional forecast hit rate” instead of forecast win rate.
- Executed trade win rate appears only from closed finalized executed trades.
- Forecast accuracy, signal quality, and executed profitability are visually and semantically separate.
- Expectancy, average win/loss, drawdown, spread impact, and slippage impact are displayed where data exists.
- Validation blockers and execution decision reasons are visible per signal.
- Stale, partial, latest, and unavailable states are clear.
- Dashboard functionality audit is updated for all changed controls, routes, endpoints, and metrics.

### 9. Rollback notes

- Keep old API fields temporarily while new dashboard fields are introduced.
- Use additive dashboard payload fields before removing deprecated labels.
- Preserve raw metric endpoints for debugging.
- Feature-flag new reporting panels if needed.

### 10. Risk level

Medium. Dashboard changes mostly affect interpretation, but incorrect labels can still cause dangerous operational decisions.

### 11. What must NOT be changed in this phase

- Do not hide bad metrics to make performance look better.
- Do not count HOLD/skipped predictions as wins.
- Do not show partial future validation as final.
- Do not label forecast directional accuracy as profitability.
- Do not alter execution behavior from dashboard-only reporting work.

## Cross-Phase Final Acceptance Criteria

- Every live prediction has auditable input quality, source counts, feature columns, amount mode, gap metadata, and timestamp equality checks.
- Every final forecast metric uses complete future windows only.
- Forecast quality, signal quality, and executed-trade profitability are stored and displayed separately.
- Every executed trade has immutable realized outcome fields once closed.
- Execution is hard-blocked for invalid validation statuses and insufficient expected edge.
- Dashboard reports closed-trade win rate only from finalized closed executed trades.
- Fine-tuning and model promotion occur only after leakage-safe validation and baseline outperformance after costs.
- All new behavior has tests, audit logs, and rollback paths.
