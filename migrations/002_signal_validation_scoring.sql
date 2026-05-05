CREATE TABLE IF NOT EXISTS signal_validation_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    base_resolution TEXT NOT NULL,
    candidate_signal TEXT NOT NULL,
    final_signal TEXT NOT NULL,
    forecast_direction TEXT NOT NULL,
    last_input_close NUMERIC(20, 8),
    forecast_close NUMERIC(20, 8),
    forecast_return_pct NUMERIC(12, 8),
    estimated_cost_pct NUMERIC(12, 8),
    net_edge_pct NUMERIC(12, 8),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    block_reason TEXT,
    confidence_level TEXT NOT NULL,
    total_score NUMERIC(8, 4) NOT NULL,
    component_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason_details JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id)
);

CREATE TABLE IF NOT EXISTS signal_timeframe_validations (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    timeframe TEXT NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    trend TEXT NOT NULL,
    confirms_candidate BOOLEAN NOT NULL,
    trend_score NUMERIC(8, 4) NOT NULL,
    momentum_score NUMERIC(8, 4) NOT NULL,
    volume_score NUMERIC(8, 4) NOT NULL,
    volatility_score NUMERIC(8, 4) NOT NULL,
    support_resistance_score NUMERIC(8, 4) NOT NULL,
    total_timeframe_score NUMERIC(8, 4) NOT NULL,
    indicator_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_details JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_signal_validation_runs_created
    ON signal_validation_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_validation_runs_symbol_signal
    ON signal_validation_runs(symbol, final_signal, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signal_timeframe_validations_run
    ON signal_timeframe_validations(run_id);

ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_score NUMERIC(8, 4);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_status TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_summary JSONB NOT NULL DEFAULT '{}'::jsonb;
