-- Round 1 strategy-brain architecture tables.
-- These tables are additive and use the active PostgreSQL search_path schema.

CREATE TABLE IF NOT EXISTS strategy_decisions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    signal TEXT NOT NULL,
    strategy_type TEXT,
    regime TEXT,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    take_profit_1 DOUBLE PRECISION,
    take_profit_2 DOUBLE PRECISION,
    position_size DOUBLE PRECISION,
    risk_reward_1 DOUBLE PRECISION,
    risk_reward_2 DOUBLE PRECISION,
    strategy_score DOUBLE PRECISION,
    ai_support_score DOUBLE PRECISION,
    risk_score DOUBLE PRECISION,
    final_score DOUBLE PRECISION,
    decision_status TEXT NOT NULL,
    reason TEXT,
    blocked_by JSONB,
    indicators_json JSONB,
    ai_json JSONB,
    risk_json JSONB
);

CREATE TABLE IF NOT EXISTS ai_support_evaluations (
    id BIGSERIAL PRIMARY KEY,
    strategy_decision_id BIGINT REFERENCES strategy_decisions(id),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    model_key TEXT NOT NULL,
    model_status TEXT NOT NULL,
    candidate_signal TEXT NOT NULL,
    predicted_return DOUBLE PRECISION,
    predicted_direction TEXT,
    support_value DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    latency_ms INTEGER,
    raw_json JSONB,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS strategy_performance (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy_type TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_trades INTEGER,
    win_rate DOUBLE PRECISION,
    profit_factor DOUBLE PRECISION,
    expectancy DOUBLE PRECISION,
    avg_win DOUBLE PRECISION,
    avg_loss DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    sharpe DOUBLE PRECISION,
    details_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_strategy_decisions_symbol_tf_time
    ON strategy_decisions(symbol, timeframe, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_support_eval_decision_time
    ON ai_support_evaluations(strategy_decision_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_support_eval_symbol_tf_time
    ON ai_support_evaluations(symbol, timeframe, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_performance_symbol_tf_time
    ON strategy_performance(symbol, timeframe, evaluated_at DESC);