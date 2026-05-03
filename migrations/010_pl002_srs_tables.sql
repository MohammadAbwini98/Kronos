CREATE TABLE IF NOT EXISTS forecast_scoring_versions (
    scoring_version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    flat_threshold_pct NUMERIC(12, 8) NOT NULL,
    cost_threshold_pct NUMERIC(12, 8) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecast_scoring_versions_created
    ON forecast_scoring_versions(created_at DESC);

INSERT INTO forecast_scoring_versions(scoring_version, description, flat_threshold_pct, cost_threshold_pct)
VALUES ('v1', 'Canonical close-direction and cost-aware signal scoring.', 0.02, 0.05)
ON CONFLICT (scoring_version) DO NOTHING;

CREATE TABLE IF NOT EXISTS prediction_run_quality (
    run_id TEXT PRIMARY KEY REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    quality_grade TEXT NOT NULL,
    quality_score NUMERIC(12, 8) NOT NULL,
    lookback_rows_expected INTEGER NOT NULL,
    lookback_rows_actual INTEGER NOT NULL,
    missing_candle_count INTEGER NOT NULL DEFAULT 0,
    duplicate_timestamp_count INTEGER NOT NULL DEFAULT 0,
    largest_gap_minutes INTEGER NOT NULL DEFAULT 0,
    stale_live_price_seconds INTEGER,
    ohlc_repair_count INTEGER NOT NULL DEFAULT 0,
    volume_available BOOLEAN NOT NULL DEFAULT false,
    amount_available BOOLEAN NOT NULL DEFAULT false,
    source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_run_quality_grade
    ON prediction_run_quality(quality_grade, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_run_quality_score
    ON prediction_run_quality(quality_score DESC);

CREATE TABLE IF NOT EXISTS forecast_horizon_metrics (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    scoring_version TEXT NOT NULL REFERENCES forecast_scoring_versions(scoring_version),
    horizon_index INTEGER NOT NULL,
    forecast_timestamp_utc TIMESTAMPTZ NOT NULL,
    predicted_direction TEXT NOT NULL,
    actual_direction TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    forecast_close NUMERIC(20, 8) NOT NULL,
    actual_close NUMERIC(20, 8),
    close_error NUMERIC(20, 8),
    close_error_pct NUMERIC(20, 8),
    abs_close_error NUMERIC(20, 8),
    expected_move_pct NUMERIC(20, 8),
    realized_move_pct NUMERIC(20, 8),
    movement_after_cost_pct NUMERIC(20, 8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, scoring_version, horizon_index)
);

CREATE INDEX IF NOT EXISTS idx_forecast_horizon_metrics_run
    ON forecast_horizon_metrics(run_id, horizon_index);
CREATE INDEX IF NOT EXISTS idx_forecast_horizon_metrics_status
    ON forecast_horizon_metrics(status, forecast_timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_forecast_horizon_metrics_scoring
    ON forecast_horizon_metrics(scoring_version, horizon_index);

CREATE TABLE IF NOT EXISTS signal_quality_metrics (
    run_id TEXT PRIMARY KEY REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    scoring_version TEXT NOT NULL REFERENCES forecast_scoring_versions(scoring_version),
    signal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    actionable BOOLEAN NOT NULL,
    confidence NUMERIC(12, 8) NOT NULL,
    expected_move_pct NUMERIC(20, 8) NOT NULL,
    realized_move_pct NUMERIC(20, 8),
    cost_threshold_pct NUMERIC(12, 8) NOT NULL,
    movement_after_cost_pct NUMERIC(20, 8),
    precision_bucket TEXT,
    false_positive BOOLEAN,
    hold_quality TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_quality_status
    ON signal_quality_metrics(status, actionable, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_quality_signal
    ON signal_quality_metrics(signal, status);

CREATE TABLE IF NOT EXISTS market_feature_sets (
    feature_set_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled_features JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name, version)
);

INSERT INTO market_feature_sets(feature_set_id, name, version, parameters, enabled_features)
VALUES (
    'raw-ohlcv-v1',
    'raw-ohlcv',
    'v1',
    '{}'::jsonb,
    '["log_return","body_pct","range_pct","upper_wick_pct","lower_wick_pct","rolling_volatility_12","rolling_volatility_48","rolling_volume_zscore_48","trend_slope_12","atr_pct_14","hour_utc","day_of_week","session_label","source_quality_score","gap_from_previous_minutes"]'::jsonb
)
ON CONFLICT (feature_set_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS ohlcv_features (
    id BIGSERIAL PRIMARY KEY,
    candle_id BIGINT NOT NULL REFERENCES ohlcv_candles(id) ON DELETE CASCADE,
    feature_set_id TEXT NOT NULL REFERENCES market_feature_sets(feature_set_id),
    log_return NUMERIC(20, 12),
    body_pct NUMERIC(20, 12),
    range_pct NUMERIC(20, 12),
    upper_wick_pct NUMERIC(20, 12),
    lower_wick_pct NUMERIC(20, 12),
    rolling_volatility_12 NUMERIC(20, 12),
    rolling_volatility_48 NUMERIC(20, 12),
    rolling_volume_zscore_48 NUMERIC(20, 12),
    trend_slope_12 NUMERIC(20, 12),
    atr_pct_14 NUMERIC(20, 12),
    hour_utc SMALLINT,
    day_of_week SMALLINT,
    session_label TEXT,
    source_quality_score NUMERIC(12, 8),
    gap_from_previous_minutes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(candle_id, feature_set_id)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_features_feature_set
    ON ohlcv_features(feature_set_id, candle_id);
CREATE INDEX IF NOT EXISTS idx_ohlcv_features_session
    ON ohlcv_features(session_label, hour_utc);

CREATE TABLE IF NOT EXISTS dataset_snapshots (
    dataset_id TEXT PRIMARY KEY,
    dataset_role TEXT NOT NULL CHECK (dataset_role IN ('train', 'validation', 'shadow_eval', 'promotion_eval', 'backtest')),
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    price_side TEXT NOT NULL DEFAULT 'mid',
    feature_set_id TEXT REFERENCES market_feature_sets(feature_set_id),
    start_timestamp_utc TIMESTAMPTZ NOT NULL,
    end_timestamp_utc TIMESTAMPTZ NOT NULL,
    row_count INTEGER NOT NULL,
    missing_candle_count INTEGER NOT NULL DEFAULT 0,
    source_filter JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_filter JSONB NOT NULL DEFAULT '{}'::jsonb,
    checksum TEXT NOT NULL,
    artifact_path TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol, resolution, price_side, dataset_role, start_timestamp_utc, end_timestamp_utc, checksum)
);

CREATE INDEX IF NOT EXISTS idx_dataset_snapshots_symbol_time
    ON dataset_snapshots(symbol, resolution, start_timestamp_utc, end_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_dataset_snapshots_role
    ON dataset_snapshots(dataset_role, created_at DESC);

CREATE TABLE IF NOT EXISTS model_versions (
    model_version_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_path TEXT NOT NULL,
    tokenizer_path TEXT,
    base_model_version_id TEXT REFERENCES model_versions(model_version_id),
    training_dataset_id TEXT REFERENCES dataset_snapshots(dataset_id),
    validation_dataset_id TEXT REFERENCES dataset_snapshots(dataset_id),
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    feature_set_id TEXT REFERENCES market_feature_sets(feature_set_id),
    lookback INTEGER NOT NULL,
    pred_len INTEGER NOT NULL,
    promotion_status TEXT NOT NULL DEFAULT 'pending_review',
    promotion_reason TEXT,
    approval_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_versions_status
    ON model_versions(promotion_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_versions_symbol_resolution
    ON model_versions(symbol, resolution, created_at DESC);

CREATE TABLE IF NOT EXISTS run_model_versions (
    run_id TEXT PRIMARY KEY REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    model_version_id TEXT NOT NULL REFERENCES model_versions(model_version_id),
    role TEXT NOT NULL CHECK (role IN ('active', 'shadow', 'baseline', 'backtest')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shadow_evaluations (
    id BIGSERIAL PRIMARY KEY,
    active_run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    shadow_run_id TEXT NOT NULL,
    active_model_version_id TEXT REFERENCES model_versions(model_version_id),
    shadow_model_version_id TEXT NOT NULL REFERENCES model_versions(model_version_id),
    scoring_version TEXT NOT NULL REFERENCES forecast_scoring_versions(scoring_version),
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    generated_at_utc TIMESTAMPTZ NOT NULL,
    active_signal TEXT NOT NULL,
    active_status TEXT NOT NULL DEFAULT 'PENDING',
    shadow_signal TEXT NOT NULL,
    shadow_status TEXT NOT NULL DEFAULT 'PENDING',
    disagreement BOOLEAN NOT NULL,
    active_wins INTEGER NOT NULL DEFAULT 0,
    active_losses INTEGER NOT NULL DEFAULT 0,
    shadow_wins INTEGER NOT NULL DEFAULT 0,
    shadow_losses INTEGER NOT NULL DEFAULT 0,
    comparable_horizons INTEGER NOT NULL DEFAULT 0,
    horizon_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_quality_grade TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(active_run_id, shadow_model_version_id, scoring_version)
);

CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_model
    ON shadow_evaluations(shadow_model_version_id, generated_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_status
    ON shadow_evaluations(shadow_status, active_status);
CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_disagreement
    ON shadow_evaluations(disagreement, generated_at_utc DESC);

CREATE TABLE IF NOT EXISTS promotion_gate_results (
    id BIGSERIAL PRIMARY KEY,
    model_version_id TEXT NOT NULL REFERENCES model_versions(model_version_id) ON DELETE CASCADE,
    gate_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'WARN', 'SKIP')),
    metric_value NUMERIC(20, 8),
    threshold_value NUMERIC(20, 8),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promotion_gate_results_model
    ON promotion_gate_results(model_version_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_promotion_gate_results_status
    ON promotion_gate_results(status, gate_name);

CREATE TABLE IF NOT EXISTS walk_forward_experiments (
    experiment_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    price_side TEXT NOT NULL DEFAULT 'mid',
    model_version_id TEXT REFERENCES model_versions(model_version_id),
    baseline_method TEXT,
    feature_set_id TEXT REFERENCES market_feature_sets(feature_set_id),
    start_timestamp_utc TIMESTAMPTZ NOT NULL,
    end_timestamp_utc TIMESTAMPTZ NOT NULL,
    lookback INTEGER NOT NULL,
    pred_len INTEGER NOT NULL,
    stride INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS walk_forward_results (
    id BIGSERIAL PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES walk_forward_experiments(experiment_id) ON DELETE CASCADE,
    window_start_timestamp_utc TIMESTAMPTZ NOT NULL,
    input_end_timestamp_utc TIMESTAMPTZ NOT NULL,
    forecast_start_timestamp_utc TIMESTAMPTZ NOT NULL,
    forecast_end_timestamp_utc TIMESTAMPTZ NOT NULL,
    run_id TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_quality JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(experiment_id, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_walk_forward_results_experiment
    ON walk_forward_results(experiment_id, forecast_start_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_walk_forward_results_cache
    ON walk_forward_results(cache_key);

CREATE TABLE IF NOT EXISTS api_rate_limit_state (
    endpoint_class TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('OK', 'COOLDOWN')),
    last_error TEXT,
    last_status_code INTEGER,
    retry_after_utc TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS supervisor_leases (
    lease_name TEXT PRIMARY KEY,
    supervisor_instance_id TEXT NOT NULL,
    host_name TEXT NOT NULL,
    process_id INTEGER NOT NULL,
    command_line TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_supervisor_leases_expiry
    ON supervisor_leases(expires_at);

ALTER TABLE prediction_runs
    ADD COLUMN IF NOT EXISTS scoring_version TEXT REFERENCES forecast_scoring_versions(scoring_version),
    ADD COLUMN IF NOT EXISTS data_quality_grade TEXT,
    ADD COLUMN IF NOT EXISTS model_version_id TEXT REFERENCES model_versions(model_version_id),
    ADD COLUMN IF NOT EXISTS experiment_id TEXT;

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS scoring_version TEXT REFERENCES forecast_scoring_versions(scoring_version),
    ADD COLUMN IF NOT EXISTS actionable BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS quality_grade TEXT,
    ADD COLUMN IF NOT EXISTS movement_after_cost_pct NUMERIC(20, 8);

ALTER TABLE signal_shadow_predictions
    ADD COLUMN IF NOT EXISTS shadow_model_version_id TEXT REFERENCES model_versions(model_version_id),
    ADD COLUMN IF NOT EXISTS scoring_version TEXT REFERENCES forecast_scoring_versions(scoring_version),
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS outcome_updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS disagreement BOOLEAN,
    ADD COLUMN IF NOT EXISTS horizon_metrics JSONB NOT NULL DEFAULT '{}'::jsonb;
