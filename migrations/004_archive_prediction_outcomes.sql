CREATE TABLE IF NOT EXISTS prediction_outcomes_archive (
    id BIGINT PRIMARY KEY,
    run_id TEXT NOT NULL,
    forecast_candle_id BIGINT NOT NULL,
    actual_candle_id BIGINT,
    forecast_timestamp_utc TIMESTAMPTZ NOT NULL,
    actual_timestamp_utc TIMESTAMPTZ,
    predicted_direction TEXT NOT NULL,
    actual_direction TEXT,
    forecast_close NUMERIC(20, 8) NOT NULL,
    actual_close NUMERIC(20, 8),
    close_error NUMERIC(20, 8),
    close_error_pct NUMERIC(12, 8),
    status TEXT NOT NULL,
    validated_at_utc TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_archive_run_time
    ON prediction_outcomes_archive(run_id, forecast_timestamp_utc DESC);

CREATE INDEX IF NOT EXISTS idx_prediction_outcomes_archive_status
    ON prediction_outcomes_archive(status, archived_at DESC);
