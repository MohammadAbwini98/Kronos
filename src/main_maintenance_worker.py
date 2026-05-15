from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from capital_rest_client import CapitalRestClient
from config import DEFAULT_INSTRUMENT_SYMBOL, configure_logging, load_settings
from historical_backfill import ensure_historical_candles
from rate_limit_state import RateLimitCooldownError
from service_runtime import write_heartbeat

from db import connect

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive old validated outcomes and create nightly artifact backups.")
    parser.add_argument("--env", default=os.getenv("CAPITAL_ENV", "demo"), choices=["demo", "live"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("MAINTENANCE_POLL_SECONDS", "60")))
    parser.add_argument("--archive-retention-days", type=int, default=int(os.getenv("OUTCOME_ARCHIVE_RETENTION_DAYS", "30")))
    parser.add_argument("--archive-interval-minutes", type=int, default=int(os.getenv("OUTCOME_ARCHIVE_INTERVAL_MINUTES", "60")))
    parser.add_argument("--backup-hour-utc", type=int, default=int(os.getenv("NIGHTLY_BACKUP_HOUR_UTC", "2")))
    parser.add_argument("--backup-retention-days", type=int, default=int(os.getenv("BACKUP_RETENTION_DAYS", "14")))
    parser.add_argument("--market", default=os.getenv("CAPITAL_DEFAULT_MARKET_SEARCH", os.getenv("TRADING_PROVIDER_SYMBOL", DEFAULT_INSTRUMENT_SYMBOL)))
    parser.add_argument("--epic", default=os.getenv("CAPITAL_DEFAULT_EPIC") or None)
    parser.add_argument("--symbol", default=os.getenv("SIGNAL_SYMBOL", os.getenv("TRADING_PROVIDER_SYMBOL", DEFAULT_INSTRUMENT_SYMBOL)))
    parser.add_argument("--resolution", default=os.getenv("HISTORICAL_BACKFILL_RESOLUTION", "MINUTE_5"))
    parser.add_argument("--price-side", default=os.getenv("CAPITAL_DEFAULT_PRICE_SIDE", "mid"), choices=["bid", "ask", "mid"])
    parser.add_argument("--historical-backfill-days", type=int, default=int(os.getenv("HISTORICAL_BACKFILL_DAYS", "35")))
    parser.add_argument("--historical-backfill-interval-minutes", type=int, default=int(os.getenv("HISTORICAL_BACKFILL_INTERVAL_MINUTES", "5")))
    parser.add_argument("--historical-backfill-chunk-points", type=int, default=int(os.getenv("HISTORICAL_BACKFILL_CHUNK_POINTS", "900")))
    parser.add_argument("--disable-historical-backfill", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _heartbeat(status: str, details: dict[str, Any], dsn: str | None) -> None:
    try:
        write_heartbeat("maintenance_worker", status, details, dsn)
    except Exception:  # noqa: BLE001
        LOGGER.debug("Unable to write maintenance heartbeat", exc_info=True)


def _archive_validated_outcomes(*, retention_days: int, dsn: str | None) -> int:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            WITH moved AS (
                DELETE FROM prediction_outcomes o
                USING prediction_runs r
                WHERE o.run_id = r.run_id
                  AND r.run_status = 'VALIDATED'
                  AND r.generated_at_utc < (now() - make_interval(days => %s))
                RETURNING
                    o.id,
                    o.run_id,
                    o.forecast_candle_id,
                    o.actual_candle_id,
                    o.forecast_timestamp_utc,
                    o.actual_timestamp_utc,
                    o.predicted_direction,
                    o.actual_direction,
                    o.forecast_close,
                    o.actual_close,
                    o.close_error,
                    o.close_error_pct,
                    o.status,
                    o.validated_at_utc,
                    o.created_at,
                    o.updated_at
            )
            INSERT INTO prediction_outcomes_archive (
                id,
                run_id,
                forecast_candle_id,
                actual_candle_id,
                forecast_timestamp_utc,
                actual_timestamp_utc,
                predicted_direction,
                actual_direction,
                forecast_close,
                actual_close,
                close_error,
                close_error_pct,
                status,
                validated_at_utc,
                created_at,
                updated_at,
                archived_at
            )
            SELECT
                id,
                run_id,
                forecast_candle_id,
                actual_candle_id,
                forecast_timestamp_utc,
                actual_timestamp_utc,
                predicted_direction,
                actual_direction,
                forecast_close,
                actual_close,
                close_error,
                close_error_pct,
                status,
                validated_at_utc,
                created_at,
                updated_at,
                now()
            FROM moved
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (retention_days,),
        ).fetchall()
    return len(rows)


def _state_path(output_dir: Path) -> Path:
    return output_dir / "maintenance_worker_state.json"


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _backup_files(*, output_dir: Path, backup_dir: Path) -> int:
    patterns = [
        "forecast_metadata_*.json",
        "forecast_quality_report_*.json",
        "kronos_forecast_*.csv",
        "kronos_input_*.csv",
        "actual_for_forecast_*.csv",
        "experiment_comparison_report.json",
        "cumulative_forecast_quality_report.json",
    ]
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pattern in patterns:
        for source in output_dir.glob(pattern):
            if not source.is_file():
                continue
            target = backup_dir / source.name
            shutil.copy2(source, target)
            copied += 1
    return copied


def _cleanup_old_backups(*, backups_root: Path, retention_days: int) -> int:
    if not backups_root.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    removed = 0
    for child in backups_root.iterdir():
        if not child.is_dir():
            continue
        try:
            folder_date = datetime.strptime(child.name, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def _should_backup_today(*, now_utc: datetime, backup_hour_utc: int, state: dict[str, Any]) -> bool:
    last_date = str(state.get("last_backup_date") or "")
    today = now_utc.date().isoformat()
    return now_utc.hour >= backup_hour_utc and last_date != today


def _resolve_backfill_market(settings: Any, args: argparse.Namespace) -> tuple[CapitalRestClient, dict[str, Any]]:
    client = CapitalRestClient(settings)
    client.authenticate()
    selected = client.resolve_market(args.market, args.epic, streaming=False)
    if not selected or not selected.get("epic"):
        raise RuntimeError(f"Historical backfill market was not resolved for market={args.market!r} epic={args.epic!r}")
    client.save_market_details(selected["epic"])
    return client, selected


def main() -> None:
    args = parse_args()
    configure_logging(service_name="maintenance_worker")
    settings = load_settings(args.env)
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    backups_root = output_dir / "backups"
    state_file = _state_path(output_dir)

    archive_interval_seconds = max(60, args.archive_interval_minutes * 60)
    backfill_interval_seconds = max(60, args.historical_backfill_interval_minutes * 60)
    last_archive_at = 0.0
    last_backfill_at = 0.0
    backfill_client: CapitalRestClient | None = None
    backfill_selected: dict[str, Any] | None = None

    while True:
        now_utc = datetime.now(timezone.utc)
        status = "OK"
        details: dict[str, Any] = {
            "checked_at_utc": now_utc.isoformat(),
            "archive_retention_days": args.archive_retention_days,
            "backup_hour_utc": args.backup_hour_utc,
            "historical_backfill_enabled": not args.disable_historical_backfill,
            "historical_backfill_days": args.historical_backfill_days,
            "historical_backfill_resolution": args.resolution,
        }
        try:
            if not args.disable_historical_backfill and ((time.time() - last_backfill_at) >= backfill_interval_seconds or args.once):
                if str(args.resolution).upper() != "MINUTE_5":
                    raise ValueError("Maintenance historical backfill is pinned to MINUTE_5.")
                if backfill_client is None or backfill_selected is None:
                    backfill_client, backfill_selected = _resolve_backfill_market(settings, args)
                summary = ensure_historical_candles(
                    client=backfill_client,
                    selected_market=backfill_selected,
                    symbol=args.symbol,
                    resolution=args.resolution,
                    price_side=args.price_side,
                    days=args.historical_backfill_days,
                    chunk_points=args.historical_backfill_chunk_points,
                    source="historical",
                    dsn=args.postgres_dsn,
                )
                details["historical_backfill"] = summary.to_dict()
                _write_state(
                    output_dir / "historical_5m_backfill_status.json",
                    {
                        "enabled": True,
                        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                        **summary.to_dict(),
                    },
                )
                last_backfill_at = time.time()

            if (time.time() - last_archive_at) >= archive_interval_seconds or args.once:
                archived = _archive_validated_outcomes(retention_days=args.archive_retention_days, dsn=args.postgres_dsn)
                details["archived_outcomes"] = int(archived)
                last_archive_at = time.time()

            state = _read_state(state_file)
            if _should_backup_today(now_utc=now_utc, backup_hour_utc=max(0, min(23, args.backup_hour_utc)), state=state) or args.once:
                folder_name = now_utc.strftime("%Y%m%d")
                backup_dir = backups_root / folder_name
                copied = _backup_files(output_dir=output_dir, backup_dir=backup_dir)
                removed_dirs = _cleanup_old_backups(backups_root=backups_root, retention_days=args.backup_retention_days)
                state["last_backup_date"] = now_utc.date().isoformat()
                state["last_backup_folder"] = folder_name
                state["last_backup_copied_files"] = copied
                state["last_backup_utc"] = now_utc.isoformat()
                _write_state(state_file, state)
                details["backup_folder"] = folder_name
                details["backup_copied_files"] = int(copied)
                details["backup_old_dirs_removed"] = int(removed_dirs)
        except Exception as exc:  # noqa: BLE001
            status = "COOLDOWN" if isinstance(exc, RateLimitCooldownError) else "ERROR"
            details["error"] = str(exc)
            details["state"] = "cooldown" if status == "COOLDOWN" else "error"
            LOGGER.exception("Maintenance worker cycle failed")

        _heartbeat(status, details, args.postgres_dsn)
        if args.once:
            return
        time.sleep(max(30, args.poll_seconds))


if __name__ == "__main__":
    main()
