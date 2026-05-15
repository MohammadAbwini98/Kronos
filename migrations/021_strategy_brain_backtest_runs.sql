-- Strategy-brain backtest summary table.
-- This table is additive and uses the active PostgreSQL search_path schema.

CREATE TABLE IF NOT EXISTS strategy_backtest_runs (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy_type TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'PENDING',
    lookback_start TIMESTAMPTZ,
    lookback_end TIMESTAMPTZ,
    trades_count INTEGER,
    win_rate DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    expectancy DOUBLE PRECISION,
    avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    sharpe DOUBLE PRECISION,
    approved_for_paper BOOLEAN,
    config_json JSONB,
    summary_json JSONB,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_strategy_backtest_runs_symbol_tf_time
    ON strategy_backtest_runs(symbol, timeframe, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_backtest_runs_status_time
    ON strategy_backtest_runs(status, started_at DESC);