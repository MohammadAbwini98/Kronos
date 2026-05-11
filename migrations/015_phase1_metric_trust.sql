ALTER TABLE executed_trades
    ADD COLUMN IF NOT EXISTS entry_price NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS exit_price NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS gross_pnl NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS net_pnl NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS fee_amount NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS spread_cost NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS slippage_estimate NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS close_reason TEXT,
    ADD COLUMN IF NOT EXISTS final_outcome TEXT,
    ADD COLUMN IF NOT EXISTS outcome_finalized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validation_status_at_execution TEXT,
    ADD COLUMN IF NOT EXISTS validation_score_at_execution NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS expected_move_pct_at_execution NUMERIC(20, 8),
    ADD COLUMN IF NOT EXISTS entry_spread_pct NUMERIC(20, 8);

UPDATE executed_trades
SET entry_price = COALESCE(entry_price, actual_entry, recommended_entry)
WHERE entry_price IS NULL
  AND COALESCE(actual_entry, recommended_entry) IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_executed_trades_final_outcome
    ON executed_trades(final_outcome, outcome_finalized_at DESC);
CREATE INDEX IF NOT EXISTS idx_executed_trades_closed_finalized
    ON executed_trades(status, final_outcome, outcome_finalized_at DESC)
    WHERE status = 'CLOSED';

ALTER TABLE prediction_runs
    ADD COLUMN IF NOT EXISTS actual_window_status TEXT,
    ADD COLUMN IF NOT EXISTS terminal_predicted_direction TEXT,
    ADD COLUMN IF NOT EXISTS terminal_actual_direction TEXT,
    ADD COLUMN IF NOT EXISTS terminal_direction_status TEXT,
    ADD COLUMN IF NOT EXISTS path_outcome_status TEXT,
    ADD COLUMN IF NOT EXISTS validation_finalized_at TIMESTAMPTZ;

ALTER TABLE prediction_outcomes
    ADD COLUMN IF NOT EXISTS validation_state TEXT NOT NULL DEFAULT 'NEEDS_MORE_SAMPLES',
    ADD COLUMN IF NOT EXISTS validation_scope TEXT NOT NULL DEFAULT 'PER_HORIZON_DIRECTION',
    ADD COLUMN IF NOT EXISTS actual_window_complete BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS terminal_predicted_direction TEXT,
    ADD COLUMN IF NOT EXISTS terminal_actual_direction TEXT,
    ADD COLUMN IF NOT EXISTS terminal_direction_status TEXT,
    ADD COLUMN IF NOT EXISTS path_outcome_status TEXT;

UPDATE prediction_outcomes
SET validation_state = CASE
        WHEN status IN ('WIN', 'LOSS') THEN 'FINAL'
        WHEN actual_close IS NOT NULL THEN 'PARTIAL_PROGRESS'
        ELSE 'NEEDS_MORE_SAMPLES'
    END,
    actual_window_complete = status IN ('WIN', 'LOSS')
WHERE validation_state = 'NEEDS_MORE_SAMPLES';

ALTER TABLE forecast_horizon_metrics
    ADD COLUMN IF NOT EXISTS validation_state TEXT NOT NULL DEFAULT 'NEEDS_MORE_SAMPLES',
    ADD COLUMN IF NOT EXISTS validation_scope TEXT NOT NULL DEFAULT 'PER_HORIZON_DIRECTION',
    ADD COLUMN IF NOT EXISTS actual_window_complete BOOLEAN NOT NULL DEFAULT false;

UPDATE forecast_horizon_metrics
SET validation_state = CASE
        WHEN status IN ('WIN', 'LOSS') THEN 'FINAL'
        WHEN actual_close IS NOT NULL THEN 'PARTIAL_PROGRESS'
        ELSE 'NEEDS_MORE_SAMPLES'
    END,
    actual_window_complete = status IN ('WIN', 'LOSS')
WHERE validation_state = 'NEEDS_MORE_SAMPLES';

CREATE TABLE IF NOT EXISTS baseline_comparison_metrics (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    scoring_version TEXT NOT NULL REFERENCES forecast_scoring_versions(scoring_version),
    baseline_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    model_metric NUMERIC(20, 8),
    baseline_metric NUMERIC(20, 8),
    delta NUMERIC(20, 8),
    sample_count INTEGER NOT NULL DEFAULT 0,
    enough_samples BOOLEAN NOT NULL DEFAULT false,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, scoring_version, baseline_name, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_baseline_comparison_metrics_run
    ON baseline_comparison_metrics(run_id, baseline_name);
CREATE INDEX IF NOT EXISTS idx_baseline_comparison_metrics_metric
    ON baseline_comparison_metrics(scoring_version, metric_name, enough_samples);

INSERT INTO schema_migrations(version)
VALUES ('015_phase1_metric_trust')
ON CONFLICT (version) DO NOTHING;
