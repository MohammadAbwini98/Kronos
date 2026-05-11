# Model Prediction Weakness and Low Win Rate Analysis

## 1. Executive Summary

The weak prediction quality and low executed trade win rate are not caused by one isolated model issue. The main causes are pipeline-level: imperfect candle continuity, incomplete model inputs, weak forecast quality measurement, heuristic confidence, signal validation that is not consistently enforced before execution, and dashboard statistics that mix forecast-direction accuracy with trade profitability.

Most important confirmed findings:

- The latest model input had 512 rows, but the data-quality metadata reports 26 missing 5-minute candles and a largest gap of 125 minutes in `output/forecast_metadata_ETHUSD_MINUTE_5_20260509T141504Z.json`.
- The model receives OHLCV plus `amount`, but `amount` is always zero/unavailable for Capital.com mappings, so the Kronos OHLCVA context is incomplete.
- WebSocket OHLC rows can overwrite stored candles with higher source priority while mapping `volume`/`amount` as missing or coerced values, degrading volume/context features.
- Forecast validation is present, but recent database totals for ETHUSD/MINUTE_5 show 7,452 `LOSS` vs 3,649 `WIN` forecast outcomes, about 32.9% directional win rate excluding pending rows.
- Many executed trades are linked to signals whose current validation status is `BLOCKED`, `HOLD`, `WATCH`, or `VALIDATION_UNAVAILABLE`; execution policy does not hard-block on that validation status.
- Dashboard win-rate style metrics are mostly forecast-candle directional metrics, not executed-trade profitability after spread, fees, slippage, and realized P/L.

The next step should be measurement and validation, not fine-tuning. The system first needs trustworthy candle closure checks, source integrity, model input audit logging, baseline comparisons, and execution gating that respects validation.

## 2. End-to-End Flow Map

Market data flow:

1. Capital.com REST historical prices are fetched in `src/main_forecast_latest.py` and mapped by `src/kronos_mapper.py::capital_prices_to_kronos_df`.
2. Capital.com WebSocket OHLC updates are handled by `src/capital_ws_ohlc_client.py::_handle_message`, mapped by `src/kronos_mapper.py::ws_ohlc_to_kronos_row`, and stored through `src/prediction_store.py::upsert_ohlcv_df`.
3. Candles are stored in `ohlcv_candles` from `migrations/001_init.sql`, unique by provider, symbol, epic, resolution, price_side, timestamp.
4. The scheduler in `src/main_prediction_scheduler.py::_websocket_prediction_gate` decides whether a prediction cycle may run.
5. `src/main_forecast_latest.py::main` fetches recent historical prices, drops unclosed candles, writes the Kronos input CSV, persists input candles, and starts `src/main_run_kronos_predict.py`.
6. `src/main_run_kronos_predict.py::run_prediction` selects feature columns, builds `x_timestamp` and `y_timestamp`, calls `KronosPredictor.predict`, validates forecast structure, writes output artifacts, and persists the prediction run.
7. `src/prediction_store.py::save_prediction_run` stores `prediction_runs`, `forecast_candles`, `prediction_outcomes`, and one `signals` row.
8. `src/main_validate_signal_context.py::run_validation` applies higher-timeframe, spread, volume, volatility, and scoring checks.
9. `src/trade_execution.py::TradeExecutionPolicy.evaluate` decides whether to queue/place a trade.
10. `src/prediction_store.py::update_predictions_with_actuals` validates forecast outcomes once actual candles exist.
11. `src/dashboard_server.py` and `src/dashboard_db.py` expose status, signals, validation, execution, and summary metrics to the dashboard.

## 3. Confirmed Root Causes

### RC1: Recent model input contains material candle gaps

- Severity: Critical
- Area: Data
- Evidence: `output/forecast_metadata_ETHUSD_MINUTE_5_20260509T141504Z.json`; `src/data_quality.py::analyze_ohlcv_quality` lines 66-157
- Evidence observed: `lookback_rows_actual=512`, `missing_candle_count=26`, `largest_gap_minutes=125`, `quality_grade=B`.
- Explanation: A 5-minute sequence with a 125-minute gap is not a clean chronological market context. Kronos sees a regular timestamp sequence in the input CSV, but the historical market sequence has missing periods.
- Impact: The model is asked to infer a continuous market state from discontinuous data. Momentum, volatility, and microstructure context become distorted.
- Recommended fix: Make missing-candle count and largest gap hard blockers for live prediction above strict thresholds. Store the exact gap list in prediction metadata and dashboard.

### RC2: Prediction scheduling is gated by WebSocket freshness, not strict closed-candle alignment

- Severity: High
- Area: Data / Timing
- Evidence: `src/main_prediction_scheduler.py::_websocket_prediction_gate` lines 163-278; `src/main_forecast_latest.py::_closed_candles_only` lines 222-230
- Explanation: The scheduler checks for a fresh/advanced WebSocket candle timestamp, then `main_forecast_latest.py` fetches REST history and drops unclosed rows. The gate does not prove the exact latest prediction input candle is closed, continuous, and identical to the gated WebSocket candle.
- Impact: Predictions may run with mismatched timing, one-row-short contexts, or REST/WebSocket inconsistency. Older logs showed `forecast_latest.prices.unclosed_dropped` and 511 input rows after a 512-row request.
- Recommended fix: Gate on the final model input candle after REST fetch, not only on WebSocket status. Require `last_input_timestamp <= now - resolution`, exact 5-minute cadence, and no duplicate/missing terminal candles.

### RC3: WebSocket OHLC storage can degrade volume/amount integrity

- Severity: High
- Area: Data / DB
- Evidence: `src/kronos_mapper.py::ws_ohlc_to_kronos_row` lines 114-148; `src/prediction_store.py::upsert_ohlcv_df` lines 213-214 and 249-263
- Explanation: WebSocket OHLC mapping sets `volume=None` and `amount=None`; `upsert_ohlcv_df` coerces missing numeric fields and gives `websocket_ohlc` higher source priority than `latest_fetch` and `historical`.
- Runtime evidence: Database query showed 769 ETHUSD/MINUTE_5 rows with source `websocket_ohlc`; all 769 had `amount=0`.
- Impact: Stored candles can lose richer REST context, especially amount and possibly volume semantics, weakening model inputs, higher-timeframe validation, volume z-score, and dashboard candle context.
- Recommended fix: Do not overwrite non-null REST volume/amount with WebSocket nulls. Preserve previous non-null fields on upsert or store WebSocket candles separately until closed/complete.

### RC4: `amount` is unavailable, so Kronos does not receive full OHLCVA context

- Severity: High
- Area: Model Input
- Evidence: `src/kronos_mapper.py::capital_prices_to_kronos_df` lines 89-111; `src/kronos_mapper.py::ws_ohlc_to_kronos_row` lines 143-147; `src/main_run_kronos_predict.py::_select_feature_columns` lines 239-256
- Evidence observed: Latest input CSV header is `timestamps,open,high,low,close,volume,amount`, but every `amount` value is `0.0`; metadata reports `amount_available=false`.
- Explanation: Kronos examples use OHLCVA style inputs. This implementation cannot provide meaningful traded amount and may drop it in auto feature mode.
- Impact: The model has less market participation/liquidity context than intended, especially for crypto-like instruments where volume/amount can help regime detection.
- Recommended fix: Derive meaningful amount as `close * volume` if volume units are valid, or explicitly run/evaluate an OHLCV-only configuration against baselines.

### RC5: Forecast validation exists but does not yet prove tradability

- Severity: High
- Area: Forecast
- Evidence: `src/main_run_kronos_predict.py::_validate_forecast` lines 266-335; `src/main_forecast_latest.py::main` lines 365-381; `src/forecast_quality_validator.py::validate_forecast_quality` lines 90-204
- Explanation: The immediate validation checks structure, OHLC invariants, timestamp cadence, and movement size. Full quality validation requires future actuals and often returns `NEEDS_MORE_SAMPLES`.
- Runtime evidence: Recent ETHUSD/MINUTE_5 database outcomes: 7,452 `LOSS`, 3,649 `WIN`, 227 `PENDING`. That is about 32.9% directional win rate excluding pending rows.
- Impact: Structurally valid forecasts are still being converted into signals even when live forecast quality is not statistically established.
- Recommended fix: Promote forecasts to tradable only after rolling out-of-sample metrics beat baselines by horizon and after cost.

### RC6: Signal confidence is heuristic, not calibrated probability

- Severity: High
- Area: Signal Logic
- Evidence: `src/prediction_store.py::_signal_from_forecast` lines 397-505; `src/forecast_normalizer.py::_quality_score` lines 86-107
- Explanation: Confidence is derived from expected move, path agreement, volatility, and thresholds. It is not calibrated from historical forecast reliability or model uncertainty. `NEEDS_MORE_SAMPLES` can map to a moderate quality score.
- Impact: The system can treat weak edge as actionable confidence, especially when predicted movement barely clears cost thresholds.
- Recommended fix: Calibrate confidence from rolling live outcomes by symbol, horizon, volatility regime, session, and signal type.

### RC7: Signal horizon and validation horizon are not cleanly separated

- Severity: High
- Area: Signal Logic / Validation
- Evidence: `src/forecast_normalizer.py::normalize_forecast` lines 110-202; `src/prediction_store.py::_signal_from_forecast` lines 397-505; `src/forecast_scoring.py::score_forecast_against_actuals` lines 79-209
- Explanation: Signal direction is mostly based on terminal forecast close vs last input close over 12 candles. Forecast outcome scoring evaluates per-horizon candle directions and trade scoring uses TP/SL path.
- Impact: A 60-minute terminal forecast can be directionally right while intermediate path loses, or per-horizon validation can look poor while terminal outcome is different. This weakens both signal interpretation and dashboard statistics.
- Recommended fix: Define one primary trading horizon and validate signal outcomes against that exact horizon, plus separate diagnostic per-horizon forecast metrics.

### RC8: Execution policy does not hard-block on validation status

- Severity: Critical
- Area: Execution / Signal Logic
- Evidence: `src/trade_execution.py::ExecutionCandidate.is_actionable` lines 132-137; `src/trade_execution.py::_candidate_from_row` lines 923-963; `src/trade_execution.py::TradeExecutionPolicy.evaluate` lines 987-1050
- Explanation: Execution actionability is based primarily on raw `signals.signal` and execution settings. Validation status is included in metadata, but `TradeExecutionPolicy.evaluate` explicitly records that validation did not block demo execution.
- Runtime evidence: Database join found closed executions linked to validation statuses `HOLD`, `WATCH`, `BLOCKED`, and `VALIDATION_UNAVAILABLE`. Recent examples include `ETHUSD_MINUTE_5_20260509T134507Z` executed/closed SELL while validation was `BLOCKED` with score `0.0000`.
- Impact: The strongest validation layer can be bypassed, so low-quality signals can become real trades.
- Recommended fix: Require validation status in an allowlist such as `STRONG_LONG`, `LONG`, `STRONG_SHORT`, `SHORT`, with minimum validation score, fresh spread, no hard blockers, and matching raw direction.

### RC9: Executed trade records do not persist enough realized outcome detail

- Severity: High
- Area: DB / Execution
- Evidence: `migrations/014_trade_execution.sql` lines 20-49; `src/trade_execution.py::enrich_trade_outcomes` lines 1487-1512
- Explanation: `executed_trades` stores open/close timestamps and broker references, but not a durable realized P/L, exit price, fee, spread, slippage, or final trade outcome field. Outcomes are enriched dynamically from activity.
- Impact: Executed win rate is difficult to audit historically and can change depending on broker activity availability/window.
- Recommended fix: Persist final realized P/L, close price, close reason, fees, spread/slippage estimates, and immutable outcome at close.

### RC10: Dashboard prediction win rate is not executed-trade win rate

- Severity: High
- Area: Dashboard
- Evidence: `src/prediction_store.py::prediction_summary` lines 1635-1680; `src/dashboard_db.py::latest_validation_metrics` lines 334-416; `src/dashboard_db.py::postgres_dashboard_snapshot` lines 498-895
- Explanation: Summary metrics count forecast `prediction_outcomes`, not broker-executed trades. They are directional candle outcomes, not profitability metrics.
- Impact: Dashboard users can confuse forecast accuracy with executed trade win rate or expectancy.
- Recommended fix: Split dashboard metrics into forecast quality, signal quality, and executed trade performance. Show executed win rate only from closed executed trades with persisted P/L.

### RC11: Dashboard manual prediction accepts larger lookback but runs with `--max 512`

- Severity: Medium
- Area: Model Input / Dashboard API
- Evidence: `src/dashboard_server.py::_predict` lines 958-1056, especially the hard-coded `--max 512`
- Explanation: The request parser accepts lookbacks up to 2048, but the subprocess fetch is capped at 512 rows.
- Impact: User-requested longer context is silently not honored. This can produce misleading experiments.
- Recommended fix: Set `--max` to at least requested lookback, subject to model `max_context` and explicit UI constraints.

### RC12: Partial actual fetch is allowed through dashboard validation flow

- Severity: Medium
- Area: Validation
- Evidence: `src/dashboard_server.py::_fetch_actual` lines 1058-1114; `src/main_fetch_actual.py` lines 148-155
- Explanation: Dashboard actual fetching always passes `--allow-partial`.
- Impact: Quality validation can run on incomplete future windows, leading to `NEEDS_MORE_SAMPLES`, partial outcomes, or premature interpretation.
- Recommended fix: Separate "partial progress" from "final validation"; do not update final quality/trade metrics until the full horizon is available.

## 4. Suspected Root Causes Needing Runtime Verification

### S1: WebSocket OHLC messages may be partial/unclosed candle updates

- Why suspected: `src/capital_ws_ohlc_client.py::_handle_message` stores WebSocket OHLC rows as they arrive, and no closed-candle flag is required.
- Evidence needed: Raw `raw_market_events` payload samples for repeated timestamps, any close/completion flag, and update frequency within a 5-minute bucket.
- Safe verification: Query repeated raw OHLC timestamps and compare first vs final update for the same bucket before using WebSocket OHLC as a complete candle.

### S2: Source mixing may produce inconsistent candle windows

- Why suspected: `src/prediction_store.py::load_recent_ohlcv` and `src/candle_context.py::load_recent_candles` do not filter by source, while `SOURCE_PRIORITY` can replace rows.
- Evidence needed: Per-input-window source counts, cadence gaps, and OHLC differences by source for the same timestamp.
- Safe verification: Store source_counts in every model input metadata file and fail prediction if mixed-source windows violate quality rules.

### S3: Forecast timestamps may need stricter equality checks

- Why suspected: `src/main_run_kronos_predict.py::run_prediction` builds `y_timestamp`, but then uses `pred_df.reset_index()` and only structurally validates cadence.
- Evidence needed: Compare persisted `forecast_candles.timestamp_utc` to the exact generated `y_timestamp` for every run.
- Safe verification: Add an audit query/report that asserts `forecast_timestamp[i] == last_input_timestamp + i * resolution`.

### S4: Broker spread/slippage may exceed assumed thresholds during noisy periods

- Why suspected: Signal generation uses configured cost thresholds, while execution fills use live broker prices and dashboard outcomes are not fee/slippage-persisted.
- Evidence needed: Entry-time bid/ask spread, expected move, fill price, close price, fees, and slippage per executed trade.
- Safe verification: Persist entry spread and compare expected net edge to realized net P/L.

### S5: Regime filters may be too soft

- Why suspected: Low-volume hard blocking defaults to false in `src/signal_config.py`, and many validation-blocked/watch signals still appear in execution records.
- Evidence needed: Performance by volatility percentile, trend/range classification, volume z-score, hour/session, and spread regime.
- Safe verification: Run stratified post-trade analysis without changing execution behavior first.

## 5. Model Input Audit

Current live prediction input path:

- `src/main_forecast_latest.py::main` fetches Capital.com historical prices.
- `src/kronos_mapper.py::capital_prices_to_kronos_df` maps REST rows to `timestamps`, `open`, `high`, `low`, `close`, `volume`, `amount`.
- `src/main_forecast_latest.py::_closed_candles_only` removes unclosed candles.
- `src/main_run_kronos_predict.py::run_prediction` loads the CSV, sorts/deduplicates, selects features, builds future timestamps, and calls Kronos.

Latest observed input:

- File: `output/kronos_input_ETHUSD_MINUTE_5_20260509T141504Z.csv`
- Rows: 512 data rows
- Header: `timestamps,open,high,low,close,volume,amount`
- First timestamp: `2026-05-07 17:25:00+00:00`
- Last timestamp: `2026-05-09 14:10:00+00:00`
- Last close: `2313.305`
- Forecast horizon: 12 candles / 60 minutes
- Price side: `mid`
- Amount: all `0.0`
- Metadata quality: grade `B`, 26 missing candles, largest gap 125 minutes

Validity assessment:

- Timestamps are sorted and duplicate-free for the latest artifact.
- OHLC invariants pass for the latest artifact.
- The lookback row count is adequate for the configured 512 context, but not adequate for any dashboard request above 512.
- Volume exists in latest REST input, but amount is unavailable.
- Spread is not passed into the model input.
- No engineered indicators are passed into Kronos.
- Higher-timeframe context is used in signal validation, not in the Kronos forecast input.
- The prediction horizon is 60 minutes, while signal and validation metrics mix terminal, per-horizon, and TP/SL interpretations.

## 6. Forecast Quality Validation Gaps

Existing validation covers structural forecast validity, direction counts, MAE/RMSE/MAPE, and some trade outcome scoring. The missing or underused gaps are:

- Baseline gating: the model is not required to beat last-close, random, moving average, momentum, and mean-reversion baselines before signals become executable.
- Regime metrics: accuracy is not consistently broken down by volatility percentile, trend/range state, volume z-score, spread regime, session, or hour.
- Cost-aware forecast metrics: directional accuracy is not enough; movement must beat spread, fees, and slippage.
- Calibration: confidence is not validated as probability. A 70 confidence signal should win around 70% under comparable conditions if calibrated.
- Terminal-vs-path separation: terminal 12-candle direction, per-candle direction, and TP/SL path outcomes need separate metrics.
- Sample sufficiency: `NEEDS_MORE_SAMPLES` is common and should not be treated as tradable confidence.
- Symbol/resolution/model filtering: aggregate metrics need strict filters by symbol, resolution, model version, feature set, and date range.
- Persistence of forecast inputs/outputs: enough exists for files, but durable DB audit fields should include feature columns, input source mix, gap list, spread, and exact validation state at execution time.

## 7. Executed Win Rate Integrity Check

The current executed win rate is not fully trustworthy as a research metric.

Confirmed concerns:

- Forecast outcome totals are not executed-trade outcomes. For ETHUSD/MINUTE_5, database forecast outcomes showed 7,452 `LOSS`, 3,649 `WIN`, and 227 `PENDING`.
- Executed trade rows exist, but `executed_trades` does not persist final realized P/L, fees, spread, slippage, or immutable final outcome.
- Dashboard execution enrichment depends on broker activity lookups rather than a durable local outcome record.
- Execution records are linked to signals whose current validation status is often `BLOCKED`, `HOLD`, `WATCH`, or `VALIDATION_UNAVAILABLE`.
- Signal statuses include `GOOD_HOLD`, `MISSED_MOVE`, `WIN`, and `LOSS`, which are useful diagnostics but should not be mixed with broker trade win rate.

Conclusion: The dashboard can show useful diagnostics, but a credible executed win rate should be calculated only from closed broker executions with persisted entry price, exit price, costs, net P/L, and final outcome.

## 8. Baseline Comparison Plan

Use the exact same input timestamps, forecast horizons, actual candles, cost assumptions, and missing-candle filters for every baseline.

- Last close: forecast every future close as the last input close. This tests whether Kronos beats persistence.
- Random direction: random LONG/SHORT/HOLD with fixed seed and same no-trade threshold. This tests whether observed hit rate is above chance.
- Moving average: compare short MA vs long MA using only past candles. This tests whether a simple trend filter beats Kronos.
- Momentum: forecast direction from recent return over N closed candles. This tests whether the model beats naive continuation.
- Mean reversion: forecast opposite direction after stretched move or z-score excursion. This tests whether choppy-market behavior is better captured by simple reversion.

Evaluation rules:

- Use time-based splits only.
- Validate against the exact future candles the trade would have faced.
- Report per-horizon direction, terminal direction, TP/SL result, net return after costs, and maximum adverse excursion.
- Promote Kronos signals only when they beat baselines by statistically meaningful margins over a rolling sample.

## 9. Recommended Next Checks

Priority SQL checks:

```sql
-- Source and zero-volume/amount audit.
SELECT source,
       COUNT(*) AS rows,
       SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END) AS zero_volume,
       SUM(CASE WHEN amount = 0 THEN 1 ELSE 0 END) AS zero_amount,
       MIN(timestamp_utc) AS first_ts,
       MAX(timestamp_utc) AS last_ts
FROM ohlcv_candles
WHERE symbol = 'ETHUSD' AND resolution = 'MINUTE_5'
GROUP BY source
ORDER BY rows DESC;

-- Cadence gaps in the latest 700 stored candles.
WITH c AS (
  SELECT timestamp_utc,
         LAG(timestamp_utc) OVER (ORDER BY timestamp_utc) AS prev_ts
  FROM ohlcv_candles
  WHERE symbol = 'ETHUSD' AND resolution = 'MINUTE_5' AND price_side = 'mid'
  ORDER BY timestamp_utc DESC
  LIMIT 700
)
SELECT prev_ts, timestamp_utc, timestamp_utc - prev_ts AS gap
FROM c
WHERE prev_ts IS NOT NULL
  AND timestamp_utc - prev_ts <> interval '5 minutes'
ORDER BY timestamp_utc DESC;

-- Forecast outcome by horizon.
SELECT fc.horizon_index,
       COUNT(*) FILTER (WHERE po.status = 'WIN') AS wins,
       COUNT(*) FILTER (WHERE po.status = 'LOSS') AS losses,
       COUNT(*) FILTER (WHERE po.status = 'PENDING') AS pending,
       AVG(po.absolute_error) AS avg_abs_error,
       AVG(po.absolute_percentage_error) AS avg_ape
FROM prediction_outcomes po
JOIN forecast_candles fc ON fc.id = po.forecast_candle_id
JOIN prediction_runs pr ON pr.run_id = po.run_id
WHERE pr.symbol = 'ETHUSD' AND pr.resolution = 'MINUTE_5'
GROUP BY fc.horizon_index
ORDER BY fc.horizon_index;

-- Executions linked to weak or blocked validation.
SELECT e.signal_id,
       e.status AS execution_status,
       e.direction,
       s.signal,
       s.validation_status,
       s.validation_score,
       s.status AS signal_status,
       e.created_at
FROM executed_trades e
JOIN signals s ON s.signal_id = e.signal_id
WHERE s.validation_status IN ('BLOCKED', 'HOLD', 'WATCH', 'VALIDATION_UNAVAILABLE', 'WEAK_LONG', 'WEAK_SHORT')
ORDER BY e.created_at DESC
LIMIT 100;

-- Forecast metrics filtered by run metadata.
SELECT pr.symbol,
       pr.resolution,
       pr.model_name,
       pr.run_status,
       COUNT(*) FILTER (WHERE po.status = 'WIN') AS wins,
       COUNT(*) FILTER (WHERE po.status = 'LOSS') AS losses,
       COUNT(*) FILTER (WHERE po.status = 'PENDING') AS pending
FROM prediction_runs pr
JOIN prediction_outcomes po ON po.run_id = pr.run_id
GROUP BY pr.symbol, pr.resolution, pr.model_name, pr.run_status
ORDER BY pr.symbol, pr.resolution;
```

Priority log/artifact checks:

- Compare every `forecast_metadata_*.json` `missing_candle_count` and `largest_gap_minutes` to forecast quality.
- Compare every `kronos_forecast_validation_*.json` `max_abs_close_move_pct` to realized spread and signal status.
- Audit every executed trade's validation status at queue time, not just current signal state.
- Export the exact model input CSV for losing runs and compare against winning runs.

## 10. Important Improvements

- Input validation: hard-block predictions on large gaps, stale terminal candles, duplicate timestamps, missing rows, or source-mixed windows that fail policy.
- Multi-timeframe context: keep higher-timeframe validation, but also evaluate whether model input should include 15m/1h derived context or separate regime features outside Kronos.
- Spread/fee/slippage-aware thresholds: require expected movement to exceed realistic all-in cost plus a safety margin.
- Regime filtering: block or downsize trades in low-volume, high-spread, extreme-volatility, and choppy/no-trade regimes.
- Confidence calibration: replace heuristic confidence with rolling empirical calibration by symbol, horizon, and regime.
- No-trade zone: expand HOLD behavior when forecast movement is close to cost or historical forecast skill is poor.
- Stronger outcome validation: separate forecast direction, signal direction, TP/SL outcome, and broker realized P/L.
- Baseline benchmarking: make baseline comparison part of promotion and dashboard reporting.
- Better dashboard metrics: separate prediction accuracy, signal quality, executed trade win rate, average return, expectancy, and drawdown.
- Model input/output audit logging: persist feature columns, input source counts, gap list, latest close, spread, forecast dispersion, validation blockers, and execution decision reason.

## 11. Quick Wins

- Block execution when validation status is `BLOCKED`, `HOLD`, `WATCH`, or `VALIDATION_UNAVAILABLE`.
- Show a dashboard warning whenever `missing_candle_count > 0` or `largest_gap_minutes > 5`.
- Persist `entry_spread_pct`, `expected_move_pct`, `validation_status_at_execution`, and `validation_score_at_execution`.
- Change dashboard prediction summary labels so forecast win rate is not confused with executed trade win rate.
- Make dashboard `lookback` either truly control `--max` or cap the UI to 512 with explicit text.
- Prevent WebSocket null `amount`/`volume` from overwriting existing non-null REST candle fields.
- Require full future horizon before marking final forecast quality, while still allowing partial progress as separate status.

## 12. High-Risk Changes to Avoid

- Do not fine-tune the model before the live validation pipeline proves current input quality and baseline performance.
- Do not lower signal thresholds to increase trade count; that can increase fake activity while lowering expectancy.
- Do not evaluate on partial candles or partially available future windows as final outcomes.
- Do not use future candles in features, regime labels, thresholds, or indicator calculations.
- Do not optimize thresholds on the same period used for performance reporting.
- Do not report forecast directional accuracy as profitability.
- Do not count skipped/HOLD predictions as executed trade wins.
- Do not use dashboard/manual backtests that ignore spread, fees, slippage, and realistic fill timing.

## 13. Final Priority Roadmap

### Phase 1: Measurement and Validation

- Persist immutable execution outcome fields: exit price, net P/L, fees, spread/slippage estimate, close reason, final outcome.
- Split dashboard metrics into forecast, signal, and executed-trade sections.
- Add baseline comparisons to every validated run and require enough samples before drawing conclusions.
- Add regime/hour/session breakdowns.

### Phase 2: Data/Input Correctness

- Enforce closed-candle gating on the exact model input window.
- Hard-block large gaps and stale terminal candles.
- Prevent source-priority upserts from erasing useful REST volume/amount fields.
- Log feature columns, source counts, gap list, and terminal price for every prediction.

### Phase 3: Signal Filtering and Risk Logic

- Make validation status a hard execution gate.
- Require net edge over realistic spread, fees, and slippage.
- Add stricter no-trade zones for weak movement, missing spread, poor regime, and low confidence.
- Validate TP/SL sizing against recent ATR and broker minimum distances.

### Phase 4: Model Improvements

- Only after measurement is trustworthy, compare OHLCV vs OHLCVA-derived amount vs regime-enhanced inputs.
- Test horizon-specific forecasts and choose the horizon with measurable skill.
- Consider multi-timeframe features or separate regime classifiers before fine-tuning.
- Fine-tune only with time-based splits and leakage checks.

### Phase 5: Dashboard/Statistics Trust

- Rename forecast win rate to directional forecast hit rate.
- Add executed trade win rate from closed trades only.
- Add expectancy, average win/loss, drawdown, spread impact, and slippage impact.
- Show validation blockers and execution decision reasons for every signal.
- Make stale/partial/latest prediction states visually explicit.
