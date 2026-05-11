-- Phase 3: signal filtering and execution-gate audit trail.
-- Decisions are immutable per evaluation so blocked signals remain visible.

CREATE TABLE IF NOT EXISTS trade_execution_decisions (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    raw_signal TEXT,
    validation_status TEXT,
    validation_score NUMERIC,
    validation_age_seconds NUMERIC,
    expected_move_pct NUMERIC,
    spread_pct NUMERIC,
    estimated_fee_pct NUMERIC,
    estimated_slippage_pct NUMERIC,
    safety_margin_pct NUMERIC,
    net_expected_edge_pct NUMERIC,
    execution_decision TEXT NOT NULL CHECK (execution_decision IN ('ALLOW', 'BLOCK')),
    block_reason TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_trade_execution_decisions_signal_time
    ON trade_execution_decisions(signal_id, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_execution_decisions_decision_time
    ON trade_execution_decisions(execution_decision, evaluated_at DESC);

ALTER TABLE trade_execution_candidates
    ADD COLUMN IF NOT EXISTS last_execution_decision TEXT,
    ADD COLUMN IF NOT EXISTS last_block_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_decision_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_decision_details JSONB;
