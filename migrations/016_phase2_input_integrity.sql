CREATE TABLE IF NOT EXISTS prediction_input_rejections (
    id BIGSERIAL PRIMARY KEY,
    prediction_request_id TEXT,
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    resolution TEXT NOT NULL,
    price_side TEXT NOT NULL DEFAULT 'mid',
    requested_lookback INTEGER NOT NULL,
    actual_lookback INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    rejection_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_path TEXT,
    input_csv_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_input_rejections_symbol_time
    ON prediction_input_rejections(symbol, resolution, created_at DESC);

ALTER TABLE prediction_run_quality
    ADD COLUMN IF NOT EXISTS first_timestamp_utc TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_timestamp_utc TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS requested_lookback INTEGER,
    ADD COLUMN IF NOT EXISTS actual_lookback INTEGER,
    ADD COLUMN IF NOT EXISTS selected_feature_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS terminal_close NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS price_side TEXT,
    ADD COLUMN IF NOT EXISTS resolution TEXT,
    ADD COLUMN IF NOT EXISTS symbol TEXT,
    ADD COLUMN IF NOT EXISTS gap_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS feature_mode TEXT,
    ADD COLUMN IF NOT EXISTS strict_policy_passed BOOLEAN,
    ADD COLUMN IF NOT EXISTS strict_policy_rejection_reason TEXT;

ALTER TABLE prediction_runs
    ADD COLUMN IF NOT EXISTS feature_mode TEXT,
    ADD COLUMN IF NOT EXISTS input_quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS forecast_timestamp_check_status TEXT,
    ADD COLUMN IF NOT EXISTS forecast_timestamp_mismatches JSONB NOT NULL DEFAULT '[]'::jsonb;

INSERT INTO schema_migrations(version)
VALUES ('016_phase2_input_integrity')
ON CONFLICT (version) DO NOTHING;
