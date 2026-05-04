from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import time

from config import configure_logging
from forecast_quality_validator import recommendation_for_status, validate_forecast_quality
from forecast_runs_index import append_forecast_run_index
from logging_utils import log_event, new_correlation_id
from prediction_store import run_id_from_metadata_path, update_predictions_with_actuals


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare saved Kronos forecast candles against actual candles.")
    parser.add_argument("--forecast", required=True, help="Kronos forecast CSV.")
    parser.add_argument("--actual", required=True, help="Actual Kronos-compatible OHLC CSV.")
    parser.add_argument("--resolution", required=True, help="Resolution such as MINUTE_5.")
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"])
    parser.add_argument("--epic", default=None, help="Epic for timestamped report filename.")
    parser.add_argument("--output", default=None, help="Report JSON path. Defaults to timestamped output file.")
    parser.add_argument("--metadata", default=None, help="Optional forecast metadata JSON for run indexing.")
    parser.add_argument("--index", default="output/forecast_runs_index.csv", help="Forecast runs index CSV.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN for saved prediction records.")
    parser.add_argument("--prediction-db", default=None, help="Deprecated alias for --postgres-dsn.")
    parser.add_argument("--run-id", default=None, help="Prediction DB run id. Defaults to metadata filename when metadata is provided.")
    parser.add_argument("--no-update-prediction-db", action="store_true", help="Skip updating saved prediction records.")
    parser.add_argument("--flat-threshold-pct", type=float, default=0.02)
    parser.add_argument("--cost-threshold-pct", type=float, default=0.05)
    parser.add_argument("--scoring-version", default="v1")
    return parser.parse_args()


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _infer_epic(path: Path, resolution: str) -> str:
    stem = path.stem
    marker = f"_{resolution}_"
    if marker in stem:
        before = stem.split(marker, 1)[0]
        return before.replace("kronos_forecast_", "") or "UNKNOWN"
    return "UNKNOWN"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find non-overwriting report path for {path}")


def main() -> None:
    configure_logging(service_name="validate_forecast_quality")
    args = parse_args()
    request_id = new_correlation_id("req")
    started = time.perf_counter()
    log_event(
        LOGGER,
        logging.INFO,
        "validate_forecast_quality.start",
        request_id=request_id,
        forecast_path=args.forecast,
        actual_path=args.actual,
        resolution=args.resolution,
        metadata_path=args.metadata,
        run_id=args.run_id,
        update_prediction_db=not args.no_update_prediction_db,
    )
    try:
        metadata_payload = {}
        if args.metadata and Path(args.metadata).exists():
            metadata_payload = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        last_input_close = metadata_payload.get("last_input_close")
        report = validate_forecast_quality(
            args.forecast,
            args.actual,
            args.resolution,
            args.price_side,
            flat_threshold_pct=args.flat_threshold_pct,
            cost_threshold_pct=args.cost_threshold_pct,
            last_input_close=None if last_input_close is None else float(last_input_close),
        )
        summary = report["forecast_quality_validation"]
        epic = args.epic or _infer_epic(Path(args.forecast), args.resolution)
        timestamp = Path(args.forecast).stem.split(f"_{args.resolution}_")[-1]
        output = Path(args.output) if args.output else _unique_path(Path("output") / f"forecast_quality_report_{_safe_name(epic)}_{args.resolution}_{timestamp}.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if args.metadata:
            append_forecast_run_index(
                args.index,
                metadata_path=args.metadata,
                quality_report_path=output,
                actual_csv_path=args.actual,
            )
        db_summary = None
        if not args.no_update_prediction_db and (args.metadata or args.run_id):
            db_summary = update_predictions_with_actuals(
                run_id=args.run_id or run_id_from_metadata_path(args.metadata),
                actual_csv_path=args.actual,
                db_path=args.postgres_dsn or args.prediction_db,
                flat_threshold_pct=args.flat_threshold_pct,
                scoring_version=args.scoring_version,
            )

        log_event(
            LOGGER,
            logging.INFO,
            "validate_forecast_quality.completed",
            request_id=request_id,
            forecast_path=args.forecast,
            actual_path=args.actual,
            resolution=args.resolution,
            quality_status=summary.get("quality_status"),
            matched_candles=summary.get("matched_candles"),
            wins=summary.get("wins"),
            losses=summary.get("losses"),
            output_path=str(output),
            run_id=args.run_id or (run_id_from_metadata_path(args.metadata) if args.metadata else None),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        status = summary["quality_status"]
        print("\nForecast quality summary")
        print(f"Matched candles: {summary['matched_candles']}")
        print(f"Display timezone: {summary.get('display_timezone', 'n/a')}")
        print(f"MAE: {summary['mae']}")
        print(f"RMSE: {summary['rmse']}")
        print(f"MAPE: {summary['mape_pct']}")
        print(f"Direction accuracy: {summary['direction_accuracy_pct']}")
        print(f"Quality status: {status}")
        print(f"Recommendation: {recommendation_for_status(status)}")
        if db_summary:
            print(
                "Prediction DB update: "
                f"{db_summary['wins']} WIN, {db_summary['losses']} LOSS, "
                f"{db_summary['pending_records']} PENDING, win_rate={db_summary['win_rate_pct']}"
            )
        print(f"Report: {output}")
    except Exception as exc:  # noqa: BLE001
        log_event(
            LOGGER,
            logging.ERROR,
            "validate_forecast_quality.error",
            request_id=request_id,
            forecast_path=args.forecast,
            actual_path=args.actual,
            resolution=args.resolution,
            metadata_path=args.metadata,
            run_id=args.run_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
