from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from db import connect


ACTIONABLE_FINAL_SIGNALS = {
    "LONG",
    "SHORT",
    "STRONG_LONG",
    "STRONG_SHORT",
    "WEAK_LONG",
    "WEAK_SHORT",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate calibration report for signal validation runs.")
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--output", default="output/signal_validation_report.json")
    return parser.parse_args()


def _timestamped_output_path(output_hint: str) -> Path:
    hint = Path(output_hint)
    parent = hint.parent if hint.parent != Path("") else Path("output")
    parent.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
    stem = hint.stem or "signal_validation_report"
    return parent / f"{stem}_{stamp}.json"


def _safe_pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return (num / den) * 100.0


def _load_rows(dsn: str | None) -> dict[str, Any]:
    with connect(dsn) as conn:
        validations = conn.execute(
            """
            SELECT
                svr.run_id,
                svr.final_signal,
                svr.candidate_signal,
                svr.blocked,
                svr.block_reason,
                svr.total_score,
                svr.forecast_return_pct,
                s.status AS signal_outcome_status
            FROM signal_validation_runs svr
            LEFT JOIN signals s ON s.run_id = svr.run_id
            ORDER BY svr.created_at ASC
            """
        ).fetchall()

        timeframe_rows = conn.execute(
            """
            SELECT
                run_id,
                timeframe,
                confirms_candidate,
                trend
            FROM signal_timeframe_validations
            ORDER BY run_id, timeframe
            """
        ).fetchall()

        primary_horizon = conn.execute(
            """
            SELECT
                run_id,
                realized_move_pct,
                status
            FROM forecast_horizon_metrics
            WHERE horizon_index = 1
            ORDER BY run_id
            """
        ).fetchall()

    return {
        "validations": [dict(row) for row in validations],
        "timeframes": [dict(row) for row in timeframe_rows],
        "primary_horizon": [dict(row) for row in primary_horizon],
    }


def _build_report(rows: dict[str, Any]) -> dict[str, Any]:
    validations = rows["validations"]
    timeframe_rows = rows["timeframes"]
    primary_horizon_rows = rows["primary_horizon"]

    total_runs = len(validations)
    final_distribution = Counter(str(row.get("final_signal") or "UNKNOWN") for row in validations)

    blocked_reasons = Counter(
        str(row.get("block_reason") or "UNKNOWN")
        for row in validations
        if bool(row.get("blocked"))
    )

    by_signal: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0, "pending": 0})
    score_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0, "pending": 0})

    actionable = 0
    actionable_losses = 0
    hold_or_blocked = 0

    for row in validations:
        final_signal = str(row.get("final_signal") or "UNKNOWN")
        outcome = str(row.get("signal_outcome_status") or "PENDING").upper()
        score = float(row.get("total_score") or 0.0)

        if final_signal in {"HOLD", "BLOCKED", "VALIDATION_UNAVAILABLE", "WATCH"}:
            hold_or_blocked += 1
        if final_signal in ACTIONABLE_FINAL_SIGNALS:
            actionable += 1
            if outcome == "LOSS":
                actionable_losses += 1

        bucket = "<50"
        if score >= 85:
            bucket = "85-100"
        elif score >= 70:
            bucket = "70-84"
        elif score >= 60:
            bucket = "60-69"
        elif score >= 50:
            bucket = "50-59"

        if outcome == "WIN":
            by_signal[final_signal]["wins"] += 1
            score_buckets[bucket]["wins"] += 1
        elif outcome == "LOSS":
            by_signal[final_signal]["losses"] += 1
            score_buckets[bucket]["losses"] += 1
        else:
            by_signal[final_signal]["pending"] += 1
            score_buckets[bucket]["pending"] += 1

    timeframe_by_run: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in timeframe_rows:
        timeframe_by_run[str(row["run_id"])][str(row["timeframe"])]= {
            "confirms": bool(row.get("confirms_candidate")),
            "trend": str(row.get("trend") or "NEUTRAL"),
        }

    agreement_combo_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "losses": 0, "pending": 0})
    hour_stats = {
        "confirms": {"wins": 0, "losses": 0, "pending": 0},
        "opposes": {"wins": 0, "losses": 0, "pending": 0},
        "neutral_or_missing": {"wins": 0, "losses": 0, "pending": 0},
    }

    for row in validations:
        run_id = str(row["run_id"])
        outcome = str(row.get("signal_outcome_status") or "PENDING").upper()
        tf = timeframe_by_run.get(run_id, {})

        combo = [
            f"15:{'Y' if tf.get('MINUTE_15', {}).get('confirms') else 'N'}",
            f"30:{'Y' if tf.get('MINUTE_30', {}).get('confirms') else 'N'}",
            f"60:{'Y' if tf.get('HOUR', {}).get('confirms') else 'N'}",
            f"240:{'Y' if tf.get('HOUR_4', {}).get('confirms') else 'N'}",
        ]
        combo_key = "|".join(combo)

        if outcome == "WIN":
            agreement_combo_stats[combo_key]["wins"] += 1
        elif outcome == "LOSS":
            agreement_combo_stats[combo_key]["losses"] += 1
        else:
            agreement_combo_stats[combo_key]["pending"] += 1

        hour = tf.get("HOUR")
        bucket = "neutral_or_missing"
        if hour is not None:
            bucket = "confirms" if bool(hour.get("confirms")) else "opposes"

        if outcome == "WIN":
            hour_stats[bucket]["wins"] += 1
        elif outcome == "LOSS":
            hour_stats[bucket]["losses"] += 1
        else:
            hour_stats[bucket]["pending"] += 1

    actual_move_by_run = {
        str(row["run_id"]): float(row["realized_move_pct"])
        for row in primary_horizon_rows
        if row.get("realized_move_pct") is not None
    }

    forecast_returns = [float(row["forecast_return_pct"]) for row in validations if row.get("forecast_return_pct") is not None]
    actual_returns = [value for value in actual_move_by_run.values()]

    threshold_candidates = [50.0, 60.0, 70.0, 85.0]
    threshold_stats = []
    for threshold in threshold_candidates:
        rows_at_threshold = [
            row
            for row in validations
            if float(row.get("total_score") or 0.0) >= threshold
            and str(row.get("final_signal") or "") in ACTIONABLE_FINAL_SIGNALS
            and str(row.get("signal_outcome_status") or "PENDING").upper() in {"WIN", "LOSS"}
        ]
        wins = sum(1 for row in rows_at_threshold if str(row.get("signal_outcome_status")).upper() == "WIN")
        losses = sum(1 for row in rows_at_threshold if str(row.get("signal_outcome_status")).upper() == "LOSS")
        threshold_stats.append(
            {
                "threshold": threshold,
                "samples": len(rows_at_threshold),
                "wins": wins,
                "losses": losses,
                "win_rate_pct": _safe_pct(wins, wins + losses),
            }
        )

    ranked = sorted(
        threshold_stats,
        key=lambda row: (
            row["win_rate_pct"] if row["win_rate_pct"] is not None else -1.0,
            row["samples"],
        ),
        reverse=True,
    )
    best_threshold = ranked[0] if ranked else None

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "total_validation_runs": total_runs,
        "final_signal_distribution": dict(final_distribution),
        "blocked_count_by_reason": dict(blocked_reasons),
        "win_rate_by_final_signal": {
            signal: {
                **counts,
                "win_rate_pct": _safe_pct(counts["wins"], counts["wins"] + counts["losses"]),
            }
            for signal, counts in by_signal.items()
        },
        "win_rate_by_score_bucket": {
            bucket: {
                **counts,
                "win_rate_pct": _safe_pct(counts["wins"], counts["wins"] + counts["losses"]),
            }
            for bucket, counts in score_buckets.items()
        },
        "win_rate_by_higher_timeframe_agreement_combination": {
            key: {
                **counts,
                "win_rate_pct": _safe_pct(counts["wins"], counts["wins"] + counts["losses"]),
            }
            for key, counts in agreement_combo_stats.items()
        },
        "win_rate_hour_confirms_vs_opposes": {
            key: {
                **counts,
                "win_rate_pct": _safe_pct(counts["wins"], counts["wins"] + counts["losses"]),
            }
            for key, counts in hour_stats.items()
        },
        "average_forecast_return_pct": None if not forecast_returns else float(sum(forecast_returns) / len(forecast_returns)),
        "average_actual_return_pct": None if not actual_returns else float(sum(actual_returns) / len(actual_returns)),
        "false_positive_rate_pct": _safe_pct(actionable_losses, actionable),
        "hold_blocked_statistics": {
            "hold_or_blocked_count": hold_or_blocked,
            "hold_or_blocked_rate_pct": _safe_pct(hold_or_blocked, total_runs),
        },
        "score_threshold_evaluation": threshold_stats,
        "best_performing_score_threshold_suggestion": best_threshold,
        "warning": "Threshold changes must not be auto-applied without operator approval.",
    }


def main() -> None:
    args = parse_args()
    rows = _load_rows(args.postgres_dsn)
    report = _build_report(rows)

    output_path = _timestamped_output_path(args.output)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Keep the requested output path as a convenience alias for operators.
    requested = Path(args.output)
    requested.parent.mkdir(parents=True, exist_ok=True)
    requested.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps({"ok": True, "output": str(output_path)}, indent=2))


if __name__ == "__main__":
    main()
