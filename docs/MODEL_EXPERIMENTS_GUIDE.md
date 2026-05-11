# Model Experiments Guide

Phase 4 is measurement infrastructure for model/input experiments. It does not fine-tune Kronos, replace the model, or promote a new feature mode.

## Feature Modes

Compare runs on the same symbol, resolution, timestamp windows, lookback, and horizon:

- `OHLCV_ONLY`: open, high, low, close, volume.
- `OHLCVA_DERIVED_AMOUNT`: open, high, low, close, volume, plus `amount = close * volume`.
- `OHLCV_WITH_REGIME_CONTEXT`: Kronos input remains OHLCV; regime context is recorded for analysis.
- `MULTI_TIMEFRAME_VALIDATION_ONLY`: model input stays compatible; multi-timeframe context is validation/report-only.

Do not treat derived amount as better until it beats OHLCV on held-out windows and baselines after costs. Derived amount must never be silently all-zero.

## Horizon Comparison

Analyze skill separately for 1, 3, 6, and 12 candle horizons. Report directional hit rate, MAE, RMSE, safe MAPE, net-edge hit rate after costs, sample count, and baseline delta.

Do not collapse horizon results into one generic win rate. A model can be useful at 3 candles and weak at 12 candles, or vice versa.

## Baseline Improvement

Compare every candidate mode against the same timestamp windows and actual candles:

- last close persistence
- random direction with fixed seed
- moving average direction
- naive momentum
- naive mean reversion

Use `model_metric - baseline_metric` for deltas. Positive is model outperformance.

## Leakage Avoidance

Regime labels and features must use only candles available at prediction time. Rolling volatility, trend/range, volume, spread, hour, and session labels must be computed from past/current closed candles only.

Never optimize thresholds or select a feature mode on the same period used for reporting.

## Confidence Calibration

Current signal confidence is heuristic. Phase 4 only prepares empirical buckets by symbol, resolution, horizon, signal type, validation status, volatility regime, and confidence bucket.

Buckets with insufficient samples expose `observed_win_rate = null` and `enough_samples = false`. They must not be presented as calibrated probabilities.

## Fine-Tuning Gate

Fine-tuning remains blocked until there are enough trusted samples showing:

- input windows pass strict continuity and closure checks
- validation metrics are final, not partial
- execution gates are trusted
- candidate feature modes beat baselines on held-out periods after costs
- horizon-specific skill is stable
- calibration buckets have enough samples
- leakage checks pass on time-based splits
