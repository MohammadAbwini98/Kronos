from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from config import validate_price_side

KRONOS_COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


class KronosMappingError(ValueError):
    """Raised when Capital.com data cannot be mapped into Kronos schema."""


def _price_value(price: dict[str, Any] | None, side: str) -> float:
    if not isinstance(price, dict):
        raise KronosMappingError("Missing price object in Capital.com price payload")
    if side == "mid":
        bid = price.get("bid")
        ask = price.get("ask")
        if bid is None or ask is None:
            raise KronosMappingError("Mid price requires both bid and ask values")
        return (float(bid) + float(ask)) / 2.0
    value = price.get(side)
    if value is None:
        raise KronosMappingError(f"Missing {side} price value")
    return float(value)


def _extract_prices(raw_prices: Any) -> list[dict[str, Any]]:
    if isinstance(raw_prices, dict):
        prices = raw_prices.get("prices", raw_prices.get("data", raw_prices))
        if isinstance(prices, list):
            return prices
    if isinstance(raw_prices, list):
        return raw_prices
    raise KronosMappingError("Expected Capital.com prices response object with a 'prices' list")


def capital_prices_to_kronos_df(raw_prices: Any, price_side: str = "mid", min_rows: int = 50) -> pd.DataFrame:
    side = validate_price_side(price_side)
    rows: list[dict[str, Any]] = []
    for item in _extract_prices(raw_prices):
        timestamp = item.get("snapshotTimeUTC") or item.get("snapshotTime")
        if not timestamp:
            raise KronosMappingError("Price item missing snapshotTimeUTC/snapshotTime")
        rows.append(
            {
                "timestamps": pd.to_datetime(timestamp, utc=True),
                "open": _price_value(item.get("openPrice"), side),
                "high": _price_value(item.get("highPrice"), side),
                "low": _price_value(item.get("lowPrice"), side),
                "close": _price_value(item.get("closePrice"), side),
                "volume": float(item.get("lastTradedVolume") or 0.0),
                "amount": 0.0,
            }
        )
    df = pd.DataFrame(rows, columns=KRONOS_COLUMNS)
    if not df.empty:
        df = df.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    validate_kronos_df(df, min_rows=min_rows)
    return df


def ws_ohlc_to_kronos_row(event_payload: dict[str, Any]) -> dict[str, Any]:
    payload = event_payload.get("payload", event_payload)
    for key in ("t", "o", "h", "l", "c"):
        if key not in payload:
            raise KronosMappingError(f"WebSocket OHLC payload missing {key!r}")
    return {
        "timestamps": pd.to_datetime(int(payload["t"]), unit="ms", utc=True),
        "open": float(payload["o"]),
        "high": float(payload["h"]),
        "low": float(payload["l"]),
        "close": float(payload["c"]),
        "volume": 0.0,
        "amount": 0.0,
    }


def validate_kronos_df(df: pd.DataFrame, min_rows: int = 50) -> None:
    missing = [col for col in KRONOS_COLUMNS if col not in df.columns]
    if missing:
        raise KronosMappingError(f"Kronos DataFrame missing required columns: {', '.join(missing)}")
    if df.empty:
        raise KronosMappingError("Kronos DataFrame is empty")
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    for col in ("open", "high", "low", "close"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise KronosMappingError(f"Kronos column {col!r} must be numeric")
        if df[col].isna().any():
            raise KronosMappingError(f"Kronos column {col!r} contains null values")
    if df["timestamps"].duplicated().any():
        raise KronosMappingError("Kronos timestamps contain duplicates")
    if not df["timestamps"].is_monotonic_increasing:
        raise KronosMappingError("Kronos timestamps must be sorted ascending")
    if len(df) < min_rows:
        raise KronosMappingError(f"Kronos DataFrame should contain at least {min_rows} rows")


def save_kronos_csv(df: pd.DataFrame, path: str | Path, min_rows: int = 50) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_kronos_df(df, min_rows=min_rows)
    df.to_csv(target, index=False)


def prepare_for_kronos_predictor(df: pd.DataFrame, lookback: int = 512, pred_len: int = 12) -> pd.DataFrame:
    """Placeholder for a future local Kronos predictor integration."""
    if lookback <= 0 or pred_len <= 0:
        raise KronosMappingError("lookback and pred_len must be positive")
    validate_kronos_df(df, min_rows=1)
    return df.tail(lookback).copy()
