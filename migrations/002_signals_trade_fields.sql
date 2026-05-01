ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS signal_id TEXT;

UPDATE signals
SET signal_id = run_id
WHERE signal_id IS NULL OR signal_id = '';

ALTER TABLE signals
    ALTER COLUMN signal_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_signal_id
    ON signals(signal_id);

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS entry_price NUMERIC(20, 8);

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS tp_price NUMERIC(20, 8);

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS sl_price NUMERIC(20, 8);

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'PENDING';

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS outcome_updated_at TIMESTAMPTZ;

UPDATE signals s
SET entry_price = COALESCE(s.entry_price, r.last_input_close),
    status = COALESCE(NULLIF(s.status, ''), 'PENDING')
FROM prediction_runs r
WHERE r.run_id = s.run_id;

CREATE INDEX IF NOT EXISTS idx_signals_filters
    ON signals(resolution, timestamp_utc DESC, direction, status);
