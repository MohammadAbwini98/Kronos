from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from capital_rest_client import CapitalRestClient
from config import configure_logging, load_settings, safe_epic_for_filename, validate_price_side, validate_resolution
from data_quality import analyze_ohlcv_quality, grade_meets_minimum, persist_prediction_run_quality
from prediction_store import run_id_from_metadata_path, save_shadow_prediction, upsert_instrument, upsert_ohlcv_df
from time_utils import format_local_timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch latest Capital.com candles and generate a current/future Kronos forecast.")
    parser.add_argument("--market", default="ETHUSD")
    parser.add_argument("--epic", default=None)
    parser.add_argument("--resolution", default="MINUTE_5")
    parser.add_argument("--max", type=int, default=512, dest="max_points")
    parser.add_argument("--lookback", type=int, default=512)
    parser.add_argument("--pred-len", type=int, default=12)
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"])
    parser.add_argument("--env", default="demo", choices=["demo", "live"])
    parser.add_argument("--feature-set", default="auto", choices=["auto", "ohlc", "ohlcv", "ohlcva"])
    parser.add_argument("--repair-ohlc", action="store_true", help="Repair forecast high/low if raw Kronos output violates OHLC envelope.")
    parser.add_argument("--kronos-python", default=r"C:\AI\Kronos\.venv\Scripts\python.exe")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--symbol", default=None, help="Configured dashboard/signal symbol. Defaults to market.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--disable-shadow-model", action="store_true", help="Skip candidate-model shadow prediction.")
    return parser.parse_args()


def _read_window(csv_path: Path) -> tuple[str, str]:
    df = pd.read_csv(csv_path)
    return str(df.iloc[0]["timestamps"]), str(df.iloc[-1]["timestamps"])


def _flag_enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _model_ready(path: Path) -> bool:
    return path.is_dir() and (path / "config.json").exists() and (path / "model.safetensors").exists()


def _shadow_candidate_model(output_dir: Path) -> dict[str, str] | None:
    status_path = output_dir / "auto_finetune_status.json"
    if not status_path.exists():
        return None
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    promotion_status = str(payload.get("promotion_status") or "").strip().lower()
    # Shadow runs during both "pending_review" (accumulating matches) and
    # "pending_evaluation" (model trained, awaiting evaluate_promotion()).
    # "not_ready" and "approved" do not run shadow.
    if promotion_status not in ("pending_review", "pending_evaluation"):
        return None
    candidate = payload.get("active_model_path")
    if not candidate:
        return None
    model_dir = Path(str(candidate))
    if not _model_ready(model_dir):
        return None
    return {
        "model_dir": str(model_dir),
        "model_version_id": payload.get("candidate_model_version_id") or payload.get("model_version_id") or model_dir.name,
    }


def _run_shadow_prediction(
    *,
    base_cmd: list[str],
    active_metadata: Path,
    output_dir: Path,
    model_dir: Path,
    shadow_model_version_id: str | None,
    dsn: str | None,
) -> None:
    active_run_id = run_id_from_metadata_path(active_metadata)
    stamp = active_metadata.stem.replace("forecast_metadata_", "", 1)
    shadow_forecast = output_dir / f"shadow_kronos_forecast_{stamp}.csv"
    shadow_metadata = output_dir / f"shadow_forecast_metadata_{stamp}.json"
    shadow_input = output_dir / f"shadow_kronos_input_{stamp}.csv"
    shadow_validation = output_dir / f"shadow_kronos_forecast_validation_{stamp}.json"
    cmd = [
        *base_cmd,
        "--model-dir",
        str(model_dir),
        "--model-name",
        "Kronos-auto-shadow",
        "--output",
        str(shadow_forecast),
        "--metadata-output",
        str(shadow_metadata),
        "--input-copy-output",
        str(shadow_input),
        "--validation-report",
        str(shadow_validation),
        "--no-save-prediction-db",
    ]
    result = subprocess.run(cmd, cwd=Path.cwd(), text=True)
    if result.returncode != 0:
        print(f"Shadow model prediction failed with exit code {result.returncode}.")
        return
    save_shadow_prediction(
        active_run_id=active_run_id,
        metadata_path=shadow_metadata,
        dsn=dsn,
        shadow_model_version_id=shadow_model_version_id,
    )
    print(f"Shadow model signal recorded for active run {active_run_id}.")


def main() -> None:
    configure_logging()
    args = parse_args()
    resolution = validate_resolution(args.resolution)
    price_side = validate_price_side(args.price_side)
    settings = load_settings(args.env)
    settings.output_dir = Path(args.output_dir)
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    client = CapitalRestClient(settings)
    client.authenticate()
    selected = client.resolve_market(args.market, args.epic, streaming=False)
    epic = selected["epic"]
    symbol = args.symbol or args.market or epic
    market_name = selected.get("instrumentName") or ""
    client.save_market_details(epic)
    df = client.get_historical_prices(
        epic=epic,
        resolution=resolution,
        max_points=args.max_points,
        price_side=price_side,
        save_outputs=True,
        min_rows=min(args.lookback, args.max_points, 50),
    )
    data_quality = analyze_ohlcv_quality(
        df,
        resolution=resolution,
        expected_rows=args.lookback,
    )
    min_quality_grade = os.getenv("MIN_PREDICTION_QUALITY_GRADE")
    quality_action = os.getenv("PREDICTION_QUALITY_ACTION", "downgrade").strip().lower()
    if min_quality_grade and not grade_meets_minimum(data_quality.quality_grade, min_quality_grade):
        message = f"Prediction input quality {data_quality.quality_grade} is below minimum {min_quality_grade}."
        if quality_action == "block":
            raise SystemExit(message)
        print(f"WARNING: {message} Signal quality will be downgraded in metadata.")
    upsert_instrument(
        symbol=symbol,
        epic=epic,
        market_name=market_name,
        price_side=price_side,
        metadata=selected,
        dsn=args.postgres_dsn,
    )
    stored_rows = upsert_ohlcv_df(
        df,
        symbol=symbol,
        epic=epic,
        resolution=resolution,
        price_side=price_side,
        source="latest_fetch",
        dsn=args.postgres_dsn,
    )
    input_path = settings.output_dir / f"kronos_input_{safe_epic_for_filename(epic)}_{resolution}.csv"
    last_input = df["timestamps"].iloc[-1]
    print("\nLatest input fetched")
    print(f"Epic: {epic}")
    print(f"Market: {market_name}")
    print(f"Rows: {len(df)}")
    print(f"PostgreSQL candles upserted: {stored_rows}")
    print(f"Last input candle: {format_local_timestamp(last_input)}")

    # Generate run_stamp here so we can construct artifact paths deterministically
    # instead of globbing for the lexicographic latest file after the subprocess.
    run_stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
    cmd = [
        args.kronos_python,
        str(Path("src") / "main_run_kronos_predict.py"),
        "--input",
        str(input_path),
        "--resolution",
        resolution,
        "--lookback",
        str(args.lookback),
        "--pred-len",
        str(args.pred_len),
        "--epic",
        epic,
        "--market-name",
        market_name,
        "--price-side",
        price_side,
        "--feature-set",
        args.feature_set,
        "--output-dir",
        str(settings.output_dir),
        "--postgres-dsn",
        args.postgres_dsn or "",
        "--run-stamp",
        run_stamp,
    ]
    if args.repair_ohlc:
        cmd.append("--repair-ohlc")

    result = subprocess.run(cmd, cwd=Path.cwd(), text=True)
    if result.returncode != 0 and not args.repair_ohlc:
        print("\nRaw Kronos output failed validation. Retrying with --repair-ohlc.")
        result = subprocess.run([*cmd, "--repair-ohlc"], cwd=Path.cwd(), text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    latest_metadata = settings.output_dir / f"forecast_metadata_{safe_epic_for_filename(epic)}_{resolution}_{run_stamp}.json"
    metadata = json.loads(latest_metadata.read_text(encoding="utf-8"))
    metadata["data_quality"] = data_quality.to_dict()
    if min_quality_grade and not grade_meets_minimum(data_quality.quality_grade, min_quality_grade):
        metadata["data_quality"]["quality_gate_action"] = quality_action
        metadata["data_quality"]["minimum_grade"] = min_quality_grade
    latest_metadata.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    try:
        persist_prediction_run_quality(
            run_id_from_metadata_path(latest_metadata),
            data_quality,
            dsn=args.postgres_dsn,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: data quality report could not be persisted: {exc}")
    shadow_model = None if args.disable_shadow_model else _shadow_candidate_model(settings.output_dir)
    if shadow_model is not None and _flag_enabled("ENABLE_SHADOW_MODEL", True):
        try:
            _run_shadow_prediction(
                base_cmd=cmd,
                active_metadata=latest_metadata,
                output_dir=settings.output_dir,
                model_dir=Path(shadow_model["model_dir"]),
                shadow_model_version_id=shadow_model.get("model_version_id"),
                dsn=args.postgres_dsn,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Shadow model prediction could not be recorded: {exc}")
    print("\nCurrent/future forecast ready")
    print(f"Forecast start: {metadata['forecast_start_timestamp']}")
    print(f"Forecast end: {metadata['forecast_end_timestamp']}")
    print(f"Forecast CSV: {metadata['forecast_csv_path']}")
    print(f"Metadata: {latest_metadata}")


if __name__ == "__main__":
    main()
