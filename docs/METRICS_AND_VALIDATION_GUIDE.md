# Metrics and Validation Guide

## Phase 1 Scope

Phase 1 improves measurement trust only. It does not change Kronos forecasting behavior, signal thresholds, execution gating, trading behavior, or model weights.

## Forecast Hit Rate vs Executed Trade Win Rate

Forecast quality measures whether forecast candles matched later actual candles. Its directional forecast hit rate comes from `prediction_outcomes` and `forecast_horizon_metrics`.

Executed trade win rate measures only closed broker executions with finalized local outcome fields in `executed_trades`: `final_outcome`, `net_pnl`, `exit_price`, costs, and `outcome_finalized_at`.

These are intentionally separate. A forecast can be directionally correct without producing a profitable broker trade after spread, fees, slippage, entry timing, and TP/SL path. A skipped, held, blocked, or unexecuted signal is never an executed win.

## Signal Quality vs Profitability

Signal quality is sourced from `signals` and validation fields:

- signal status distribution
- validation status distribution
- validation score distribution
- raw signal versus validation status mismatch count

Signal quality explains whether the signal pipeline agreed with or blocked model output. It does not prove profitability. Profitability comes only from finalized executed trades.

## Partial vs Final Validation

Partial future windows are stored as progress, not final outcomes.

- `PARTIAL_PROGRESS`: at least one actual candle exists, but the full forecast horizon is not complete.
- `NEEDS_MORE_SAMPLES`: no complete actual window is available yet.
- `FINAL`: every forecast horizon has the required actual candle.

Final WIN/LOSS forecast quality metrics are updated only when the complete forecast horizon is available. The dashboard must not treat partial validation as final performance.

## Terminal vs Path Outcome

Phase 1 separates these outcome types:

- Per-horizon candle direction: each forecast candle direction versus the matching actual candle direction.
- Terminal horizon direction: final forecast close versus last input close, compared with final actual close versus last input close.
- TP/SL path outcome: whether the actual path touched take-profit or stop-loss first for the signal.
- Executed broker outcome: realized closed-trade result from broker execution records and persisted P/L fields.

These can disagree. They should not be collapsed into one generic win rate.

## Baseline Comparison

Baseline comparisons use the same prediction timestamps, horizons, actual candles, and filters as the model:

- last close persistence
- random direction with a fixed seed
- moving average direction
- naive momentum
- naive mean reversion

Baselines are generated from historical candles available at prediction time only. They are stored in `baseline_comparison_metrics` with model metric, baseline metric, delta, sample count, and `enough_samples`.

## Executed Trade Outcome Persistence

Closed executions can persist:

- `entry_price`, `exit_price`
- `gross_pnl`, `net_pnl`
- `fee_amount`, `spread_cost`, `slippage_estimate`
- `close_reason`, `final_outcome`, `outcome_finalized_at`
- validation and expected-move snapshots captured at execution time

Existing records remain compatible because these fields are additive and nullable.

## Why This Does Not Improve Win Rate Yet

This phase makes the measurement system harder to misread. It does not tune the model, loosen thresholds, hard-block weak validation states, or alter trading rules. Those changes belong to later phases after the system can prove which metric is being improved.
