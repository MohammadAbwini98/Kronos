ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS outcome_policy_version TEXT NOT NULL DEFAULT 'signal_trade_v1',
    ADD COLUMN IF NOT EXISTS outcome_reason TEXT,
    ADD COLUMN IF NOT EXISTS outcome_hit_timestamp_utc TIMESTAMPTZ;

ALTER TABLE signal_shadow_predictions
    ADD COLUMN IF NOT EXISTS outcome_policy_version TEXT NOT NULL DEFAULT 'signal_trade_v1',
    ADD COLUMN IF NOT EXISTS outcome_reason TEXT,
    ADD COLUMN IF NOT EXISTS outcome_hit_timestamp_utc TIMESTAMPTZ;

ALTER TABLE signal_quality_metrics
    ADD COLUMN IF NOT EXISTS outcome_policy_version TEXT,
    ADD COLUMN IF NOT EXISTS outcome_reason TEXT,
    ADD COLUMN IF NOT EXISTS outcome_hit_timestamp_utc TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_signals_outcome_policy
    ON signals(outcome_policy_version, status, outcome_hit_timestamp_utc DESC);

