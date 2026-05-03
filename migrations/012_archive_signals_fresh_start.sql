-- Migration: 012_archive_signals_fresh_start
-- Purpose  : Archive all prediction-run / signal data to *_archive tables,
--             then wipe the live tables for a clean slate.
--
-- Tables cleared (via CASCADE on prediction_runs):
--   prediction_runs, forecast_candles, prediction_outcomes, signals,
--   signal_shadow_predictions, prediction_run_quality,
--   forecast_horizon_metrics, signal_quality_metrics,
--   run_model_versions, shadow_evaluations
--
-- Tables NOT touched (intentionally preserved):
--   ohlcv_candles, raw_market_events, market_instruments,
--   model_versions, dataset_snapshots, walk_forward_experiments,
--   walk_forward_results, promotion_gate_results,
--   forecast_scoring_versions, service_heartbeats

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1.  Create archive tables (idempotent)
-- ─────────────────────────────────────────────────────────────────────────────

-- prediction_runs
CREATE TABLE IF NOT EXISTS prediction_runs_archive (
    LIKE prediction_runs INCLUDING DEFAULTS
);
ALTER TABLE prediction_runs_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_prediction_runs_archive_symbol
    ON prediction_runs_archive(symbol, generated_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_runs_archive_at
    ON prediction_runs_archive(archived_at DESC);

-- forecast_candles
CREATE TABLE IF NOT EXISTS forecast_candles_archive (
    LIKE forecast_candles INCLUDING DEFAULTS
);
ALTER TABLE forecast_candles_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_forecast_candles_archive_run
    ON forecast_candles_archive(run_id, archived_at DESC);

-- prediction_outcomes already has an archive table from migration 004;
-- no structure change needed.

-- signals
CREATE TABLE IF NOT EXISTS signals_archive (
    LIKE signals INCLUDING DEFAULTS
);
ALTER TABLE signals_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_signals_archive_symbol_time
    ON signals_archive(symbol, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_signals_archive_at
    ON signals_archive(archived_at DESC);

-- signal_shadow_predictions
CREATE TABLE IF NOT EXISTS signal_shadow_predictions_archive (
    LIKE signal_shadow_predictions INCLUDING DEFAULTS
);
ALTER TABLE signal_shadow_predictions_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_signal_shadow_predictions_archive_at
    ON signal_shadow_predictions_archive(archived_at DESC);

-- prediction_run_quality
CREATE TABLE IF NOT EXISTS prediction_run_quality_archive (
    LIKE prediction_run_quality INCLUDING DEFAULTS
);
ALTER TABLE prediction_run_quality_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_prediction_run_quality_archive_at
    ON prediction_run_quality_archive(archived_at DESC);

-- forecast_horizon_metrics
CREATE TABLE IF NOT EXISTS forecast_horizon_metrics_archive (
    LIKE forecast_horizon_metrics INCLUDING DEFAULTS
);
ALTER TABLE forecast_horizon_metrics_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_forecast_horizon_metrics_archive_run
    ON forecast_horizon_metrics_archive(run_id, archived_at DESC);

-- signal_quality_metrics
CREATE TABLE IF NOT EXISTS signal_quality_metrics_archive (
    LIKE signal_quality_metrics INCLUDING DEFAULTS
);
ALTER TABLE signal_quality_metrics_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_signal_quality_metrics_archive_at
    ON signal_quality_metrics_archive(archived_at DESC);

-- run_model_versions
CREATE TABLE IF NOT EXISTS run_model_versions_archive (
    LIKE run_model_versions INCLUDING DEFAULTS
);
ALTER TABLE run_model_versions_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_run_model_versions_archive_at
    ON run_model_versions_archive(archived_at DESC);

-- shadow_evaluations
CREATE TABLE IF NOT EXISTS shadow_evaluations_archive (
    LIKE shadow_evaluations INCLUDING DEFAULTS
);
ALTER TABLE shadow_evaluations_archive
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_archive_at
    ON shadow_evaluations_archive(archived_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2.  Copy live data into archive tables
--     (deepest children first so nothing is lost before CASCADE fires)
-- ─────────────────────────────────────────────────────────────────────────────

-- prediction_outcomes  (archive table exists from migration 004)
INSERT INTO prediction_outcomes_archive
SELECT *, now() AS archived_at
FROM   prediction_outcomes
ON CONFLICT (id) DO NOTHING;

-- forecast_candles
INSERT INTO forecast_candles_archive
SELECT *, now() AS archived_at
FROM   forecast_candles;

-- run_model_versions
INSERT INTO run_model_versions_archive
SELECT *, now() AS archived_at
FROM   run_model_versions;

-- shadow_evaluations
INSERT INTO shadow_evaluations_archive
SELECT *, now() AS archived_at
FROM   shadow_evaluations;

-- signal_shadow_predictions
INSERT INTO signal_shadow_predictions_archive
SELECT *, now() AS archived_at
FROM   signal_shadow_predictions;

-- prediction_run_quality
INSERT INTO prediction_run_quality_archive
SELECT *, now() AS archived_at
FROM   prediction_run_quality;

-- forecast_horizon_metrics
INSERT INTO forecast_horizon_metrics_archive
SELECT *, now() AS archived_at
FROM   forecast_horizon_metrics;

-- signal_quality_metrics
INSERT INTO signal_quality_metrics_archive
SELECT *, now() AS archived_at
FROM   signal_quality_metrics;

-- signals
INSERT INTO signals_archive
SELECT *, now() AS archived_at
FROM   signals;

-- prediction_runs (parent — archive last)
INSERT INTO prediction_runs_archive
SELECT *, now() AS archived_at
FROM   prediction_runs;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3.  Wipe live data
--     CASCADE from prediction_runs clears all child tables automatically.
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM prediction_runs;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4.  Record migration
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO schema_migrations(version)
VALUES ('012_archive_signals_fresh_start')
ON CONFLICT (version) DO NOTHING;

COMMIT;
