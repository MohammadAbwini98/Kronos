from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from candle_context import resolution_to_timedelta


def _load_json(value: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    path = Path(value)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_frame(value: str | Path | pd.DataFrame | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _coerce_ohlc_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    if df.empty:
        return df
    if "timestamps" in df.columns:
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "timestamps" in df.columns:
        df = df.dropna(subset=["timestamps"]).sort_values("timestamps")
        df = df.drop_duplicates(subset=["timestamps"], keep="last").reset_index(drop=True)
    return df


def _run_id_from_metadata_path(metadata_path: str | Path | None, metadata: dict[str, Any]) -> str:
    if metadata.get("run_id"):
        return str(metadata["run_id"])
    if metadata_path is None:
        return "UNKNOWN_RUN"
    stem = Path(metadata_path).stem
    if stem.startswith("forecast_metadata_"):
        return stem.replace("forecast_metadata_", "", 1)
    return stem


def _direction(last_input_close: float, final_close: float, flat_threshold_pct: float) -> str:
    if last_input_close == 0.0:
        return "FLAT"
    move_pct = ((final_close / last_input_close) - 1.0) * 100.0
    if abs(move_pct) <= flat_threshold_pct:
        return "FLAT"
    return "UP" if move_pct > 0 else "DOWN"


def _path_consistency_score(last_input_close: float, closes: list[float]) -> float:
    if not closes:
        return 0.0
    if len(closes) == 1:
        return 100.0

    final_move = closes[-1] - last_input_close
    if final_move == 0.0:
        return 0.0

    target_sign = 1 if final_move > 0 else -1
    chain = [last_input_close, *closes]
    steps = [chain[index + 1] - chain[index] for index in range(len(chain) - 1)]
    aligned = sum(1 for step in steps if step != 0 and (1 if step > 0 else -1) == target_sign)
    return round((aligned / max(len(steps), 1)) * 100.0, 4)


def _quality_score_from_report(validation_report: dict[str, Any], fallback: float) -> float:
    quality = validation_report.get("forecast_quality_validation", validation_report)
    if not isinstance(quality, dict):
        return fallback

    mapped = {
        "PROMISING": 90.0,
        "NEEDS_MORE_SAMPLES": 60.0,
        "WEAK": 35.0,
    }
    status = str(quality.get("quality_status") or "").upper()
    if status in mapped:
        return mapped[status]

    direction_accuracy = quality.get("direction_accuracy_pct")
    if direction_accuracy is None:
        return fallback
    try:
        value = float(direction_accuracy)
    except Exception:  # noqa: BLE001
        return fallback
    return max(0.0, min(100.0, value))


def normalize_forecast(
    *,
    metadata: str | Path | dict[str, Any] | None = None,
    metadata_path: str | Path | None = None,
    forecast: str | Path | pd.DataFrame | None = None,
    input_data: str | Path | pd.DataFrame | None = None,
    validation_report: str | Path | dict[str, Any] | None = None,
    estimated_cost_pct: float = 0.05,
    flat_threshold_pct: float = 0.02,
) -> dict[str, Any]:
    """
    Normalize forecast artifacts into a stable analytical payload used by blockers and scoring.
    """
    md = _load_json(metadata)
    if metadata_path is None and isinstance(metadata, (str, Path)):
        metadata_path = metadata

    forecast_frame = _coerce_ohlc_frame(_load_frame(forecast if forecast is not None else md.get("forecast_csv_path")))
    input_frame = _coerce_ohlc_frame(_load_frame(input_data if input_data is not None else md.get("input_csv_path")))
    report = _load_json(validation_report)

    if forecast_frame.empty:
        raise ValueError("Forecast data is required for normalization.")
    if input_frame.empty:
        raise ValueError("Input data is required for normalization.")

    symbol = str(md.get("symbol") or md.get("epic") or "ETHUSD")
    epic = str(md.get("epic") or symbol)
    resolution = str(md.get("resolution") or "MINUTE_5").upper()

    last_input_close = float(input_frame["close"].iloc[-1])
    first_forecast_close = float(forecast_frame["close"].iloc[0])
    last_forecast_close = float(forecast_frame["close"].iloc[-1])

    forecast_return_pct = 0.0
    if last_input_close != 0.0:
        forecast_return_pct = ((last_forecast_close / last_input_close) - 1.0) * 100.0

    closes = [float(value) for value in forecast_frame["close"].tolist()]
    direction = _direction(last_input_close, last_forecast_close, flat_threshold_pct)

    # Use high/low range when available; otherwise fallback to close-path range.
    range_high = float(forecast_frame["high"].max()) if "high" in forecast_frame.columns else max(closes)
    range_low = float(forecast_frame["low"].min()) if "low" in forecast_frame.columns else min(closes)
    forecast_range_pct = 0.0 if last_input_close == 0.0 else ((range_high - range_low) / last_input_close) * 100.0

    cost_pct = float(md.get("cost_threshold_pct") or estimated_cost_pct)
    net_edge_pct = abs(forecast_return_pct) - cost_pct

    candidate_signal = "HOLD"
    if direction == "UP" and net_edge_pct > 0:
        candidate_signal = "LONG"
    elif direction == "DOWN" and net_edge_pct > 0:
        candidate_signal = "SHORT"

    candles = int(len(forecast_frame.index))
    horizon_minutes = int(resolution_to_timedelta(resolution).total_seconds() / 60) * candles

    consistency_score = _path_consistency_score(last_input_close, closes)
    quality_score = _quality_score_from_report(report, fallback=consistency_score)

    reasons: list[str] = []
    if direction == "FLAT":
        reasons.append("Forecast direction is FLAT after flat threshold filtering.")
    if net_edge_pct <= 0.0:
        reasons.append("Forecast movement does not clear estimated cost threshold.")

    payload = {
        "run_id": _run_id_from_metadata_path(metadata_path, md),
        "symbol": symbol,
        "epic": epic,
        "resolution": resolution,
        "generated_at_utc": str(md.get("generated_at_utc") or pd.Timestamp.now(tz="UTC").isoformat()),
        "last_input_close": last_input_close,
        "first_forecast_close": first_forecast_close,
        "last_forecast_close": last_forecast_close,
        "forecast_return_pct": float(forecast_return_pct),
        "forecast_return_bps": float(forecast_return_pct * 100.0),
        "forecast_direction": direction,
        "candidate_signal": candidate_signal,
        "forecast_range_pct": float(forecast_range_pct),
        "forecast_range_bps": float(forecast_range_pct * 100.0),
        "estimated_cost_pct": float(cost_pct),
        "estimated_cost_bps": float(cost_pct * 100.0),
        "net_edge_pct": float(net_edge_pct),
        "net_edge_bps": float(net_edge_pct * 100.0),
        "forecast_horizon_candles": candles,
        "forecast_horizon_minutes": horizon_minutes,
        "forecast_path_consistency_score": float(consistency_score),
        "forecast_quality_score": float(quality_score),
        "reason_details": reasons,
    }
    return payload
