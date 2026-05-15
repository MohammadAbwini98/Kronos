from __future__ import annotations

import pandas as pd


TIMEFRAME_TO_DELTA = {
    "MINUTE": pd.Timedelta(minutes=1),
    "MINUTE_5": pd.Timedelta(minutes=5),
    "MINUTE_15": pd.Timedelta(minutes=15),
    "MINUTE_30": pd.Timedelta(minutes=30),
    "HOUR": pd.Timedelta(hours=1),
    "HOUR_4": pd.Timedelta(hours=4),
    "DAY": pd.Timedelta(days=1),
}


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    key = str(timeframe).upper()
    if key not in TIMEFRAME_TO_DELTA:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return TIMEFRAME_TO_DELTA[key]


def forecast_timestamps(last_timestamp: pd.Timestamp, timeframe: str, horizon_bars: int) -> list[pd.Timestamp]:
    delta = timeframe_delta(timeframe)
    anchor = pd.to_datetime(last_timestamp, utc=True)
    return [anchor + (index * delta) for index in range(1, int(horizon_bars) + 1)]
