from __future__ import annotations

from pathlib import Path

import pandas as pd

from forecast_quality_validator import validate_ohlc_df


RESOLUTION_TO_FREQ = {
    "MINUTE": "1min",
    "MINUTE_5": "5min",
    "MINUTE_15": "15min",
    "MINUTE_30": "30min",
    "HOUR": "1h",
    "HOUR_4": "4h",
    "DAY": "1D",
    "WEEK": "1W",
}


def _future_timestamps(last_timestamp: pd.Timestamp, resolution: str, pred_len: int) -> pd.Series:
    freq = RESOLUTION_TO_FREQ[resolution]
    start = last_timestamp + pd.tseries.frequencies.to_offset(freq)
    return pd.Series(pd.date_range(start=start, periods=pred_len, freq=freq, tz="UTC"))


def generate_baseline_forecast(
    input_csv_path: str | Path,
    output_csv_path: str | Path,
    resolution: str,
    pred_len: int = 12,
    method: str = "naive",
    moving_average_window: int = 12,
) -> pd.DataFrame:
    if method not in {"naive", "drift", "moving_average", "last_direction"}:
        raise ValueError(f"Unsupported baseline method: {method}")
    df = validate_ohlc_df(pd.read_csv(input_csv_path), "baseline input")
    last = df.iloc[-1]
    timestamps = _future_timestamps(last["timestamps"], resolution, pred_len)
    if method == "naive":
        closes = [float(last["close"])] * pred_len
    elif method == "moving_average":
        closes = [float(df["close"].tail(moving_average_window).mean())] * pred_len
    elif method == "drift":
        first_close = float(df["close"].iloc[0])
        last_close = float(last["close"])
        step = (last_close - first_close) / max(len(df) - 1, 1)
        closes = [last_close + step * (i + 1) for i in range(pred_len)]
    else:
        delta = float(df["close"].iloc[-1] - df["close"].iloc[-2]) if len(df) >= 2 else 0.0
        closes = [float(last["close"]) + delta * (i + 1) for i in range(pred_len)]

    rows = []
    spread = max(float(df["high"].tail(20).sub(df["low"].tail(20)).mean()), 0.01)
    volume = float(df["volume"].tail(20).mean())
    amount_multiplier = float(df["amount"].tail(20).mean() / volume) if volume else float(last["close"])
    for ts, close in zip(timestamps, closes):
        open_ = float(last["close"])
        high = max(open_, close) + spread * 0.25
        low = min(open_, close) - spread * 0.25
        rows.append(
            {
                "timestamps": ts,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": volume * amount_multiplier,
            }
        )
    forecast = pd.DataFrame(rows)
    output = Path(output_csv_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_csv(output, index=False)
    return forecast
