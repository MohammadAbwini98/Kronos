# External Higher-Timeframe Signal Validation Architecture

## Safety Boundary

This project remains data-only.

- No trade execution is implemented.
- No order placement endpoint is called.
- No automated broker position management is added.
- Signals are analytical outputs only.

## Architecture

```text
Capital.com REST/WebSocket Data
        |
        v
PostgreSQL ohlcv_candles
        |
        v
5m Kronos Forecast
        |
        v
Forecast Normalizer
        |
        v
Hard Blocker Engine
        |
        v
Higher-Timeframe Context Validator
        |
        v
Signal Scoring Engine
        |
        v
Analytical Final Signal
        |
        v
PostgreSQL Persistence
        |
        v
Dashboard/API
        |
        v
Outcome Validation and Calibration Reports
```

## Why Kronos Stays 5m-Only

Kronos forecasting stays anchored on `MINUTE_5`.

Higher timeframes (`MINUTE_15`, `MINUTE_30`, `HOUR`, `HOUR_4`) are used only after forecast generation for external validation and confidence scoring. This prevents mixed-cadence contamination of the base forecast sequence and keeps model behavior stable.

## Data Flow

1. Forecast run is persisted (`prediction_runs`, `forecast_candles`, `signals`).
2. Forecast is normalized into direction, edge, cost-adjusted metrics, and path-consistency features.
3. Hard blockers run first.
4. Higher timeframe candles are validated from DB and fetched when missing.
5. Per-timeframe trend and indicator snapshots are computed.
6. Component scoring produces a 0-100 score and confidence bucket.
7. Validation payloads are saved in:
   - `signal_validation_runs`
   - `signal_timeframe_validations`
8. The related row in `signals` is updated with validation summary fields.

## Hard Blockers

Hard blockers override all downstream scoring and force `BLOCKED` or `VALIDATION_UNAVAILABLE` outcomes.

Main blocker reasons:

- `KRONOS_FORECAST_INVALID`
- `FORECAST_DIRECTION_FLAT`
- `FORECAST_EDGE_BELOW_COST`
- `MISSING_5M_INPUT`
- `INVALID_5M_INPUT`
- `MISSING_HIGHER_TIMEFRAME_CONTEXT`
- `PROVISIONAL_HIGHER_TIMEFRAME_CONTEXT`
- `WIDE_SPREAD_OR_COST_UNKNOWN`
- `VERY_LOW_VOLUME`
- `EXTREME_VOLATILITY`
- `CADENCE_INVALID`
- `DATABASE_UNAVAILABLE`
- `VALIDATION_DISABLED`
- `VALIDATION_UNAVAILABLE`

## Score Formula

Total score is 100 with these component caps:

- Kronos forecast quality: 35
- Higher timeframe alignment: 25
- Momentum confirmation: 10
- Volume confirmation: 10
- Cost/spread/liquidity quality: 10
- Volatility regime: 5
- Support/resistance location: 5

Confidence levels:

- `VERY_HIGH` for score >= 85
- `HIGH` for score >= 70
- `MEDIUM` for score >= 60
- `LOW` for score >= 50
- `NONE` below 50

## Database Tables

Added table: `signal_validation_runs`

- One row per run id.
- Stores candidate/final signal, score, confidence, blocker status, and JSON component details.

Added table: `signal_timeframe_validations`

- One row per `(run_id, timeframe)`.
- Stores trend class, confirmation flag, per-timeframe component scores, and indicator snapshots.

Extended table: `signals`

- `validation_score`
- `validation_status`
- `validation_summary` (JSONB)

## API and Dashboard Fields

`/api/status` now includes:

- `signal_validation`
- `timeframe_validations`

Dashboard now surfaces:

- Candidate and final signal
- Confidence and total score
- Blocked state and block reason
- Net edge and estimated cost
- Component score breakdown
- Higher-timeframe validation table with indicator values
- Decision reason codes/details

## CLI Commands

Run validation for a specific run:

```powershell
.\.venv\Scripts\python.exe .\src\main_validate_signal_context.py --run-id RUN_ID
```

Run validation for latest symbol/resolution run:

```powershell
.\.venv\Scripts\python.exe .\src\main_validate_signal_context.py --latest --symbol ETHUSD --resolution MINUTE_5
```

Generate calibration report:

```powershell
.\.venv\Scripts\python.exe .\src\main_signal_validation_report.py --output .\output\signal_validation_report.json
```

## Configuration

Primary variables:

- `SIGNAL_VALIDATION_ENABLED`
- `SIGNAL_VALIDATION_STRICT`
- `SIGNAL_VALIDATION_TIMEFRAMES`
- `SIGNAL_REQUIRE_HOUR_CONFIRMATION`
- `SIGNAL_BLOCK_ON_EXTREME_VOLATILITY`
- `SIGNAL_BLOCK_ON_WIDE_SPREAD`
- `SIGNAL_MAX_SPREAD_PCT`
- `SIGNAL_MIN_NET_EDGE_PCT`
- `SIGNAL_SCORE_STRONG_THRESHOLD`
- `SIGNAL_SCORE_ACTIONABLE_THRESHOLD`
- `SIGNAL_SCORE_WEAK_THRESHOLD`
- `SIGNAL_SCORE_WATCH_THRESHOLD`

## Calibration Workflow

1. Accumulate validated runs in production-like conditions.
2. Generate report from `signal_validation_runs` and outcome tables.
3. Review score-bucket win rates and false positive rates.
4. Propose threshold changes manually.
5. Do not auto-apply threshold changes without operator approval.

## Rollback Notes

Rollback is migration-based.

- Disable feature quickly: set `SIGNAL_VALIDATION_ENABLED=false`.
- Keep forecasting path intact while suppressing validation scoring.
- If needed, roll back migration changes according to the project migration rollback plan and operational SOP.
