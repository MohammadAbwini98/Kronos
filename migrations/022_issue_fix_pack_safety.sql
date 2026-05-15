-- Additive safety migration for issue-fix-pack signal hygiene.

ALTER TABLE IF EXISTS signals
    ADD COLUMN IF NOT EXISTS is_trade_signal BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS strategy_type TEXT,
    ADD COLUMN IF NOT EXISTS risk_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS final_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS blocked_by JSONB;

UPDATE signals
SET is_trade_signal = CASE
    WHEN upper(COALESCE(signal, direction, '')) IN ('BUY', 'SELL', 'LONG', 'SHORT') THEN TRUE
    ELSE FALSE
END
WHERE is_trade_signal IS DISTINCT FROM CASE
    WHEN upper(COALESCE(signal, direction, '')) IN ('BUY', 'SELL', 'LONG', 'SHORT') THEN TRUE
    ELSE FALSE
END;

UPDATE signals
SET status = 'PENDING',
    outcome_reason = NULL,
    outcome_hit_timestamp_utc = NULL,
    updated_at = now()
WHERE upper(COALESCE(signal, direction, '')) NOT IN ('BUY', 'SELL', 'LONG', 'SHORT')
  AND upper(COALESCE(status, '')) IN ('WIN', 'LOSS');

DO $$
BEGIN
    IF to_regclass('gold_analytics.signal_recommendations') IS NOT NULL THEN
        ALTER TABLE gold_analytics.signal_recommendations
            ADD COLUMN IF NOT EXISTS is_trade_signal BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS strategy_type TEXT,
            ADD COLUMN IF NOT EXISTS risk_score DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS final_score DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS blocked_by JSONB;

        UPDATE gold_analytics.signal_recommendations
        SET is_trade_signal = CASE WHEN upper(COALESCE(signal, '')) IN ('BUY', 'SELL') THEN TRUE ELSE FALSE END;

        UPDATE gold_analytics.signal_recommendations
        SET outcome = NULL,
            pnl = NULL,
            exit_price = NULL,
            exit_ts = NULL,
            label_computed_at = NULL
        WHERE upper(COALESCE(signal, '')) NOT IN ('BUY', 'SELL');
    END IF;

    IF to_regclass('signal_recommendations') IS NOT NULL THEN
        ALTER TABLE signal_recommendations
            ADD COLUMN IF NOT EXISTS is_trade_signal BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS strategy_type TEXT,
            ADD COLUMN IF NOT EXISTS risk_score DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS final_score DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS blocked_by JSONB;

        UPDATE signal_recommendations
        SET is_trade_signal = CASE WHEN upper(COALESCE(signal, '')) IN ('BUY', 'SELL') THEN TRUE ELSE FALSE END;

        UPDATE signal_recommendations
        SET outcome = NULL,
            pnl = NULL,
            exit_price = NULL,
            exit_ts = NULL,
            label_computed_at = NULL
        WHERE upper(COALESCE(signal, '')) NOT IN ('BUY', 'SELL');
    END IF;
END $$;

INSERT INTO schema_migrations(version)
VALUES ('022_issue_fix_pack_safety')
ON CONFLICT (version) DO NOTHING;
