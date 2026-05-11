-- Phase 4: model experiment metadata and analysis persistence.

ALTER TABLE prediction_runs
    ADD COLUMN IF NOT EXISTS feature_set_name TEXT,
    ADD COLUMN IF NOT EXISTS feature_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS lookback INTEGER,
    ADD COLUMN IF NOT EXISTS horizon INTEGER,
    ADD COLUMN IF NOT EXISTS amount_available BOOLEAN,
    ADD COLUMN IF NOT EXISTS amount_derivation_method TEXT,
    ADD COLUMN IF NOT EXISTS regime_context_used BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS amount_mode TEXT,
    ADD COLUMN IF NOT EXISTS horizon_policy TEXT,
    ADD COLUMN IF NOT EXISTS regime_feature_version TEXT,
    ADD COLUMN IF NOT EXISTS calibration_version TEXT,
    ADD COLUMN IF NOT EXISTS training_data_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS training_data_end TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_data_start TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_data_end TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS leakage_check_status TEXT,
    ADD COLUMN IF NOT EXISTS baseline_comparison_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS model_experiment_reports (
    id BIGSERIAL PRIMARY KEY,
    report_name TEXT NOT NULL,
    symbol TEXT,
    resolution TEXT,
    feature_mode TEXT,
    model_version_id TEXT,
    report_type TEXT NOT NULL,
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_count INTEGER NOT NULL DEFAULT 0,
    enough_samples BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_experiment_reports_lookup
    ON model_experiment_reports(report_type, symbol, resolution, feature_mode, created_at DESC);

CREATE TABLE IF NOT EXISTS confidence_calibration_buckets (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    signal_type TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    volatility_regime TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence_bucket TEXT NOT NULL,
    observed_win_rate NUMERIC(20, 8),
    empirical_win_rate_raw NUMERIC(20, 8),
    sample_count INTEGER NOT NULL DEFAULT 0,
    enough_samples BOOLEAN NOT NULL DEFAULT false,
    calibration_version TEXT NOT NULL DEFAULT 'empirical_untrusted_v1',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol, resolution, horizon, signal_type, validation_status, volatility_regime, confidence_bucket, calibration_version)
);

CREATE INDEX IF NOT EXISTS idx_confidence_calibration_buckets_lookup
    ON confidence_calibration_buckets(symbol, resolution, horizon, enough_samples);

INSERT INTO schema_migrations(version)
VALUES ('018_phase4_model_experiments')
ON CONFLICT (version) DO NOTHING;
