CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_instruments (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'Capital.com',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    market_name TEXT,
    price_side TEXT NOT NULL DEFAULT 'mid',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, symbol, epic, price_side)
);

CREATE TABLE IF NOT EXISTS ohlcv_candles (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'Capital.com',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    resolution TEXT NOT NULL,
    price_side TEXT NOT NULL DEFAULT 'mid',
    timestamp_utc TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(28, 10) NOT NULL DEFAULT 0,
    amount NUMERIC(28, 10) NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'historical',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ohlcv_valid_prices CHECK (high >= open AND high >= close AND high >= low AND low <= open AND low <= close AND low <= high),
    UNIQUE(provider, symbol, epic, resolution, price_side, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_resolution_time
    ON ohlcv_candles(symbol, resolution, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_epic_resolution_time
    ON ohlcv_candles(epic, resolution, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS raw_market_events (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'Capital.com',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_timestamp_utc TIMESTAMPTZ,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_market_events_epic_time
    ON raw_market_events(epic, event_timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS prediction_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'Capital.com',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    market_name TEXT,
    resolution TEXT NOT NULL,
    price_side TEXT NOT NULL DEFAULT 'mid',
    source_provider TEXT NOT NULL DEFAULT 'Capital.com',
    model_name TEXT NOT NULL,
    model_path TEXT,
    tokenizer_path TEXT,
    generated_at_utc TIMESTAMPTZ NOT NULL,
    input_start_timestamp_utc TIMESTAMPTZ NOT NULL,
    input_end_timestamp_utc TIMESTAMPTZ NOT NULL,
    forecast_start_timestamp_utc TIMESTAMPTZ NOT NULL,
    forecast_end_timestamp_utc TIMESTAMPTZ NOT NULL,
    input_rows_used INTEGER NOT NULL,
    forecast_rows INTEGER NOT NULL,
    forecast_horizon_minutes INTEGER NOT NULL,
    last_input_close NUMERIC(20, 8) NOT NULL,
    metadata_path TEXT,
    input_csv_path TEXT,
    forecast_csv_path TEXT,
    validation_report_path TEXT,
    run_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_runs_symbol_generated
    ON prediction_runs(symbol, generated_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_runs_status
    ON prediction_runs(run_status);

CREATE TABLE IF NOT EXISTS forecast_candles (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    horizon_index INTEGER NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(28, 10) NOT NULL DEFAULT 0,
    amount NUMERIC(28, 10) NOT NULL DEFAULT 0,
    anchor_close NUMERIC(20, 8) NOT NULL,
    predicted_direction TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, horizon_index),
    UNIQUE(run_id, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_forecast_candles_timestamp
    ON forecast_candles(timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    resolution TEXT NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    signal TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence NUMERIC(12, 8) NOT NULL,
    expected_move_pct NUMERIC(12, 8) NOT NULL,
    cost_threshold_pct NUMERIC(12, 8) NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id)
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_time
    ON signals(symbol, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    forecast_candle_id BIGINT NOT NULL REFERENCES forecast_candles(id) ON DELETE CASCADE,
    actual_candle_id BIGINT REFERENCES ohlcv_candles(id) ON DELETE SET NULL,
    forecast_timestamp_utc TIMESTAMPTZ NOT NULL,
    actual_timestamp_utc TIMESTAMPTZ,
    predicted_direction TEXT NOT NULL,
    actual_direction TEXT,
    forecast_close NUMERIC(20, 8) NOT NULL,
    actual_close NUMERIC(20, 8),
    close_error NUMERIC(20, 8),
    close_error_pct NUMERIC(12, 8),
    status TEXT NOT NULL DEFAULT 'PENDING',
    validated_at_utc TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, forecast_candle_id)
);

CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_status
    ON prediction_outcomes(status);
CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_time
    ON prediction_outcomes(forecast_timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations(version)
VALUES ('001_init')
ON CONFLICT (version) DO NOTHING;
