ALTER TABLE signal_shadow_predictions
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'PENDING';

ALTER TABLE signal_shadow_predictions
    ADD COLUMN IF NOT EXISTS outcome_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_signal_shadow_predictions_status
    ON signal_shadow_predictions(status, generated_at_utc DESC);
