from __future__ import annotations

import pandas as pd


class LeakageError(ValueError):
    """Raised when features appear to use future rows."""


def assert_monotonic_timestamps(frame: pd.DataFrame) -> None:
    if "timestamps" not in frame.columns:
        return
    ts = pd.to_datetime(frame["timestamps"], utc=True)
    if not ts.is_monotonic_increasing:
        raise LeakageError("Feature input timestamps must be sorted ascending")


def assert_no_future_timestamps(features: pd.DataFrame, source: pd.DataFrame) -> None:
    if "timestamps" not in features.columns or "timestamps" not in source.columns:
        return
    feature_ts = pd.to_datetime(features["timestamps"], utc=True)
    source_ts = pd.to_datetime(source["timestamps"], utc=True)
    if len(feature_ts) != len(source_ts):
        raise LeakageError("Feature row count changed during feature building")
    if (feature_ts.reset_index(drop=True) != source_ts.reset_index(drop=True)).any():
        raise LeakageError("Feature timestamps no longer align with source candles")
