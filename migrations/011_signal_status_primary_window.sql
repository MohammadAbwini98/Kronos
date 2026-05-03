WITH primary_window AS (
    SELECT
        o.run_id,
        CASE
            WHEN UPPER(COALESCE(o.status, 'PENDING')) IN ('WIN', 'LOSS') THEN UPPER(o.status)
            ELSE 'PENDING'
        END AS signal_status
    FROM prediction_outcomes o
    JOIN forecast_candles fc ON fc.id = o.forecast_candle_id
    WHERE fc.horizon_index = 1
)
UPDATE signals s
SET status = p.signal_status,
    outcome_updated_at = CASE
        WHEN p.signal_status = 'PENDING' THEN s.outcome_updated_at
        ELSE now()
    END,
    updated_at = now()
FROM primary_window p
WHERE s.run_id = p.run_id
  AND COALESCE(s.status, 'PENDING') IS DISTINCT FROM p.signal_status;

UPDATE signals s
SET status = 'PENDING',
    updated_at = now()
WHERE NOT EXISTS (
    SELECT 1
    FROM prediction_outcomes o
    JOIN forecast_candles fc ON fc.id = o.forecast_candle_id
    WHERE o.run_id = s.run_id
      AND fc.horizon_index = 1
)
  AND COALESCE(s.status, 'PENDING') <> 'PENDING';
