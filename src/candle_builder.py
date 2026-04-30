from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


RESOLUTION_MINUTES = {
    "MINUTE": 1,
    "MINUTE_5": 5,
    "MINUTE_15": 15,
    "MINUTE_30": 30,
    "HOUR": 60,
    "HOUR_4": 240,
    "DAY": 1440,
    "WEEK": 10080,
}


@dataclass(frozen=True)
class Tick:
    timestamp: pd.Timestamp
    price: float
    volume: float = 0.0


def floor_timestamp(timestamp: pd.Timestamp, resolution: str) -> pd.Timestamp:
    minutes = RESOLUTION_MINUTES[resolution]
    ts = pd.to_datetime(timestamp, utc=True)
    if minutes < 1440:
        return ts.floor(f"{minutes}min")
    if resolution == "DAY":
        return ts.floor("D")
    return ts.to_period("W").start_time.tz_localize("UTC")


def build_ohlcv_from_ticks(ticks: Iterable[Tick], resolution: str) -> pd.DataFrame:
    rows = [
        {"timestamps": pd.to_datetime(tick.timestamp, utc=True), "price": float(tick.price), "volume": float(tick.volume)}
        for tick in ticks
    ]
    if not rows:
        return pd.DataFrame(columns=["timestamps", "open", "high", "low", "close", "volume", "amount"])
    df = pd.DataFrame(rows)
    df["bucket"] = df["timestamps"].apply(lambda value: floor_timestamp(value, resolution))
    grouped = df.groupby("bucket", sort=True)
    out = grouped.agg(open=("price", "first"), high=("price", "max"), low=("price", "min"), close=("price", "last"), volume=("volume", "sum"))
    out = out.reset_index().rename(columns={"bucket": "timestamps"})
    out["amount"] = 0.0
    return out[["timestamps", "open", "high", "low", "close", "volume", "amount"]]
