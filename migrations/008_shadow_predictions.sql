CREATE TABLE IF NOT EXISTS signal_shadow_predictions (
    active_run_id TEXT PRIMARY KEY REFERENCES prediction_runs(run_id) ON DELETE CASCADE,
    shadow_run_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_path TEXT,
    generated_at_utc TIMESTAMPTZ NOT NULL,
    signal TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence NUMERIC(12, 8) NOT NULL,
    expected_move_pct NUMERIC(12, 8) NOT NULL,
    cost_threshold_pct NUMERIC(12, 8) NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    tp_price NUMERIC(20, 8) NOT NULL,
    sl_price NUMERIC(20, 8) NOT NULL,
    reason TEXT NOT NULL,
    metadata_path TEXT,
    forecast_csv_path TEXT,
    validation_report_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_shadow_predictions_generated
    ON signal_shadow_predictions(generated_at_utc DESC);
