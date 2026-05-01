from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from prediction_store import save_prediction_run
from time_utils import display_timezone_name, format_local_timestamp

SUPPORTED_RESOLUTIONS = {
    "MINUTE",
    "MINUTE_5",
    "MINUTE_15",
    "MINUTE_30",
    "HOUR",
    "HOUR_4",
    "DAY",
    "WEEK",
}
KRONOS_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


RESOLUTION_TO_PANDAS_FREQ = {
    "MINUTE": "1min",
    "MINUTE_5": "5min",
    "MINUTE_15": "15min",
    "MINUTE_30": "30min",
    "HOUR": "1h",
    "HOUR_4": "4h",
    "DAY": "1D",
    "WEEK": "1W",
}
RESOLUTION_TO_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Kronos forecast on a Kronos-ready CSV.")
    parser.add_argument("--input", required=True, help="Kronos-ready CSV with timestamps, OHLC, volume, amount.")
    parser.add_argument("--output", default=None, help="Forecast CSV output path. Defaults to timestamped output file.")
    parser.add_argument("--resolution", default="MINUTE_5", choices=sorted(SUPPORTED_RESOLUTIONS))
    parser.add_argument("--lookback", type=int, default=512, help="Historical rows to pass to Kronos.")
    parser.add_argument("--pred-len", type=int, default=12, help="Number of future candles to forecast.")
    parser.add_argument("--min-input-rows", type=int, default=50, help="Minimum historical rows required to run.")
    parser.add_argument("--preferred-input-rows", type=int, default=512, help="Preferred Kronos-base context length.")
    parser.add_argument("--epic", default=None, help="Capital.com epic for metadata and timestamped filenames.")
    parser.add_argument("--market-name", default="", help="Human-readable market name for metadata.")
    parser.add_argument("--price-side", default="mid", choices=["bid", "ask", "mid"], help="Price side used to build the input.")
    parser.add_argument("--source", default="Capital.com", help="Source provider label.")
    parser.add_argument("--model-name", default="Kronos-base", help="Model name for metadata.")
    parser.add_argument("--output-dir", default="output", help="Directory for timestamped forecast artifacts.")
    parser.add_argument("--metadata-output", default=None, help="Metadata JSON output path. Defaults to timestamped output file.")
    parser.add_argument("--input-copy-output", default=None, help="Input copy path. Defaults to timestamped output file.")
    parser.add_argument("--temperature", type=float, default=1.0, help="Kronos sampling temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Kronos nucleus sampling probability.")
    parser.add_argument("--sample-count", type=int, default=1, help="Number of sampled forecast paths to average.")
    parser.add_argument(
        "--feature-set",
        default="auto",
        choices=["auto", "ohlc", "ohlcv", "ohlcva"],
        help="Columns passed to Kronos. auto omits unavailable all-zero amount but keeps volume.",
    )
    parser.add_argument(
        "--repair-ohlc",
        action="store_true",
        help="Post-process forecast high/low so high >= open/close/low and low <= open/close/high.",
    )
    parser.add_argument("--validation-report", default=None, help="Optional JSON validation report path.")
    parser.add_argument("--max-close-move-pct", type=float, default=20.0, help="Warn if forecast close moves more than this percent from last close.")
    parser.add_argument("--flat-threshold-pct", type=float, default=0.02, help="Close movement below this percent is FLAT.")
    parser.add_argument(
        "--movement-cost-threshold-pct",
        type=float,
        default=float(os.getenv("SIGNAL_COST_THRESHOLD_PCT", "0.05")),
        help="Movement below this threshold is likely not useful after spread, fees, and slippage.",
    )
    parser.add_argument("--signal-min-confidence", type=float, default=float(os.getenv("SIGNAL_MIN_CONFIDENCE", "0.55")))
    parser.add_argument("--repo-dir", default=None, help="Local Kronos repository path.")
    parser.add_argument("--model-dir", default=None, help="Local Kronos model directory.")
    parser.add_argument("--tokenizer-dir", default=None, help="Local Kronos tokenizer directory.")
    parser.add_argument("--device", default=None, help="auto, cpu, cuda, or cuda:0.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN for saved prediction records.")
    parser.add_argument("--prediction-db", default=None, help="Deprecated alias for --postgres-dsn.")
    parser.add_argument("--no-save-prediction-db", action="store_true", help="Skip saving forecast rows to the prediction DB.")
    return parser.parse_args()


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _load_dotenv_if_present(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _utc_file_timestamp() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def _model_dir_ready(path: Path | None) -> bool:
    if path is None or not path.is_dir():
        return False
    return (path / "config.json").exists() and (path / "model.safetensors").exists()


def _auto_finetuned_model_dir(output_dir: Path) -> Path | None:
    status_path = output_dir / "auto_finetune_status.json"
    if not status_path.exists():
        return None
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    candidate = payload.get("active_model_path")
    if not candidate:
        return None
    promotion_status = str(payload.get("promotion_status") or "").strip().lower()
    if promotion_status not in {"approved", "promoted"}:
        return None
    model_path = Path(str(candidate))
    return model_path if _model_dir_ready(model_path) else None


def _infer_epic(input_csv: Path, resolution: str) -> str:
    stem = input_csv.stem
    prefix = "kronos_input_"
    suffix = f"_{resolution}"
    if stem.startswith(prefix) and stem.endswith(suffix):
        return stem[len(prefix) : -len(suffix)]
    return "UNKNOWN"


def _direction(start: float, end: float, flat_threshold_pct: float) -> str:
    if start == 0:
        return "FLAT"
    move_pct = ((end / start) - 1.0) * 100.0
    if abs(move_pct) < flat_threshold_pct:
        return "FLAT"
    return "UP" if move_pct > 0 else "DOWN"


def _validate_kronos_df(df: pd.DataFrame) -> None:
    missing = [col for col in KRONOS_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Kronos input missing columns: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Kronos input is empty")
    for col in ("open", "high", "low", "close"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(f"Kronos input column {col!r} must be numeric")
        if df[col].isna().any():
            raise ValueError(f"Kronos input column {col!r} contains null values")
    if df["timestamps"].duplicated().any():
        raise ValueError("Kronos input timestamps contain duplicates")
    if not df["timestamps"].is_monotonic_increasing:
        raise ValueError("Kronos input timestamps must be sorted ascending")


def _select_feature_columns(df: pd.DataFrame, feature_set: str) -> list[str]:
    if feature_set == "ohlc":
        return ["open", "high", "low", "close"]
    if feature_set == "ohlcv":
        return ["open", "high", "low", "close", "volume"]
    if feature_set == "ohlcva":
        return ["open", "high", "low", "close", "volume", "amount"]

    amount_is_unavailable = bool((df["amount"].abs() < 1e-12).all())
    volume_is_available = bool((df["volume"].abs() > 1e-12).any())
    if amount_is_unavailable and volume_is_available:
        return ["open", "high", "low", "close", "volume"]
    if amount_is_unavailable:
        return ["open", "high", "low", "close"]
    return ["open", "high", "low", "close", "volume", "amount"]


def _repair_ohlc(pred_df: pd.DataFrame) -> pd.DataFrame:
    repaired = pred_df.copy()
    repaired["high"] = repaired[["open", "high", "low", "close"]].max(axis=1)
    repaired["low"] = repaired[["open", "high", "low", "close"]].min(axis=1)
    return repaired


def _validate_forecast(
    pred_df: pd.DataFrame,
    input_df: pd.DataFrame,
    resolution: str,
    price_side: str,
    source: str,
    input_rows_used: int,
    preferred_input_rows: int,
    min_input_rows: int,
    flat_threshold_pct: float,
    movement_cost_threshold_pct: float,
    max_close_move_pct: float,
) -> dict[str, object]:
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    ohlc_violations = (
        (pred_df["high"] < pred_df[["open", "close", "low"]].max(axis=1))
        | (pred_df["low"] > pred_df[["open", "close", "high"]].min(axis=1))
    )
    expected_freq = pd.tseries.frequencies.to_offset(RESOLUTION_TO_PANDAS_FREQ[resolution])
    diffs = pred_df["timestamps"].diff().dropna()
    cadence_ok = bool(diffs.empty or (diffs == expected_freq).all())
    last_input_close = float(input_df["close"].iloc[-1])
    close_move_pct = ((pred_df["close"] / last_input_close - 1.0) * 100.0).abs()
    first_forecast_close = float(pred_df["close"].iloc[0])
    last_forecast_close = float(pred_df["close"].iloc[-1])
    forecast_horizon_minutes = RESOLUTION_TO_MINUTES[resolution] * len(pred_df)
    warnings: list[str] = []
    if input_rows_used < preferred_input_rows:
        warnings.append(
            f"Input rows used ({input_rows_used}) are below preferred Kronos-base context ({preferred_input_rows})."
        )
    if input_rows_used < min_input_rows:
        warnings.append(f"Input rows used ({input_rows_used}) are below configured minimum ({min_input_rows}).")
    movement_after_cost_warning = bool(float(close_move_pct.max()) < movement_cost_threshold_pct)
    report: dict[str, object] = {
        "input_rows_used": int(input_rows_used),
        "preferred_input_rows": int(preferred_input_rows),
        "minimum_input_rows": int(min_input_rows),
        "input_context_warning": bool(input_rows_used < preferred_input_rows),
        "forecast_rows": int(len(pred_df)),
        "forecast_horizon_candles": int(len(pred_df)),
        "forecast_horizon_minutes": int(forecast_horizon_minutes),
        "resolution": resolution,
        "price_side": price_side,
        "source": source,
        "display_timezone": display_timezone_name(),
        "columns": list(pred_df.columns),
        "timestamps_sorted": bool(pred_df["timestamps"].is_monotonic_increasing),
        "duplicate_timestamps": int(pred_df["timestamps"].duplicated().sum()),
        "cadence_ok": cadence_ok,
        "null_numeric_values": int(pred_df[numeric_cols].isna().sum().sum()),
        "finite_numeric_values": bool(np.isfinite(pred_df[numeric_cols].to_numpy()).all()),
        "ohlc_invariant_violations": int(ohlc_violations.sum()),
        "negative_volume_rows": int((pred_df["volume"] < 0).sum()),
        "negative_amount_rows": int((pred_df["amount"] < -1e-8).sum()),
        "last_input_timestamp": format_local_timestamp(input_df["timestamps"].iloc[-1]),
        "first_forecast_timestamp": format_local_timestamp(pred_df["timestamps"].iloc[0]),
        "last_forecast_timestamp": format_local_timestamp(pred_df["timestamps"].iloc[-1]),
        "last_input_close": last_input_close,
        "first_forecast_close": first_forecast_close,
        "last_forecast_close": last_forecast_close,
        "forecast_direction": _direction(last_input_close, last_forecast_close, flat_threshold_pct),
        "max_abs_close_move_pct": float(close_move_pct.max()),
        "maximum_forecast_close_deviation_pct": float(close_move_pct.max()),
        "movement_cost_threshold_pct": float(movement_cost_threshold_pct),
        "movement_after_cost_warning": movement_after_cost_warning,
        "close_move_warning": bool(close_move_pct.max() > max_close_move_pct),
        "warnings": warnings,
    }
    return report


def _write_metadata(
    path: Path,
    *,
    epic: str,
    market_name: str,
    resolution: str,
    price_side: str,
    input_rows_used: int,
    forecast_rows: int,
    model_name: str,
    model_dir: Path,
    tokenizer_dir: Path,
    source: str,
    generated_at_utc: str,
    input_df: pd.DataFrame,
    pred_df: pd.DataFrame,
    forecast_csv: Path,
    input_copy_csv: Path,
    validation_report: Path | None,
) -> None:
    metadata = {
        "epic": epic,
        "market_name": market_name,
        "resolution": resolution,
        "price_side": price_side,
        "input_rows_used": int(input_rows_used),
        "forecast_rows": int(forecast_rows),
        "forecast_horizon_minutes": int(RESOLUTION_TO_MINUTES[resolution] * forecast_rows),
        "model_name": model_name,
        "model_path": str(model_dir),
        "tokenizer_path": str(tokenizer_dir),
        "source_provider": source,
        "generated_at_utc": generated_at_utc,
        "generated_at_local": format_local_timestamp(generated_at_utc),
        "display_timezone": display_timezone_name(),
        "input_start_timestamp": format_local_timestamp(input_df["timestamps"].iloc[0]),
        "input_end_timestamp": format_local_timestamp(input_df["timestamps"].iloc[-1]),
        "forecast_start_timestamp": format_local_timestamp(pred_df["timestamps"].iloc[0]),
        "forecast_end_timestamp": format_local_timestamp(pred_df["timestamps"].iloc[-1]),
        "input_start_timestamp_utc": str(input_df["timestamps"].iloc[0]),
        "input_end_timestamp_utc": str(input_df["timestamps"].iloc[-1]),
        "forecast_start_timestamp_utc": str(pred_df["timestamps"].iloc[0]),
        "forecast_end_timestamp_utc": str(pred_df["timestamps"].iloc[-1]),
        "last_input_close": float(input_df["close"].iloc[-1]),
        "forecast_csv_path": str(forecast_csv),
        "input_csv_path": str(input_copy_csv),
        "validation_report_path": str(validation_report) if validation_report else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _require_model_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} directory does not exist: {path}")
    for required in ("config.json", "model.safetensors"):
        if not (path / required).exists():
            raise FileNotFoundError(f"{label} missing {required}: {path / required}")


def _select_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if requested == "cuda":
        return "cuda:0"
    return requested


def _future_timestamps(last_timestamp: pd.Timestamp, resolution: str, pred_len: int) -> pd.Series:
    freq = RESOLUTION_TO_PANDAS_FREQ[resolution]
    start = last_timestamp + pd.tseries.frequencies.to_offset(freq)
    return pd.Series(pd.date_range(start=start, periods=pred_len, freq=freq, tz="UTC"))


def run_prediction(
    input_csv: Path,
    output_csv: Path,
    repo_dir: Path,
    model_dir: Path,
    tokenizer_dir: Path,
    resolution: str,
    lookback: int,
    pred_len: int,
    min_input_rows: int,
    preferred_input_rows: int,
    epic: str,
    market_name: str,
    price_side: str,
    source: str,
    model_name: str,
    temperature: float,
    top_p: float,
    sample_count: int,
    device_request: str,
    feature_set: str,
    repair_ohlc: bool,
    validation_report: Path | None,
    metadata_output: Path | None,
    input_copy_output: Path | None,
    max_close_move_pct: float,
    flat_threshold_pct: float,
    movement_cost_threshold_pct: float,
    signal_min_confidence: float,
    prediction_db: Path | None = None,
    save_prediction_db: bool = True,
) -> pd.DataFrame:
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    _require_model_dir(model_dir, "Kronos model")
    _require_model_dir(tokenizer_dir, "Kronos tokenizer")

    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer

    df = pd.read_csv(input_csv)
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    _validate_kronos_df(df)
    if len(df) < min_input_rows:
        raise ValueError(f"Input has {len(df)} rows but minimum input rows is {min_input_rows}.")
    input_rows_used = min(len(df), lookback)
    if input_rows_used < preferred_input_rows:
        print(
            f"Warning: using {input_rows_used} input rows; preferred Kronos-base context is {preferred_input_rows}."
        )

    feature_columns = _select_feature_columns(df, feature_set)
    input_used_df = df.tail(input_rows_used).reset_index(drop=True)
    x_df = input_used_df[feature_columns].reset_index(drop=True)
    x_timestamp = input_used_df["timestamps"].reset_index(drop=True)
    y_timestamp = _future_timestamps(x_timestamp.iloc[-1], resolution, pred_len)
    device = _select_device(device_request)

    print(f"Loading Kronos tokenizer: {tokenizer_dir}")
    tokenizer = KronosTokenizer.from_pretrained(str(tokenizer_dir))
    print(f"Loading Kronos model: {model_dir}")
    model = Kronos.from_pretrained(str(model_dir))
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
    print(f"Running Kronos forecast on {device}; lookback={lookback}, pred_len={pred_len}")
    print(f"Columns passed to Kronos: {', '.join(feature_columns)}")

    with torch.no_grad():
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )

    pred_df = pred_df.reset_index().rename(columns={"index": "timestamps"})
    if "timestamps" not in pred_df.columns:
        pred_df.insert(0, "timestamps", y_timestamp)
    pred_df["timestamps"] = pd.to_datetime(pred_df["timestamps"], utc=True)
    for col in KRONOS_COLUMNS:
        if col not in pred_df.columns:
            pred_df[col] = 0.0
    pred_df = pred_df[KRONOS_COLUMNS]
    if repair_ohlc:
        pred_df = _repair_ohlc(pred_df)
    report = _validate_forecast(
        pred_df,
        input_used_df,
        resolution,
        price_side,
        source,
        input_rows_used,
        preferred_input_rows,
        min_input_rows,
        flat_threshold_pct,
        movement_cost_threshold_pct,
        max_close_move_pct,
    )
    if validation_report is not None:
        validation_report.parent.mkdir(parents=True, exist_ok=True)
        validation_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["ohlc_invariant_violations"]:
        raise ValueError(
            f"Kronos forecast failed OHLC validation: {report['ohlc_invariant_violations']} invariant violation(s). "
            "Re-run with --repair-ohlc to save a post-processed forecast."
        )
    if report["null_numeric_values"] or report["negative_volume_rows"] or report["negative_amount_rows"]:
        raise ValueError(f"Kronos forecast failed numeric validation: {report}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pred_df.to_csv(output_csv, index=False)
    if input_copy_output is not None:
        input_copy_output.parent.mkdir(parents=True, exist_ok=True)
        input_used_df.to_csv(input_copy_output, index=False)
    if metadata_output is not None:
        _write_metadata(
            metadata_output,
            epic=epic,
            market_name=market_name,
            resolution=resolution,
            price_side=price_side,
            input_rows_used=input_rows_used,
            forecast_rows=len(pred_df),
            model_name=model_name,
            model_dir=model_dir,
            tokenizer_dir=tokenizer_dir,
            source=source,
            generated_at_utc=pd.Timestamp.now(tz="UTC").isoformat(),
            input_df=input_used_df,
            pred_df=pred_df,
            forecast_csv=output_csv,
            input_copy_csv=input_copy_output,
            validation_report=validation_report,
        )
        if save_prediction_db:
            db_summary = save_prediction_run(
                metadata_output,
                db_path=prediction_db,
                flat_threshold_pct=flat_threshold_pct,
                cost_threshold_pct=movement_cost_threshold_pct,
                min_confidence=signal_min_confidence,
            )
            print(
                "Prediction DB saved: "
                f"{db_summary['saved_records']} rows, run_id={db_summary['run_id']}, dsn={db_summary['dsn']}"
            )
    print("Validation report:")
    print(json.dumps(report, indent=2))
    return pred_df


def main() -> None:
    _load_dotenv_if_present()
    args = parse_args()
    repo_dir = Path(args.repo_dir or _env("KRONOS_REPO_DIR", r"C:\AI\Kronos"))
    tokenizer_dir = Path(args.tokenizer_dir or _env("KRONOS_TOKENIZER_DIR", r"C:\AI\Models\Kronos\Kronos-Tokenizer-base"))
    device = args.device or _env("KRONOS_DEVICE", "auto")
    run_timestamp = _utc_file_timestamp()
    epic = args.epic or _infer_epic(Path(args.input), args.resolution)
    safe_epic = _safe_name(epic)
    output_dir = Path(args.output_dir)
    configured_model_dir = Path(args.model_dir or _env("KRONOS_MODEL_DIR", r"C:\AI\Models\Kronos\Kronos-base"))
    auto_model_dir = None
    if args.model_dir is None:
        auto_model_dir = _auto_finetuned_model_dir(output_dir)
    model_dir = auto_model_dir or configured_model_dir
    model_name = "Kronos-auto-finetuned" if auto_model_dir is not None else args.model_name
    output_csv = Path(args.output) if args.output else output_dir / f"kronos_forecast_{safe_epic}_{args.resolution}_{run_timestamp}.csv"
    metadata_output = (
        Path(args.metadata_output)
        if args.metadata_output
        else output_dir / f"forecast_metadata_{safe_epic}_{args.resolution}_{run_timestamp}.json"
    )
    input_copy_output = (
        Path(args.input_copy_output)
        if args.input_copy_output
        else output_dir / f"kronos_input_{safe_epic}_{args.resolution}_{run_timestamp}.csv"
    )
    validation_report = (
        Path(args.validation_report)
        if args.validation_report
        else output_dir / f"kronos_forecast_validation_{safe_epic}_{args.resolution}_{run_timestamp}.json"
    )

    pred_df = run_prediction(
        input_csv=Path(args.input),
        output_csv=output_csv,
        repo_dir=repo_dir,
        model_dir=model_dir,
        tokenizer_dir=tokenizer_dir,
        resolution=args.resolution,
        lookback=args.lookback,
        pred_len=args.pred_len,
        min_input_rows=args.min_input_rows,
        preferred_input_rows=args.preferred_input_rows,
        epic=epic,
        market_name=args.market_name,
        price_side=args.price_side,
        source=args.source,
        model_name=model_name,
        temperature=args.temperature,
        top_p=args.top_p,
        sample_count=args.sample_count,
        device_request=device,
        feature_set=args.feature_set,
        repair_ohlc=args.repair_ohlc,
        validation_report=validation_report,
        metadata_output=metadata_output,
        input_copy_output=input_copy_output,
        max_close_move_pct=args.max_close_move_pct,
        flat_threshold_pct=args.flat_threshold_pct,
        movement_cost_threshold_pct=args.movement_cost_threshold_pct,
        signal_min_confidence=args.signal_min_confidence,
        prediction_db=Path(args.postgres_dsn or args.prediction_db) if (args.postgres_dsn or args.prediction_db) else None,
        save_prediction_db=not args.no_save_prediction_db,
    )
    print("\nKronos forecast complete")
    print(f"Input: {Path(args.input)}")
    print(f"Timestamped input copy: {input_copy_output}")
    print(f"Forecast output: {output_csv}")
    print(f"Metadata: {metadata_output}")
    print(f"Validation report: {validation_report}")
    print(f"Forecast rows: {len(pred_df)}")
    print(pred_df.head().to_string(index=False))


if __name__ == "__main__":
    main()
