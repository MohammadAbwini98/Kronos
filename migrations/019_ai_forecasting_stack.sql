-- Optional AI forecasting stack tables.
-- These tables are additive and use the active PostgreSQL search_path schema.

CREATE TABLE IF NOT EXISTS model_registry (
    id BIGSERIAL PRIMARY KEY,
    model_key TEXT NOT NULL,
    model_family TEXT NOT NULL,
    version TEXT NOT NULL,
    artifact_path TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(model_key, version)
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    id BIGSERIAL PRIMARY KEY,
    model_key TEXT NOT NULL,
    model_version TEXT,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    input_start_ts TIMESTAMPTZ,
    input_end_ts TIMESTAMPTZ,
    horizon_bars INTEGER NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    error_message TEXT,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS forecasts (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES forecast_runs(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    forecast_for_ts TIMESTAMPTZ NOT NULL,
    horizon_bar INTEGER NOT NULL,
    predicted_close DOUBLE PRECISION,
    predicted_return DOUBLE PRECISION,
    predicted_direction TEXT,
    lower_bound DOUBLE PRECISION,
    upper_bound DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ensemble_forecasts (
    id BIGSERIAL PRIMARY KEY,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    forecast_for_ts TIMESTAMPTZ NOT NULL,
    horizon_bar INTEGER NOT NULL,
    ensemble_return DOUBLE PRECISION,
    ensemble_direction TEXT,
    agreement_score DOUBLE PRECISION,
    dispersion_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    model_votes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id BIGSERIAL PRIMARY KEY,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    regime TEXT,
    trend_strength DOUBLE PRECISION,
    realized_volatility DOUBLE PRECISION,
    garch_volatility DOUBLE PRECISION,
    spread DOUBLE PRECISION,
    liquidity_score DOUBLE PRECISION,
    risk_state TEXT,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS signal_scores (
    id BIGSERIAL PRIMARY KEY,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    candidate_signal TEXT NOT NULL,
    probability_win DOUBLE PRECISION,
    probability_loss DOUBLE PRECISION,
    expected_return DOUBLE PRECISION,
    model_agreement DOUBLE PRECISION,
    risk_score DOUBLE PRECISION,
    scorer_model TEXT,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision TEXT
);

CREATE TABLE IF NOT EXISTS forecast_validation (
    id BIGSERIAL PRIMARY KEY,
    model_key TEXT NOT NULL,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    horizon_bar INTEGER NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_samples INTEGER,
    direction_accuracy DOUBLE PRECISION,
    mae DOUBLE PRECISION,
    rmse DOUBLE PRECISION,
    hit_rate_after_spread DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    avg_return_after_cost DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ai_model_registry_enabled
    ON model_registry(model_family, is_enabled, model_key);
CREATE INDEX IF NOT EXISTS idx_ai_forecast_runs_model_time
    ON forecast_runs(model_key, timeframe, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_forecasts_model_tf_time
    ON forecasts(model_key, timeframe, forecast_for_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ai_ensemble_tf_time
    ON ensemble_forecasts(timeframe, forecast_for_ts DESC);
CREATE INDEX IF NOT EXISTS idx_ai_regime_tf_time
    ON regime_snapshots(timeframe, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_signal_scores_tf_time
    ON signal_scores(timeframe, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_forecast_validation_model_tf
    ON forecast_validation(model_key, timeframe, horizon_bar, evaluated_at DESC);

INSERT INTO schema_migrations(version)
VALUES ('019_ai_forecasting_stack')
ON CONFLICT (version) DO NOTHING;
