from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from dataset_snapshots import dataset_windows_overlap, load_dataset_snapshot
from db import connect
from forecast_scoring import DEFAULT_SCORING_VERSION, signal_status_from_counts


def _candidate_shadow_metrics(model_version_id: str, dsn: str | None) -> dict[str, Any]:
    """
    Aggregate per-candidate metrics from shadow_evaluations.horizon_metrics.

    Returns wins/losses/MAPE and per-horizon direction accuracy keyed by horizon_index.
    Returns an empty/None dict when no shadow evaluations exist for this candidate.
    """
    with connect(dsn) as conn:
        shadow_rows = conn.execute(
            """
            SELECT shadow_wins, shadow_losses, horizon_metrics
            FROM shadow_evaluations
            WHERE shadow_model_version_id = %s
            """,
            (model_version_id,),
        ).fetchall()
    total_wins = 0
    total_losses = 0
    mape_sum = 0.0
    mape_count = 0
    horizon_wins: dict[int, int] = {}
    horizon_samples: dict[int, int] = {}
    for row in shadow_rows:
        total_wins += int(row.get("shadow_wins") or 0)
        total_losses += int(row.get("shadow_losses") or 0)
        hm = row.get("horizon_metrics") or []
        hm_rows: list[Any] = list(hm) if isinstance(hm, list) else list(hm.values()) if isinstance(hm, dict) else []
        for hrow in hm_rows:
            if not isinstance(hrow, dict):
                continue
            hidx = int(hrow.get("horizon_index") or 0)
            status = str(hrow.get("status") or "PENDING")
            if status in ("WIN", "LOSS"):
                horizon_samples[hidx] = horizon_samples.get(hidx, 0) + 1
                if status == "WIN":
                    horizon_wins[hidx] = horizon_wins.get(hidx, 0) + 1
                err_pct = hrow.get("close_error_pct")
                if err_pct is not None:
                    mape_sum += abs(float(err_pct))
                    mape_count += 1
    samples = total_wins + total_losses
    return {
        "samples": samples,
        "wins": total_wins,
        "losses": total_losses,
        "direction_accuracy_pct": None if samples == 0 else (total_wins / samples) * 100.0,
        "mape_pct": None if mape_count == 0 else mape_sum / mape_count,
        "per_horizon_accuracy": {
            hidx: (horizon_wins.get(hidx, 0) / n * 100.0)
            for hidx, n in horizon_samples.items()
            if n > 0
        },
    }


def _candidate_baseline_beat_rate(model_version_id: str, dsn: str | None) -> float | None:
    """
    Compute the fraction of walk-forward windows where the candidate beat the primary
    baseline, using results stored by run_walk_forward_experiment.

    Returns None when no walk-forward results exist for this candidate.
    """
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT
                (wfr.metrics->'candidate'->>'direction_accuracy_pct')::float AS cand_acc,
                (wfr.metrics->>'direction_accuracy_pct')::float AS base_acc
            FROM walk_forward_results wfr
            JOIN walk_forward_experiments wfe ON wfe.experiment_id = wfr.experiment_id
            WHERE wfe.model_version_id = %s
              AND (wfr.metrics->'candidate') IS NOT NULL
              AND (wfr.metrics->'candidate'->>'direction_accuracy_pct') IS NOT NULL
            """,
            (model_version_id,),
        ).fetchall()
    if not rows:
        return None
    beats = sum(
        1 for r in rows
        if r.get("cand_acc") is not None and r.get("base_acc") is not None
        and float(r["cand_acc"]) > float(r["base_acc"])
    )
    return (beats / len(rows)) * 100.0


def model_version_id_for_path(model_name: str, model_path: str | None) -> str:
    source = f"{model_name}:{model_path or ''}"
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    label = "".join(ch.lower() if ch.isalnum() else "-" for ch in model_name).strip("-") or "model"
    return f"{label}-{digest}"


def artifact_manifest(model_path: str | None, tokenizer_path: str | None = None) -> dict[str, Any]:
    manifest: dict[str, Any] = {"model_path": model_path, "tokenizer_path": tokenizer_path, "complete": False}
    if not model_path:
        return manifest
    path = Path(model_path)
    required = ["config.json", "model.safetensors"]
    files = {name: (path / name).exists() for name in required}
    manifest["required_files"] = files
    manifest["complete"] = all(files.values())
    return manifest


def register_model_version(
    *,
    model_version_id: str | None = None,
    model_name: str,
    model_path: str,
    tokenizer_path: str | None = None,
    symbol: str = "ETHUSD",
    resolution: str = "MINUTE_5",
    lookback: int = 512,
    pred_len: int = 12,
    feature_set_id: str | None = "raw-ohlcv-v1",
    promotion_status: str = "pending_review",
    promotion_reason: str | None = None,
    training_dataset_id: str | None = None,
    validation_dataset_id: str | None = None,
    base_model_version_id: str | None = None,
    approval_metrics: dict[str, Any] | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    version_id = model_version_id or model_version_id_for_path(model_name, model_path)
    manifest = artifact_manifest(model_path, tokenizer_path)
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO model_versions(
                model_version_id, model_name, model_path, tokenizer_path, base_model_version_id,
                training_dataset_id, validation_dataset_id, symbol, resolution, feature_set_id,
                lookback, pred_len, promotion_status, promotion_reason, approval_metrics, artifact_manifest, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT(model_version_id) DO UPDATE SET
                model_name = EXCLUDED.model_name,
                model_path = EXCLUDED.model_path,
                tokenizer_path = EXCLUDED.tokenizer_path,
                training_dataset_id = COALESCE(EXCLUDED.training_dataset_id, model_versions.training_dataset_id),
                validation_dataset_id = COALESCE(EXCLUDED.validation_dataset_id, model_versions.validation_dataset_id),
                symbol = EXCLUDED.symbol,
                resolution = EXCLUDED.resolution,
                feature_set_id = EXCLUDED.feature_set_id,
                lookback = EXCLUDED.lookback,
                pred_len = EXCLUDED.pred_len,
                promotion_status = CASE
                    WHEN model_versions.promotion_status = 'promoted' THEN model_versions.promotion_status
                    ELSE EXCLUDED.promotion_status
                END,
                promotion_reason = COALESCE(EXCLUDED.promotion_reason, model_versions.promotion_reason),
                approval_metrics = model_versions.approval_metrics || EXCLUDED.approval_metrics,
                artifact_manifest = EXCLUDED.artifact_manifest,
                updated_at = now()
            """,
            (
                version_id,
                model_name,
                model_path,
                tokenizer_path,
                base_model_version_id,
                training_dataset_id,
                validation_dataset_id,
                symbol,
                resolution,
                feature_set_id,
                int(lookback),
                int(pred_len),
                promotion_status,
                promotion_reason,
                Jsonb(approval_metrics or {}),
                Jsonb(manifest),
            ),
        )
    return {"model_version_id": version_id, "artifact_manifest": manifest}


def associate_run_model_version(
    *,
    run_id: str,
    model_version_id: str,
    role: str,
    dsn: str | None = None,
) -> None:
    with connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO run_model_versions(run_id, model_version_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT(run_id) DO UPDATE SET
                model_version_id = EXCLUDED.model_version_id,
                role = EXCLUDED.role
            """,
            (run_id, model_version_id, role),
        )
        conn.execute(
            "UPDATE prediction_runs SET model_version_id = %s, updated_at = now() WHERE run_id = %s",
            (model_version_id, run_id),
        )


def list_model_versions(*, dsn: str | None = None, limit: int = 100) -> dict[str, Any]:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT model_version_id, model_name, model_path, tokenizer_path, symbol, resolution,
                   promotion_status, promotion_reason, approval_metrics, artifact_manifest,
                   training_dataset_id, validation_dataset_id, created_at, updated_at
            FROM model_versions
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return {"rows": [dict(row) for row in rows]}


def _active_metrics(*, symbol: str, resolution: str, dsn: str | None) -> dict[str, Any]:
    with connect(dsn) as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN o.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN o.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                AVG(ABS(o.close_error_pct)) FILTER (WHERE o.status IN ('WIN','LOSS'))::double precision AS mape_pct,
                SQRT(AVG((o.close_error * o.close_error)) FILTER (WHERE o.status IN ('WIN','LOSS')))::double precision AS rmse
            FROM prediction_runs r
            JOIN prediction_outcomes o ON o.run_id = r.run_id
            WHERE r.symbol = %s
              AND r.resolution = %s
              AND o.status IN ('WIN','LOSS')
            """,
            (symbol, resolution),
        ).fetchone()
    wins = int(row.get("wins") or 0) if row else 0
    losses = int(row.get("losses") or 0) if row else 0
    samples = wins + losses
    return {
        "model_version_id": None,
        "samples": samples,
        "wins": wins,
        "losses": losses,
        "direction_accuracy_pct": None if samples == 0 else (wins / samples) * 100.0,
        "mape_pct": row.get("mape_pct") if row else None,
        "rmse": row.get("rmse") if row else None,
    }


def _rate_from_wins_losses(wins: int, losses: int) -> float | None:
    samples = int(wins) + int(losses)
    if samples <= 0:
        return None
    return (int(wins) / samples) * 100.0


def model_performance(
    *,
    symbol: str = "ETHUSD",
    resolution: str = "MINUTE_5",
    model_version_id: str | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    active = _active_metrics(symbol=symbol, resolution=resolution, dsn=dsn)
    selected_shadow_model_version_id = model_version_id
    with connect(dsn) as conn:
        shadow_row = conn.execute(
            """
            SELECT
                shadow_model_version_id,
                COALESCE(SUM(shadow_wins), 0)::int AS wins,
                COALESCE(SUM(shadow_losses), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN disagreement THEN 1 ELSE 0 END), 0)::int AS disagreement_samples,
                COALESCE(SUM(CASE WHEN disagreement AND shadow_status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS shadow_wins_when_disagree,
                COALESCE(SUM(CASE WHEN disagreement AND active_status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS active_wins_when_disagree
            FROM shadow_evaluations
            WHERE symbol = %s
              AND resolution = %s
              AND (%s::text IS NULL OR shadow_model_version_id = %s::text)
            GROUP BY shadow_model_version_id
            ORDER BY MAX(generated_at_utc) DESC
            LIMIT 1
            """,
            (symbol, resolution, model_version_id, model_version_id),
        ).fetchone()
        if shadow_row and shadow_row.get("shadow_model_version_id"):
            selected_shadow_model_version_id = str(shadow_row.get("shadow_model_version_id"))
        status_active_all = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN s.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN s.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN s.status = 'PENDING' OR s.status IS NULL OR s.status = '' THEN 1 ELSE 0 END), 0)::int AS pending,
                COUNT(*)::int AS total
            FROM signals s
            JOIN prediction_runs r ON r.run_id = s.run_id
            WHERE r.symbol = %s
              AND r.resolution = %s
            """,
            (symbol, resolution),
        ).fetchone()
        status_active_shadow_runs = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN s.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN s.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN s.status = 'PENDING' OR s.status IS NULL OR s.status = '' THEN 1 ELSE 0 END), 0)::int AS pending,
                COUNT(*)::int AS total
            FROM signals s
            JOIN prediction_runs r ON r.run_id = s.run_id
            WHERE r.symbol = %s
              AND r.resolution = %s
              AND (%s::text IS NULL OR s.run_id IN (
                    SELECT se.active_run_id
                    FROM shadow_evaluations se
                    WHERE se.symbol = %s
                      AND se.resolution = %s
                      AND se.shadow_model_version_id = %s::text
              ))
            """,
            (
                symbol,
                resolution,
                selected_shadow_model_version_id,
                symbol,
                resolution,
                selected_shadow_model_version_id,
            ),
        ).fetchone()
        status_shadow = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN sp.status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                COALESCE(SUM(CASE WHEN sp.status = 'LOSS' THEN 1 ELSE 0 END), 0)::int AS losses,
                COALESCE(SUM(CASE WHEN sp.status = 'PENDING' OR sp.status IS NULL OR sp.status = '' THEN 1 ELSE 0 END), 0)::int AS pending,
                COUNT(*)::int AS total
            FROM signal_shadow_predictions sp
            JOIN prediction_runs r ON r.run_id = sp.active_run_id
            WHERE r.symbol = %s
              AND r.resolution = %s
              AND (%s::text IS NULL OR sp.shadow_model_version_id = %s::text)
            """,
            (symbol, resolution, selected_shadow_model_version_id, selected_shadow_model_version_id),
        ).fetchone()
        matched_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(active_wins), 0)::int AS active_wins,
                COALESCE(SUM(active_losses), 0)::int AS active_losses,
                COALESCE(SUM(shadow_wins), 0)::int AS shadow_wins,
                COALESCE(SUM(shadow_losses), 0)::int AS shadow_losses,
                COUNT(*)::int AS evaluation_rows,
                COALESCE(SUM(CASE WHEN disagreement THEN 1 ELSE 0 END), 0)::int AS disagreement_samples,
                COALESCE(SUM(CASE WHEN disagreement AND active_status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS active_wins_when_disagree,
                COALESCE(SUM(CASE WHEN disagreement AND shadow_status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS shadow_wins_when_disagree
            FROM shadow_evaluations
            WHERE symbol = %s
              AND resolution = %s
              AND (%s::text IS NULL OR shadow_model_version_id = %s::text)
            """,
            (symbol, resolution, selected_shadow_model_version_id, selected_shadow_model_version_id),
        ).fetchone()
        horizons = conn.execute(
            """
            SELECT
                horizon_index,
                COUNT(*) FILTER (WHERE status IN ('WIN','LOSS'))::int AS samples,
                COALESCE(SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END), 0)::int AS wins,
                AVG(ABS(close_error_pct)) FILTER (WHERE status IN ('WIN','LOSS'))::double precision AS mape_pct
            FROM forecast_horizon_metrics hm
            JOIN prediction_runs r ON r.run_id = hm.run_id
            WHERE r.symbol = %s AND r.resolution = %s
            GROUP BY horizon_index
            ORDER BY horizon_index
            LIMIT 96
            """,
            (symbol, resolution),
        ).fetchall()
        gate_rows = conn.execute(
            """
            SELECT pgr.gate_name, pgr.status, pgr.metric_value, pgr.threshold_value, pgr.details, pgr.evaluated_at
            FROM promotion_gate_results pgr
            WHERE (%s::text IS NULL OR pgr.model_version_id = %s::text)
            ORDER BY pgr.evaluated_at DESC, pgr.gate_name
            LIMIT 50
            """,
            (model_version_id, model_version_id),
        ).fetchall()
    shadow = {"model_version_id": model_version_id, "samples": 0, "wins": 0, "losses": 0, "direction_accuracy_pct": None, "lift_pct": None}
    disagreement = {"samples": 0, "shadow_wins_when_disagree": 0, "active_wins_when_disagree": 0}
    if shadow_row:
        wins = int(shadow_row.get("wins") or 0)
        losses = int(shadow_row.get("losses") or 0)
        samples = wins + losses
        accuracy = None if samples == 0 else (wins / samples) * 100.0
        active_accuracy = active.get("direction_accuracy_pct")
        shadow = {
            "model_version_id": shadow_row.get("shadow_model_version_id"),
            "samples": samples,
            "wins": wins,
            "losses": losses,
            "direction_accuracy_pct": accuracy,
            "lift_pct": None if accuracy is None or active_accuracy is None else accuracy - float(active_accuracy),
        }
        disagreement = {
            "samples": int(shadow_row.get("disagreement_samples") or 0),
            "shadow_wins_when_disagree": int(shadow_row.get("shadow_wins_when_disagree") or 0),
            "active_wins_when_disagree": int(shadow_row.get("active_wins_when_disagree") or 0),
        }
    horizon_payload = []
    for row in horizons:
        samples = int(row.get("samples") or 0)
        wins = int(row.get("wins") or 0)
        horizon_payload.append(
            {
                "horizon_index": int(row["horizon_index"]),
                "active_accuracy_pct": None if samples == 0 else (wins / samples) * 100.0,
                "shadow_accuracy_pct": None,
                "baseline_accuracy_pct": None,
                "samples": samples,
                "mape_pct": row.get("mape_pct"),
            }
        )
    active_status_all_wins = int(status_active_all.get("wins") or 0) if status_active_all else 0
    active_status_all_losses = int(status_active_all.get("losses") or 0) if status_active_all else 0
    active_status_all_pending = int(status_active_all.get("pending") or 0) if status_active_all else 0
    active_status_all_total = int(status_active_all.get("total") or 0) if status_active_all else 0

    active_status_shadow_wins = int(status_active_shadow_runs.get("wins") or 0) if status_active_shadow_runs else 0
    active_status_shadow_losses = int(status_active_shadow_runs.get("losses") or 0) if status_active_shadow_runs else 0
    active_status_shadow_pending = int(status_active_shadow_runs.get("pending") or 0) if status_active_shadow_runs else 0
    active_status_shadow_total = int(status_active_shadow_runs.get("total") or 0) if status_active_shadow_runs else 0

    shadow_status_wins = int(status_shadow.get("wins") or 0) if status_shadow else 0
    shadow_status_losses = int(status_shadow.get("losses") or 0) if status_shadow else 0
    shadow_status_pending = int(status_shadow.get("pending") or 0) if status_shadow else 0
    shadow_status_total = int(status_shadow.get("total") or 0) if status_shadow else 0

    matched_active_wins = int(matched_row.get("active_wins") or 0) if matched_row else 0
    matched_active_losses = int(matched_row.get("active_losses") or 0) if matched_row else 0
    matched_shadow_wins = int(matched_row.get("shadow_wins") or 0) if matched_row else 0
    matched_shadow_losses = int(matched_row.get("shadow_losses") or 0) if matched_row else 0
    matched_active_rate = _rate_from_wins_losses(matched_active_wins, matched_active_losses)
    matched_shadow_rate = _rate_from_wins_losses(matched_shadow_wins, matched_shadow_losses)

    return {
        "active_model": active,
        "shadow_model": shadow,
        "disagreement": disagreement,
        "horizons": horizon_payload,
        "comparison": {
            "shadow_model_version_id": selected_shadow_model_version_id,
            "matched_runs": {
                "evaluation_rows": int(matched_row.get("evaluation_rows") or 0) if matched_row else 0,
                "active": {
                    "wins": matched_active_wins,
                    "losses": matched_active_losses,
                    "samples": matched_active_wins + matched_active_losses,
                    "win_rate_pct": matched_active_rate,
                },
                "shadow": {
                    "wins": matched_shadow_wins,
                    "losses": matched_shadow_losses,
                    "samples": matched_shadow_wins + matched_shadow_losses,
                    "win_rate_pct": matched_shadow_rate,
                },
                "shadow_minus_active_pct": None if matched_active_rate is None or matched_shadow_rate is None else matched_shadow_rate - matched_active_rate,
                "disagreement": {
                    "samples": int(matched_row.get("disagreement_samples") or 0) if matched_row else 0,
                    "active_wins_when_disagree": int(matched_row.get("active_wins_when_disagree") or 0) if matched_row else 0,
                    "shadow_wins_when_disagree": int(matched_row.get("shadow_wins_when_disagree") or 0) if matched_row else 0,
                },
            },
            "signal_status": {
                "active_all_runs": {
                    "wins": active_status_all_wins,
                    "losses": active_status_all_losses,
                    "pending": active_status_all_pending,
                    "total": active_status_all_total,
                    "win_rate_pct": _rate_from_wins_losses(active_status_all_wins, active_status_all_losses),
                },
                "active_shadow_covered_runs": {
                    "wins": active_status_shadow_wins,
                    "losses": active_status_shadow_losses,
                    "pending": active_status_shadow_pending,
                    "total": active_status_shadow_total,
                    "win_rate_pct": _rate_from_wins_losses(active_status_shadow_wins, active_status_shadow_losses),
                },
                "shadow_runs": {
                    "wins": shadow_status_wins,
                    "losses": shadow_status_losses,
                    "pending": shadow_status_pending,
                    "total": shadow_status_total,
                    "win_rate_pct": _rate_from_wins_losses(shadow_status_wins, shadow_status_losses),
                },
            },
        },
        "promotion_gates": [dict(row) for row in gate_rows],
    }


def _gate(name: str, metric: float | int | None, threshold: float | int | None, *, comparator: str = ">=", details: dict[str, Any] | None = None) -> dict[str, Any]:
    if metric is None or threshold is None:
        status = "FAIL"
    elif comparator == ">=":
        status = "PASS" if float(metric) >= float(threshold) else "FAIL"
    elif comparator == "<=":
        status = "PASS" if float(metric) <= float(threshold) else "FAIL"
    else:
        status = "FAIL"
    return {
        "gate_name": name,
        "status": status,
        "metric_value": metric,
        "threshold_value": threshold,
        "details": details or {},
    }


def evaluate_promotion(
    *,
    model_version_id: str,
    scoring_version: str = DEFAULT_SCORING_VERSION,
    min_shadow_samples: int = 100,
    min_direction_accuracy_pct: float = 55.0,
    min_actionable_precision_pct: float = 55.0,
    min_lift_pct: float = 0.0,
    max_mape_regression_pct: float = 5.0,
    required_horizons: list[int] | None = None,
    min_quality_coverage_pct: float = 80.0,
    min_baseline_beat_rate_pct: float = 50.0,
    dsn: str | None = None,
) -> dict[str, Any]:
    with connect(dsn) as conn:
        model = conn.execute("SELECT * FROM model_versions WHERE model_version_id = %s", (model_version_id,)).fetchone()
    if not model:
        raise ValueError(f"Model version not found: {model_version_id}")
    performance = model_performance(
        symbol=model["symbol"],
        resolution=model["resolution"],
        model_version_id=model_version_id,
        dsn=dsn,
    )
    shadow = performance["shadow_model"]
    active = performance["active_model"]
    # Compute candidate-specific metrics from shadow evaluations and walk-forward results.
    # Using incumbent (active) metrics for promotion gates is a confound: incumbent
    # performance says nothing about the candidate's intrinsic quality.
    candidate_shadow = _candidate_shadow_metrics(model_version_id, dsn)
    candidate_baseline_beat_rate = _candidate_baseline_beat_rate(model_version_id, dsn)
    insufficient_evidence = {"reason": "insufficient_candidate_evidence"}
    gates: list[dict[str, Any]] = []
    gates.append(_gate("min_shadow_samples", candidate_shadow.get("samples"), min_shadow_samples))
    gates.append(_gate("min_direction_accuracy", candidate_shadow.get("direction_accuracy_pct"), min_direction_accuracy_pct))
    gates.append(_gate("lift_over_active", shadow.get("lift_pct"), min_lift_pct))
    gates.append(_gate("actionable_precision", candidate_shadow.get("direction_accuracy_pct"), min_actionable_precision_pct))
    # MAPE regression: compare candidate shadow MAPE to active incumbent MAPE.
    active_mape = active.get("mape_pct")
    candidate_mape = candidate_shadow.get("mape_pct")
    if candidate_mape is None or active_mape is None:
        mape_regression = None
    else:
        mape_regression = float(candidate_mape) - float(active_mape)
    gates.append(_gate("mape_regression", mape_regression, max_mape_regression_pct, comparator="<=", details={"active_mape_pct": active_mape, "candidate_mape_pct": candidate_mape}))
    # Horizon performance gate: use candidate shadow per-horizon accuracy, not incumbent.
    horizon_details = performance.get("horizons") or []
    candidate_per_horizon = candidate_shadow.get("per_horizon_accuracy") or {}
    required = required_horizons or []
    if required:
        if not candidate_per_horizon:
            gates.append(_gate("horizon_performance", None, len(required), details={**insufficient_evidence, "required_horizons": required}))
        else:
            passing = [
                h for h in required
                if candidate_per_horizon.get(h) is not None
                and float(candidate_per_horizon[h]) >= min_direction_accuracy_pct
            ]
            gates.append(_gate("horizon_performance", len(passing), len(required), details={"required_horizons": required, "candidate_per_horizon": candidate_per_horizon}))
    else:
        gates.append({"gate_name": "horizon_performance", "status": "PASS", "metric_value": None, "threshold_value": None, "details": {"required_horizons": []}})
    # Baseline beat rate from walk-forward candidate evaluation.
    if candidate_baseline_beat_rate is None:
        gates.append(_gate("baseline_beat_rate", None, min_baseline_beat_rate_pct, details=insufficient_evidence))
    else:
        gates.append(_gate("baseline_beat_rate", candidate_baseline_beat_rate, min_baseline_beat_rate_pct))
    with connect(dsn) as conn:
        quality_row = conn.execute(
            """
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE q.quality_grade IN ('A','B'))::int AS good
            FROM shadow_evaluations se
            LEFT JOIN prediction_run_quality q ON q.run_id = se.active_run_id
            WHERE se.shadow_model_version_id = %s
            """,
            (model_version_id,),
        ).fetchone()
    total = int(quality_row.get("total") or 0) if quality_row else 0
    good = int(quality_row.get("good") or 0) if quality_row else 0
    coverage = None if total == 0 else (good / total) * 100.0
    gates.append(_gate("data_quality_coverage", coverage, min_quality_coverage_pct))
    if model.get("training_dataset_id") and model.get("validation_dataset_id"):
        train = load_dataset_snapshot(model["training_dataset_id"], dsn=dsn)
        validation = load_dataset_snapshot(model["validation_dataset_id"], dsn=dsn)
        overlap = bool(train and validation and dataset_windows_overlap(train, validation))
        gates.append(
            {
                "gate_name": "dataset_overlap",
                "status": "FAIL" if overlap else "PASS",
                "metric_value": 1 if overlap else 0,
                "threshold_value": 0,
                "details": {"training_dataset_id": model["training_dataset_id"], "validation_dataset_id": model["validation_dataset_id"]},
            }
        )
    final_status = "approved" if all(gate["status"] == "PASS" for gate in gates) else "rejected"
    reason = "promotion_criteria_met" if final_status == "approved" else "promotion_gates_failed:" + ",".join(g["gate_name"] for g in gates if g["status"] != "PASS")
    metrics = {
        "active": active,
        "shadow": shadow,
        "disagreement": performance["disagreement"],
        "scoring_version": scoring_version,
    }
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            for gate in gates:
                cur.execute(
                    """
                    INSERT INTO promotion_gate_results(model_version_id, gate_name, status, metric_value, threshold_value, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        model_version_id,
                        gate["gate_name"],
                        gate["status"],
                        gate.get("metric_value"),
                        gate.get("threshold_value"),
                        Jsonb(gate.get("details") or {}),
                    ),
                )
        conn.execute(
            """
            UPDATE model_versions
            SET promotion_status = %s,
                promotion_reason = %s,
                approval_metrics = %s,
                updated_at = now()
            WHERE model_version_id = %s
            """,
            (final_status, reason, Jsonb(metrics), model_version_id),
        )
    return {
        "model_version_id": model_version_id,
        "promotion_status": final_status,
        "promotion_reason": reason,
        "gates": gates,
    }


def shadow_status_from_counts(wins: int, losses: int) -> str:
    return signal_status_from_counts(wins, losses)
