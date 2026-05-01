from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

import pandas as pd

from capital_rest_client import CapitalApiError, CapitalRestClient
from kronos_mapper import KronosMappingError
from prediction_store import PREDICTION_COLUMNS, upsert_instrument, upsert_ohlcv_df
from db import connect


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


@dataclass(frozen=True)
class HistoricalBackfillSummary:
    symbol: str
    epic: str
    resolution: str
    price_side: str
    window_start_utc: str
    window_end_utc: str
    expected_rows: int
    existing_rows: int
    missing_rows: int
    missing_ranges: int
    fetched_rows: int
    upserted_rows: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolution_minutes(resolution: str) -> int:
    value = str(resolution or "").upper()
    if value not in RESOLUTION_TO_MINUTES:
        raise ValueError(f"Unsupported resolution for historical backfill: {resolution}")
    return RESOLUTION_TO_MINUTES[value]


def capital_time(value: pd.Timestamp) -> str:
    return pd.to_datetime(value, utc=True).strftime("%Y-%m-%dT%H:%M:%S")


def history_window(*, days: int, resolution: str, now: pd.Timestamp | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    minutes = resolution_minutes(resolution)
    end = pd.to_datetime(now, utc=True) if now is not None else pd.Timestamp.now(tz="UTC")
    end = end.floor(f"{minutes}min")
    start = (end - pd.Timedelta(days=max(1, int(days)))).floor(f"{minutes}min")
    return start, end


def latest_available_timestamp(*, client: CapitalRestClient, epic: str, resolution: str, price_side: str) -> pd.Timestamp:
    minutes = resolution_minutes(resolution)
    df = latest_available_frame(client=client, epic=epic, resolution=resolution, price_side=price_side, max_points=1)
    if df.empty:
        raise RuntimeError(f"Capital.com returned no latest {resolution} candle for {epic}")
    return pd.to_datetime(df["timestamps"].iloc[-1], utc=True).floor(f"{minutes}min")


def latest_available_frame(
    *,
    client: CapitalRestClient,
    epic: str,
    resolution: str,
    price_side: str,
    max_points: int,
) -> pd.DataFrame:
    return client.get_historical_prices(
        epic=epic,
        resolution=resolution,
        max_points=max(1, min(1000, int(max_points))),
        price_side=price_side,
        save_outputs=False,
        min_rows=1,
    )


def expected_timestamps(start: pd.Timestamp, end: pd.Timestamp, resolution: str) -> pd.DatetimeIndex:
    minutes = resolution_minutes(resolution)
    start = pd.to_datetime(start, utc=True).floor(f"{minutes}min")
    end = pd.to_datetime(end, utc=True).floor(f"{minutes}min")
    if start > end:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.date_range(start=start, end=end, freq=f"{minutes}min")


def missing_timestamp_ranges(
    *,
    existing: Iterable[pd.Timestamp],
    start: pd.Timestamp,
    end: pd.Timestamp,
    resolution: str,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    expected = expected_timestamps(start, end, resolution)
    minutes = resolution_minutes(resolution)
    existing_set = {
        pd.to_datetime(value, utc=True).floor(f"{minutes}min")
        for value in existing
        if pd.notna(value)
    }
    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    range_start: pd.Timestamp | None = None
    previous: pd.Timestamp | None = None
    for timestamp in expected:
        if timestamp in existing_set:
            if range_start is not None and previous is not None:
                ranges.append((range_start, previous))
            range_start = None
            previous = None
            continue
        if range_start is None:
            range_start = timestamp
        previous = timestamp
    if range_start is not None and previous is not None:
        ranges.append((range_start, previous))
    return ranges


def _load_existing_timestamps(
    *,
    symbol: str,
    epic: str,
    resolution: str,
    price_side: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    dsn: str | None,
) -> list[pd.Timestamp]:
    with connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT timestamp_utc
            FROM ohlcv_candles
            WHERE symbol = %s
              AND epic = %s
              AND resolution = %s
              AND price_side = %s
              AND timestamp_utc >= %s
              AND timestamp_utc <= %s
            ORDER BY timestamp_utc
            """,
            (symbol, epic, resolution, price_side, capital_time(start), capital_time(end)),
        ).fetchall()
    return [pd.to_datetime(row["timestamp_utc"], utc=True) for row in rows]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=PREDICTION_COLUMNS)


def _fetch_range(
    *,
    client: CapitalRestClient,
    epic: str,
    resolution: str,
    price_side: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    chunk_points: int,
) -> pd.DataFrame:
    minutes = resolution_minutes(resolution)
    interval = pd.Timedelta(minutes=minutes)
    fetch_end = pd.to_datetime(end, utc=True) + interval
    cursor = pd.to_datetime(start, utc=True)
    frames: list[pd.DataFrame] = []
    while cursor < fetch_end:
        chunk_end = min(cursor + (interval * max(1, int(chunk_points))), fetch_end)
        try:
            df = client.get_historical_prices(
                epic=epic,
                resolution=resolution,
                max_points=max(1, min(1000, int(chunk_points))),
                from_utc=capital_time(cursor),
                to_utc=capital_time(chunk_end),
                price_side=price_side,
                save_outputs=False,
                min_rows=1,
            )
        except KronosMappingError as exc:
            text = str(exc).lower()
            if "empty" in text or "at least" in text:
                df = _empty_frame()
            else:
                raise
        except CapitalApiError as exc:
            if "error.invalid.daterange" in str(exc).lower():
                df = _empty_frame()
            else:
                raise
        if not df.empty:
            frames.append(df)
        cursor = chunk_end
    if not frames:
        return _empty_frame()
    combined = pd.concat(frames, ignore_index=True)
    combined["timestamps"] = pd.to_datetime(combined["timestamps"], utc=True)
    combined = combined.sort_values("timestamps").drop_duplicates("timestamps", keep="last").reset_index(drop=True)
    return combined


def ensure_historical_candles(
    *,
    client: CapitalRestClient,
    selected_market: dict[str, Any],
    symbol: str,
    resolution: str = "MINUTE_5",
    price_side: str = "mid",
    days: int = 35,
    chunk_points: int = 900,
    source: str = "historical",
    dsn: str | None = None,
    now: pd.Timestamp | None = None,
    cap_to_latest_available: bool = True,
) -> HistoricalBackfillSummary:
    epic = str(selected_market["epic"])
    market_name = str(selected_market.get("instrumentName") or "")
    latest_df = _empty_frame()
    if cap_to_latest_available and now is None:
        latest_df = latest_available_frame(
            client=client,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            max_points=chunk_points,
        )
        if latest_df.empty:
            raise RuntimeError(f"Capital.com returned no latest {resolution} candles for {epic}")
        now = pd.to_datetime(latest_df["timestamps"].iloc[-1], utc=True)
    start, end = history_window(days=days, resolution=resolution, now=now)
    upsert_instrument(
        symbol=symbol,
        epic=epic,
        market_name=market_name,
        price_side=price_side,
        metadata=selected_market,
        dsn=dsn,
    )
    fetched_rows = 0
    upserted_rows = 0
    if not latest_df.empty:
        latest_df = latest_df.copy()
        latest_df["timestamps"] = pd.to_datetime(latest_df["timestamps"], utc=True)
        latest_df = latest_df[(latest_df["timestamps"] >= start) & (latest_df["timestamps"] <= end)]
        if not latest_df.empty:
            fetched_rows += len(latest_df)
            upserted_rows += upsert_ohlcv_df(
                latest_df,
                symbol=symbol,
                epic=epic,
                resolution=resolution,
                price_side=price_side,
                source=source,
                dsn=dsn,
            )
    expected = expected_timestamps(start, end, resolution)
    existing = _load_existing_timestamps(
        symbol=symbol,
        epic=epic,
        resolution=resolution,
        price_side=price_side,
        start=start,
        end=end,
        dsn=dsn,
    )
    missing_ranges = missing_timestamp_ranges(existing=existing, start=start, end=end, resolution=resolution)
    for range_start, range_end in missing_ranges:
        df = _fetch_range(
            client=client,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            start=range_start,
            end=range_end,
            chunk_points=chunk_points,
        )
        if df.empty:
            continue
        fetched_rows += len(df)
        upserted_rows += upsert_ohlcv_df(
            df,
            symbol=symbol,
            epic=epic,
            resolution=resolution,
            price_side=price_side,
            source=source,
            dsn=dsn,
        )

    return HistoricalBackfillSummary(
        symbol=symbol,
        epic=epic,
        resolution=resolution,
        price_side=price_side,
        window_start_utc=start.isoformat(),
        window_end_utc=end.isoformat(),
        expected_rows=len(expected),
        existing_rows=len(existing),
        missing_rows=max(0, len(expected) - len(existing)),
        missing_ranges=len(missing_ranges),
        fetched_rows=fetched_rows,
        upserted_rows=upserted_rows,
        source=source,
    )
