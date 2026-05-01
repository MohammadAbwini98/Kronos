WITH outcome_rollup AS (
    SELECT
        run_id,
        COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
        COALESCE(SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
        COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending,
        COALESCE(SUM(CASE WHEN status IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0)::int AS validated
    FROM prediction_outcomes
    GROUP BY run_id
)
UPDATE signals s
SET status = CASE
        WHEN o.validated = 0 THEN 'PENDING'
        WHEN o.wins >= o.losses THEN 'WIN'
        ELSE 'LOSS'
    END,
    outcome_updated_at = now(),
    updated_at = now()
FROM outcome_rollup o
WHERE s.run_id = o.run_id;

WITH outcome_rollup AS (
    SELECT
        run_id,
        COALESCE(SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END), 0)::int AS pending,
        COALESCE(SUM(CASE WHEN status IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0)::int AS validated
    FROM prediction_outcomes
    GROUP BY run_id
)
UPDATE prediction_runs r
SET run_status = CASE
        WHEN o.pending = 0 AND o.validated > 0 THEN 'VALIDATED'
        WHEN o.validated > 0 THEN 'PARTIAL'
        ELSE 'PENDING'
    END,
    updated_at = now()
FROM outcome_rollup o
WHERE r.run_id = o.run_id
  AND r.run_status IN ('PENDING', 'PARTIAL', 'VALIDATED');
