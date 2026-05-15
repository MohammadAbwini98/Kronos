# Codex Session Summary — Kronos Capital.com Demo Trade Execution

## Project Context
This project uses Kronos predictions to generate trading signals and execute them on a Capital.com demo account. The system includes:

- Kronos prediction generation
- Signal validation
- Trade execution queue
- Capital.com demo broker execution
- Dashboard UI for predictions/signals/trades

## Execution Worker Lifecycle
The execution worker is a queue processor. It does not decide whether Kronos should generate a trade signal; it processes already-created signals.

Lifecycle:

1. Kronos generates a prediction.
2. Prediction data is saved into:
   - `prediction_runs`
   - `forecast_candles`
   - `prediction_outcomes`
   - `signals`
3. Signal validation writes:
   - `validation_status`
   - `validation_score`
   - `validation_summary`
4. If `AUTO_EXECUTE_SIGNALS=true`, the signal is enqueued for execution.
5. Trade execution worker wakes up or drains immediately.
6. Worker claims queued items.
7. Worker validates broker/risk/safety rules.
8. Worker submits order to Capital.com demo using:
   - `POST /positions`
9. Worker confirms order using:
   - `GET /confirms/{dealReference}`
10. If accepted and `dealId` is returned, local trade status becomes `OPEN`.

Important files mentioned:

- `src/main_run_kronos_predict.py`
- `src/main_trade_execution_worker.py`
- `src/trade_execution.py`
- `src/config.py`
- `src/dashboard_server.py`
- `src/dashboard_ui.py`

## Original Problem
Signals were not becoming trades because local validation blocked execution before the broker received any order.

Example:

- Signal: `SHORT`
- `signals.status`: `PENDING`
- `validation_status`: `HOLD`
- `validation_score`: `49.0467`

Originally, `HOLD` was treated as non-executable, so Capital.com never received the trade.

## User Requirements Added
The user requested:

1. Signals must be turned into trades regardless of validation decision such as `HOLD`, `BLOCKED`, etc.
2. Dashboard must include a table for executed signals showing:
   - Current active executed trades
   - Historical trades
   - Pending trades
   - Queue entries
3. Trade must execute instantly without waiting for the worker tick.
4. Price movement during execution must allow max tolerance of `+-0.1`.

## Implemented Changes
Codex implemented the following:

### Trade Execution Behavior
- Validation labels like `HOLD`, `BLOCKED`, `WATCH`, etc. no longer block demo execution by themselves.
- Low confidence no longer blocks demo execution.
- `HOLD` signals with directional `UP` / `DOWN` are mapped to `BUY` / `SELL`.
- Execution now uses the fresh Capital.com market quote as the execution entry.
- If stored TP/SL is invalid, flat, or unsuitable, TP/SL is derived or reanchored from the current market price.
- Immediate execution was enabled so queued/manual signals are drained right away.
- `TRADE_PRICE_TOLERANCE=0.1` was added.
- The `+-0.1` tolerance was changed from a pre-submit blocker into a post-confirmation warning/check against fresh quote behavior.
- Existing hard gates still remain:
  - Demo account only
  - Duplicate execution prevention
  - Stale signal expiry
  - Market must be tradeable
  - Max open trades
  - Daily trade limit
  - Daily loss limit
  - Broker-side rejection

### Dashboard Changes
Initially, Codex added a generic `Trades` tab, but the user clarified that an explicit executed signals table was missing.

Then Codex changed the dashboard to include:

- An explicit `Executed Signals` tab.
- A top-level executed signals table.
- Lifecycle categories:
  - `ACTIVE`
  - `PENDING`
  - `HISTORICAL`

Later, the user requested all active, pending, queue, and historical records to be merged into one table.

Final dashboard state:

- `Executed Signals` tab contains one unified table.
- The table includes:
  - Active trades
  - Pending/submitted trades
  - Execution queue entries
  - Historical trades
- Filters were added for:
  - Lifecycle
  - Status
  - Side
  - Signal/record ID
- Old separate sections were removed.

## BrokerExecutionFailed Root Cause
Some executed signals showed:

`BrokerExecutionFailed`

Root cause found:

Capital.com rejected some `SELL` orders because stop loss was too close to the broker’s live sell-side boundary.

Example broker error:

`error.invalid.stoploss.minvalue: 2317.42`

The code was calculating SELL stop loss too loosely. It treated Capital.com’s:

`minStopOrProfitDistance = 0.01 PERCENTAGE`

incorrectly and calculated SELL stops from the bid/entry side.

Capital.com validates SELL stop loss against the offer/ask side plus the minimum percentage distance.

## BrokerExecutionFailed Fix
Codex fixed `src/trade_execution.py` to:

- Enforce broker stop/profit boundaries before `POST /positions`.
- Correctly handle `PERCENTAGE` minimum stop/profit distance.
- Use offer-side validation for SELL exits.
- Use bid-side validation for BUY exits.
- Add a small capped buffer using `TRADE_PRICE_TOLERANCE`, max `0.1`, to avoid immediate quote-drift rejection.
- Persist broker failures into `executed_trades` instead of leaving phantom `PENDING` rows.
- Reconcile 6 old phantom pending trades to `FAILED`, preserving the Capital.com rejection message.

Dashboard status after cleanup:

- Active: `0`
- Pending: `0`
- Historical: `46`

## Files Changed Across Session
Files changed during the session included:

- `src/trade_execution.py`
- `src/config.py`
- `.env`
- `.env.example`
- `src/dashboard_server.py`
- `src/dashboard_ui.py`
- `tests/test_trade_execution.py`
- `tests/test_dashboard_ui_contract.py`
- `docs/DASHBOARD_FUNCTIONALITY_AUDIT.md`

## Tests / Validation Reported
Codex reported these validations passed at different stages:

- `python -m py_compile src/config.py src/trade_execution.py src/dashboard_server.py src/dashboard_ui.py`
- `pytest tests/test_dashboard_ui_contract.py tests/test_trade_execution.py -q`
- Full test suite:
  - Initially: `203 passed`
  - Later: `204 passed`
  - Final after broker boundary fixes: `206 passed`
- Specific final trade execution tests:
  - `tests/test_trade_execution.py`
  - `19 passed`

## Important Current State
The system is now expected to execute new eligible signals to Capital.com demo immediately, even if validation status is `HOLD`, `BLOCKED`, etc.

However, execution can still fail because of hard broker/risk gates:

- Signal is stale
- Duplicate execution exists
- Market is not tradeable
- Max open trades reached
- Daily trade limit reached
- Daily loss limit reached
- Capital.com rejects TP/SL/size/order parameters
- Capital.com session/account issue
- Broker-side quote moved too far

## Important Note
Codex repeatedly stated it did not deliberately force-place a new Capital.com demo trade during testing. The fixes were implemented and tested through code/tests, but live demo order placement should still be verified with a fresh signal.

## Recommended Next Step
In the next session, do not start from scratch. Continue from the current state and verify live execution end-to-end:

1. Generate or manually enqueue a fresh signal.
2. Confirm it appears in the unified `Executed Signals` table.
3. Confirm queue status transitions properly.
4. Confirm Capital.com receives the order.
5. Confirm `POST /positions` and `GET /confirms/{dealReference}` succeed.
6. Confirm accepted trades become `OPEN`.
7. Confirm rejected trades are stored as `FAILED` with the broker rejection message.
8. Validate BUY and SELL TP/SL calculations separately against Capital.com min stop/profit distance rules.