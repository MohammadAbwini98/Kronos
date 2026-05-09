CREATE TABLE IF NOT EXISTS trade_execution_candidates (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE,
    run_id TEXT,
    source_model TEXT NOT NULL DEFAULT 'Kronos',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    recommended_entry NUMERIC(20, 8),
    stop_loss NUMERIC(20, 8),
    take_profit NUMERIC(20, 8),
    confidence NUMERIC(12, 8),
    generated_at_utc TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS executed_trades (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE,
    candidate_id BIGINT REFERENCES trade_execution_candidates(id) ON DELETE SET NULL,
    run_id TEXT,
    source_model TEXT NOT NULL DEFAULT 'Kronos',
    symbol TEXT NOT NULL,
    epic TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    requested_size NUMERIC(20, 8) NOT NULL DEFAULT 0,
    executed_size NUMERIC(20, 8) NOT NULL DEFAULT 0,
    recommended_entry NUMERIC(20, 8),
    actual_entry NUMERIC(20, 8),
    stop_loss NUMERIC(20, 8),
    take_profit NUMERIC(20, 8),
    status TEXT NOT NULL DEFAULT 'PENDING',
    failure_reason TEXT,
    broker_rejection_reason TEXT,
    broker_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    deal_reference TEXT,
    deal_id TEXT,
    account_id TEXT,
    account_name TEXT,
    is_demo BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_executed_trades_status
    ON executed_trades(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_executed_trades_account_status
    ON executed_trades(account_id, account_name, is_demo, status);

CREATE TABLE IF NOT EXISTS trade_execution_queue (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    candidate_id BIGINT REFERENCES trade_execution_candidates(id) ON DELETE SET NULL,
    requested_by TEXT NOT NULL DEFAULT 'auto',
    requested_size NUMERIC(20, 8),
    force_market_execution BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_trade_id BIGINT REFERENCES executed_trades(id) ON DELETE SET NULL,
    failure_reason TEXT,
    error_details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_execution_queue_active_signal
    ON trade_execution_queue(signal_id)
    WHERE status IN ('QUEUED', 'PROCESSING');
CREATE INDEX IF NOT EXISTS idx_trade_execution_queue_dispatch
    ON trade_execution_queue(status, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS trade_execution_attempts (
    id BIGSERIAL PRIMARY KEY,
    executed_trade_id BIGINT REFERENCES executed_trades(id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    success BOOLEAN NOT NULL DEFAULT false,
    summary TEXT,
    error_details TEXT,
    broker_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trade_execution_attempts_signal
    ON trade_execution_attempts(signal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS trade_execution_events (
    id BIGSERIAL PRIMARY KEY,
    executed_trade_id BIGINT REFERENCES executed_trades(id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trade_execution_events_signal
    ON trade_execution_events(signal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS broker_account_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    is_demo BOOLEAN NOT NULL,
    currency TEXT,
    balance NUMERIC(20, 8),
    available NUMERIC(20, 8),
    profit_loss NUMERIC(20, 8),
    equity NUMERIC(20, 8),
    open_positions INTEGER NOT NULL DEFAULT 0,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_broker_account_snapshots_latest
    ON broker_account_snapshots(account_name, is_demo, created_at DESC);
