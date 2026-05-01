# Post-Implementation Suggestions

These suggestions are based on the dashboard, websocket, filtering, validation, and auto-finetune updates now implemented.

## 1. Keep Live Price Truly Live
- Set `LIVE_PRICE_RESOLUTION=MINUTE` and keep the websocket stream process always on.
- Add a lightweight health check alert if no `websocket_ohlc` candle update is written for more than 90 seconds.
- Show a visual warning in dashboard UI when live quote source falls back from `websocket_ohlc` to `latest_fetch`.

## 2. Improve Signal Status Trust
- Keep the new effective signal status logic (WIN/LOSS once validated outcomes exist), but add a small `validated/total` progress pill near each signal.
- Add a periodic DB cleanup task to archive very old fully validated outcomes into history tables to keep dashboard queries fast.

## 3. Make Filters Fast Under Load
- Add DB indexes for most used filter combinations in the signals table:
  - `(symbol, resolution, timestamp_utc DESC)`
  - `(symbol, signal, timestamp_utc DESC)`
  - `(symbol, status, timestamp_utc DESC)`
- Keep using date-only filtering in display timezone, but document timezone behavior in the UI help tooltip.

## 4. Validation Metrics Quality
- Add a minimum sample hint next to metrics: for example, show `direction accuracy (n=matched_candles-1)`.
- Distinguish clearly between source types:
  - `quality_report` (file-based full metrics)
  - `prediction_outcomes` (DB fallback metrics)
- Trigger an automatic background `validate-actual` pass every few minutes for runs still `PENDING` or `PARTIAL`.

## 5. Auto-Finetune Safety Controls
- Define `KRONOS_FINETUNE_COMMAND` explicitly in environment and include `"{dataset}"` and `"{model_dir}"` placeholders.
- Keep `AUTO_FINETUNE_MIN_NEW_ROWS` high enough to prevent retraining too often (for example 500-2000 depending on noise).
- Add model promotion criteria before using a newly fine-tuned model in production (e.g., better `direction_accuracy_pct` than previous model over last N runs).

## 6. Operational Monitoring
- Add one status block in the UI for worker state:
  - scheduler
  - validation worker
  - websocket stream
  - auto-finetune worker
- Write worker heartbeat details into `service_heartbeats` with timestamps and last error summaries.
- Keep one rotating log file per worker for easy diagnosis.

## 7. UX Polishing
- Keep auto close-candle prediction silent (already implemented), but show subtle timestamp text such as `Last auto prediction: HH:MM:SS`.
- Add a small `Copied` button for signal ID and run ID in table rows for easier debugging.
- Add a one-click `Reset Filters` keyboard shortcut (`Esc`) in the signals tab.

## 8. Reliability and Recovery
- Add restart policy around worker processes (PowerShell loop or process supervisor) so websocket/validation workers auto-recover from transient failures.
- On startup, verify required env vars and print a single clear preflight report before launching workers.
- Add a nightly job to back up prediction metadata and key CSV artifacts.
