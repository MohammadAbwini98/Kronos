# Capital.com Kronos Data Bridge

Safe local Python bridge for fetching Capital.com ETH/USD market data and preparing Kronos-compatible pandas/CSV input.

This project is data only. It does not place trades, open positions, close positions, manage working orders, or call trading endpoints.

## Setup

```powershell
cd C:\AI\capital_kronos_data_bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
CAPITAL_ENV=demo
CAPITAL_API_KEY=your_api_key
CAPITAL_IDENTIFIER=your_login_identifier
CAPITAL_PASSWORD=your_api_password
CAPITAL_DISPLAY_TIMEZONE=Asia/Amman
```

Never commit `.env`. Do not hardcode credentials in code. Capital.com API keys may have trading privileges, and this bridge intentionally avoids trading endpoints.

## Operational Environment Variables

Use `.env.example` as the full reference. The most important runtime controls are:

```text
ENABLE_AUTO_FINETUNE=true
ENABLE_MAINTENANCE_WORKER=true
LIVE_PRICE_RESOLUTION=MINUTE
WORKER_RESTART_MAX_ATTEMPTS=20
WORKER_MONITOR_INTERVAL_SECONDS=5

KRONOS_FINETUNE_COMMAND=
KRONOS_AUTO_MODEL_DIR=C:\AI\Models\Kronos\Kronos-auto-finetuned
AUTO_FINETUNE_DATASET_LIMIT=50000
AUTO_FINETUNE_MIN_ROWS=2000
AUTO_FINETUNE_MIN_NEW_ROWS=1000
AUTO_FINETUNE_INTERVAL_MINUTES=15
AUTO_FINETUNE_PROMOTION_MIN_DIRECTION_ACCURACY=55.0
AUTO_FINETUNE_PROMOTION_MIN_MATCHED_CANDLES=20

MAINTENANCE_POLL_SECONDS=60
OUTCOME_ARCHIVE_RETENTION_DAYS=30
OUTCOME_ARCHIVE_INTERVAL_MINUTES=60
NIGHTLY_BACKUP_HOUR_UTC=2
BACKUP_RETENTION_DAYS=14

CAPITAL_LOG_DIR=output\logs
CAPITAL_LOG_MAX_BYTES=5242880
CAPITAL_LOG_BACKUP_COUNT=5
```

Auto-finetune command safety:

- `KRONOS_FINETUNE_COMMAND` can be empty to disable training runs safely.
- If configured, the command template must include both `{dataset}` and `{model_dir}` placeholders.
- Optional placeholders `{symbol}` and `{resolution}` are also available.

Example command template:

```text
KRONOS_FINETUNE_COMMAND=C:\AI\capital_kronos_data_bridge\.venv\Scripts\python.exe C:\AI\capital_kronos_data_bridge\src\main_bootstrap_auto_model.py --dataset {dataset} --model-dir {model_dir} --symbol {symbol} --resolution {resolution}
```

## Demo vs Live

- Demo REST base URL: `https://demo-api-capital.backend-capital.com/api/v1`
- Live REST base URL: `https://api-capital.backend-capital.com/api/v1`
- WebSocket URL: `wss://api-streaming-capital.backend-capital.com/connect`

Set `CAPITAL_ENV=demo` or pass `--env demo` for demo. Use live only when you intentionally want live account data.

## Historical Fetch

```powershell
python .\src\main_fetch_historical.py --market ETHUSD --resolution MINUTE_5 --max 512 --price-side mid --env demo
```

Optional date range:

```powershell
python .\src\main_fetch_historical.py --market ETH/USD --resolution MINUTE_5 --max 512 --from 2026-04-01T00:00:00 --to 2026-04-02T00:00:00 --price-side mid
```

Behavior:

- Authenticates with `POST /session`.
- Resolves ETHUSD, ETH/USD, Ethereum, ETH, or uses `--epic` / `CAPITAL_DEFAULT_EPIC`.
- Saves market details to `output/market_details_{epic}.json`.
- Fetches historical prices from `GET /prices/{epic}`.
- Fetches client sentiment.
- Saves raw prices and Kronos CSV.

## WebSocket OHLC Stream

```powershell
python .\src\main_stream_ohlc.py --market ETHUSD --resolution MINUTE_5 --price-side mid --env demo
```

The stream subscribes to `OHLCMarketData.subscribe`, keeps a rolling in-memory DataFrame, saves raw events incrementally to JSONL, and writes the latest 512 Kronos-ready rows to:

```text
output/kronos_stream_input_{epic}_{resolution}.csv
```

Press `Ctrl+C` to stop gracefully and send `OHLCMarketData.unsubscribe`.

## Client Sentiment

The historical script retrieves sentiment automatically. The REST client implements:

- `get_client_sentiment(epic_or_market_id)`
- `get_client_sentiment_batch(market_ids)`

Sentiment is saved as:

```text
output/client_sentiment_{epic}.json
```

Expected fields include `marketId`, `longPositionPercentage`, and `shortPositionPercentage`, depending on Capital.com's response shape.

## Prepare Existing Raw JSON

Convert a previously saved Capital.com raw prices file:

```powershell
python .\src\main_prepare_kronos_input.py --input .\output\capital_raw_prices_ETHUSD_MINUTE_5.json --price-side mid --output .\output\kronos_input.csv
```

## Kronos CSV Schema

The generated CSV contains:

```text
timestamps,open,high,low,close,volume,amount
```

`timestamps` are UTC datetimes. OHLC columns are floats. `lastTradedVolume` maps to `volume`. `amount` is set to `0.0` because Capital.com does not provide quote turnover in the historical price response.

Internal CSV timestamps remain UTC for Capital.com matching and Kronos stability. Human-facing metadata summaries, quality reports, HTML reviews, and CLI summaries display timestamps in `CAPITAL_DISPLAY_TIMEZONE`, which defaults to `Asia/Amman`.

## Bid/Ask Mapping

Capital.com historical candles include bid and ask prices:

- `bid`: uses `openPrice.bid`, `highPrice.bid`, `lowPrice.bid`, `closePrice.bid`
- `ask`: uses `openPrice.ask`, `highPrice.ask`, `lowPrice.ask`, `closePrice.ask`
- `mid`: averages bid and ask for each OHLC field

Example mid mapping:

```text
open = (openPrice.bid + openPrice.ask) / 2
```

## Kronos Integration

`src/kronos_mapper.py` provides:

- `capital_prices_to_kronos_df(raw_prices, price_side="mid")`
- `ws_ohlc_to_kronos_row(event_payload)`
- `validate_kronos_df(df)`
- `save_kronos_csv(df, path)`
- `prepare_for_kronos_predictor(df, lookback=512, pred_len=12)`

Run the local Kronos model on a generated CSV:

```powershell
C:\AI\Kronos\.venv\Scripts\python.exe .\src\main_run_kronos_predict.py --input .\output\kronos_input_ETHUSD_MINUTE_5.csv --output .\output\kronos_forecast_ETHUSD_MINUTE_5_auto.csv --resolution MINUTE_5 --lookback 512 --pred-len 12 --feature-set auto --validation-report .\output\kronos_forecast_ETHUSD_MINUTE_5_auto_validation.json
```

`--feature-set auto` keeps Capital.com's real volume but omits `amount` when it is unavailable/all zero. Kronos then derives amount internally as `volume * average(OHLC)`, matching the predictor's built-in handling for missing amount data.

For current/future forecasts, prefer the wrapper that fetches the latest Capital.com candles first:

```powershell
.\.venv\Scripts\python.exe .\src\main_forecast_latest.py --market ETHUSD --resolution MINUTE_5 --max 512 --lookback 512 --pred-len 12 --price-side mid --env demo --repair-ohlc
```

Use old or held-out forecast windows only for backtesting and forecast-quality validation after actual candles are available.

Fetch a longer three-month history:

```powershell
.\.venv\Scripts\python.exe .\src\main_fetch_historical_range.py --market ETHUSD --resolution MINUTE_5 --months 3 --price-side mid --env demo
```

Start the local dashboard. It opens automatically and includes a `Run Prediction` button:

```powershell
.\start_dashboard.ps1
```

Dashboard URL:

```text
http://127.0.0.1:8765
```

Dashboard features:

- Summary cards for latest close, forecast close, direction, horizon, and quality.
- Actual plus forecast close chart.
- Historical plus forecast candlestick chart.
- Prediction controls for market, resolution, forecast length, lookback, feature set, and OHLC repair.
- Tabs for overview, charts, candles, validation, baselines, risk, history, files, logs, and embedded report.
- Buttons to fetch actual candles, validate actuals, and generate baseline comparisons.
- Auto-refresh control, run history table, and local prediction database WIN/LOSS summary.

## Dashboard Supervisor Behavior

`start_dashboard.ps1` runs as a supervisor with startup preflight checks and managed worker restarts.

- Preflight validates Python, creates output and log directories, prints active runtime config, and warns if `POSTGRES_DSN` is missing.
- Startup runs migrations once before worker launch.
- Managed workers are `prediction_scheduler`, `validation_worker`, `websocket_stream`, optional `auto_finetune_worker`, and optional `maintenance_worker`.
- Worker restart policy is controlled by `WORKER_RESTART_MAX_ATTEMPTS` (default `20`).
- Supervisor loop cadence is controlled by `WORKER_MONITOR_INTERVAL_SECONDS` (default `5`).
- Set `ENABLE_MAINTENANCE_WORKER=false` to skip maintenance worker startup.
- Set `ENABLE_AUTO_FINETUNE=false` to keep auto-finetune disabled without changing code.

When `--output` is omitted, the runner saves timestamped artifacts:

```text
output/kronos_input_{epic}_{resolution}_{timestamp}.csv
output/kronos_forecast_{epic}_{resolution}_{timestamp}.csv
output/forecast_metadata_{epic}_{resolution}_{timestamp}.json
output/kronos_forecast_validation_{epic}_{resolution}_{timestamp}.json
```

## Forecast Quality Validation

The Kronos format validation checks that a forecast is structurally clean: sorted timestamps, valid cadence, finite numeric values, no duplicate timestamps, no null OHLC values, and no OHLC invariant violations. Passing those checks does not mean the forecast is useful for trading decisions.

The next step is quality validation against actual Capital.com candles after the forecast window has passed.

1. Fetch historical candles:

```powershell
.\.venv\Scripts\python.exe .\src\main_fetch_historical.py --market ETHUSD --resolution MINUTE_5 --max 512 --price-side mid --env demo
```

2. Generate a timestamped Kronos forecast and metadata:

```powershell
C:\AI\Kronos\.venv\Scripts\python.exe .\src\main_run_kronos_predict.py --input .\output\kronos_input_ETHUSD_MINUTE_5.csv --resolution MINUTE_5 --lookback 512 --pred-len 12 --epic ETHUSD --market-name "Ethereum/USD" --price-side mid --feature-set auto
```

3. After the forecast horizon has passed, fetch actual candles for the same forecast window:

```powershell
.\.venv\Scripts\python.exe .\src\main_fetch_actual_for_forecast.py --metadata .\output\forecast_metadata_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.json --price-side mid
```

4. Compare forecast vs actual:

```powershell
.\.venv\Scripts\python.exe .\src\main_validate_forecast_quality.py --forecast .\output\kronos_forecast_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv --actual .\output\actual_for_forecast_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv --metadata .\output\forecast_metadata_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.json --resolution MINUTE_5 --price-side mid --epic ETHUSD
```

5. Aggregate many quality reports:

```powershell
.\.venv\Scripts\python.exe .\src\main_cumulative_forecast_report.py --input-dir .\output --output .\output\cumulative_forecast_quality_report.json
```

6. Generate an HTML forecast review:

```powershell
.\.venv\Scripts\python.exe .\src\main_plot_forecast_review.py --forecast .\output\kronos_forecast_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv --actual .\output\actual_for_forecast_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv --metadata .\output\forecast_metadata_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.json --quality-report .\output\forecast_quality_report_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.json --output .\output\forecast_review_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.html
```

7. Generate simple baseline forecasts:

```powershell
.\.venv\Scripts\python.exe .\src\main_generate_baseline_forecasts.py --input .\output\kronos_input_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv --resolution MINUTE_5 --pred-len 12 --method naive --output .\output\baseline_naive_ETHUSD_MINUTE_5_YYYYMMDDTHHMMSSZ.csv
```

8. Compare experiment settings from the run index:

```powershell
.\.venv\Scripts\python.exe .\src\main_compare_experiments.py --index .\output\forecast_runs_index.csv --output .\output\experiment_comparison_report.json
```

Quality metrics:

- `MAE`: average absolute close-price error.
- `RMSE`: square-rooted mean squared close-price error, more sensitive to large misses.
- `MAPE`: average percentage close-price error.
- `direction_accuracy_pct`: how often forecast close direction matched actual close direction, using a flat threshold.
- `forecast_bias`: whether forecasts tend to over-predict, under-predict, or remain neutral.
- `quality_status`: `NEEDS_MORE_SAMPLES`, `PROMISING`, `WEAK`, or `NOT_TRADABLE`.
- `trading_usefulness`: analysis-only fields such as actionable rows after costs, false positive rate, UP/DOWN precision, average hypothetical signal return, and max adverse excursion.

Important: a technically valid forecast is not automatically a profitable signal. Spread, slippage, fees, market regime changes, latency, risk limits, and position sizing must be evaluated before any forecast can support BUY / SELL / HOLD scoring. This project only produces data, forecasts, and validation reports. It does not place trades.

## Prediction WIN/LOSS Database

Every Kronos prediction run saves to PostgreSQL. The database stores one `prediction_runs` row per forecast and one `forecast_candles` plus `prediction_outcomes` row per forecast candle. Records stay `PENDING` until actual Capital.com candles are available, then quality validation updates each candle to `WIN` or `LOSS`.

The status is directional and data-only:

- The first forecast candle is judged against the last input close.
- Later forecast candles are judged candle-by-candle against the corresponding actual close path for the same timestamp and resolution.
- `WIN` means the forecast candle direction matched the actual candle direction using the configured flat threshold.
- `LOSS` means the direction did not match.
- No BUY/SELL execution logic is created or called.

Create/use a local PostgreSQL database. The default DSN (matching the provided docker-compose credentials) is:

```text
postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos
```

Apply migrations:

```powershell
.\.venv\Scripts\python.exe .\src\main_db_migrate.py
```

Inspect the ledger:

```powershell
.\.venv\Scripts\python.exe .\src\main_prediction_db_status.py
```

Use `POSTGRES_DSN` to override the PostgreSQL connection string.

## PostgreSQL Signal Engine

The production-style signal workflow is data-only:

```text
Capital.com REST/WebSocket -> PostgreSQL OHLCV -> Kronos Scheduler -> Forecast Candles -> Signal -> Validation Worker -> Dashboard
```

Apply migrations:

```powershell
.\.venv\Scripts\python.exe .\src\main_db_migrate.py
```

Fetch and store historical candles:

```powershell
.\.venv\Scripts\python.exe .\src\main_fetch_historical.py --market ETHUSD --symbol ETHUSD --resolution MINUTE_5 --max 512 --price-side mid --env demo
```

Run one current/future prediction cycle and store the forecast plus signal:

```powershell
.\.venv\Scripts\python.exe .\src\main_prediction_scheduler.py --once --symbol ETHUSD --market ETHUSD --resolution MINUTE_5
```

Run continuously every 5 minutes:

```powershell
.\.venv\Scripts\python.exe .\src\main_prediction_scheduler.py --symbol ETHUSD --market ETHUSD --resolution MINUTE_5
```

Validate completed forecast windows:

```powershell
.\.venv\Scripts\python.exe .\src\main_validation_worker.py --once
```

Prepare collected candles for future Kronos fine-tuning experiments:

```powershell
.\.venv\Scripts\python.exe .\src\main_prepare_finetune_dataset.py --symbol ETHUSD --resolution MINUTE_5 --output .\output\kronos_finetune_dataset.csv
```

Signals are analytical labels only: `LONG`, `SHORT`, or `HOLD`. They are not orders and this project does not execute trades.

This loads local model files by default:

```text
KRONOS_REPO_DIR=C:\AI\Kronos
KRONOS_MODEL_DIR=C:\AI\Models\Kronos\Kronos-base
KRONOS_TOKENIZER_DIR=C:\AI\Models\Kronos\Kronos-Tokenizer-base
KRONOS_DEVICE=auto
```

## API Limits and Sessions

The code rate-limits REST calls, limits `POST /session` to at most one request per second, retries transient HTTP errors with backoff, and refreshes authentication once on session expiry. Capital.com sessions may expire after roughly 10 minutes without keepalive, and WebSocket subscriptions support up to 40 instruments.

## Troubleshooting

- Invalid credentials: verify `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER`, and `CAPITAL_PASSWORD`; make sure the password matches your Capital.com API password.
- Missing `CST` or `X-SECURITY-TOKEN`: the session response was not valid for authenticated calls; check credentials and account/API permissions.
- Invalid epic: run with `--market ETHUSD` and let the bridge resolve a valid epic, or confirm `--epic` in Capital.com.
- Invalid resolution: use `MINUTE`, `MINUTE_5`, `MINUTE_15`, `MINUTE_30`, `HOUR`, `HOUR_4`, `DAY`, or `WEEK`.
- WebSocket disconnection: restart the stream; the client sends ping keepalives and unsubscribes cleanly on shutdown.
- Session expiry: REST requests re-authenticate once and retry.
- Empty historical prices: widen `--from` / `--to`, increase `--max`, or check whether the instrument has data for that period.
- Market closed: market discovery prefers `TRADEABLE` but does not fail solely because a market is closed.
- Unsupported instrument: search with a broader term such as `Ethereum` or configure `CAPITAL_DEFAULT_EPIC`.

## Official References

- [Capital.com API guide](https://capital.com/en-int/trading-platforms/api-development-guide)
- [Capital.com Open API reference](https://open-api.capital.com/)
