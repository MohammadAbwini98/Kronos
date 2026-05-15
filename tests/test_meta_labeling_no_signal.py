from __future__ import annotations

import pandas as pd

from gold_analyzer.meta_labeling import clean_non_trade_label, filter_meta_training_rows, label_from_return
from src.forecast_scoring import score_trade_signal_outcome


def _actual(close: float = 101.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamps": pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC"),
            "open": [100.0, 100.0],
            "high": [100.4, close],
            "low": [99.8, min(100.0, close)],
            "close": [100.0, close],
        }
    )


def test_no_signal_is_not_labeled() -> None:
    row = clean_non_trade_label({"signal": "NO_SIGNAL", "outcome": "WIN", "pnl": 10.0})

    assert row["is_trade_signal"] is False
    assert row["outcome"] is None
    assert label_from_return("NO_SIGNAL", 0.05) is None


def test_no_signal_is_not_used_for_meta_training() -> None:
    rows = filter_meta_training_rows(
        [
            {"signal": "NO_SIGNAL", "outcome": "WIN", "is_trade_signal": False},
            {"signal": "BUY", "outcome": "WIN", "is_trade_signal": True},
        ]
    )

    assert rows == [{"signal": "BUY", "outcome": "WIN", "is_trade_signal": True}]


def test_unknown_signal_is_skipped_by_labeler() -> None:
    outcome = score_trade_signal_outcome(
        signal="UNKNOWN",
        entry_price=100.0,
        tp_price=101.0,
        sl_price=99.0,
        actual_df=_actual(102.0),
        forecast_end_timestamp_utc="2026-01-01T00:05:00Z",
    )

    assert outcome["status"] in {"GOOD_HOLD", "MISSED_MOVE"}
    assert outcome["status"] not in {"WIN", "LOSS"}
    assert label_from_return("UNKNOWN", -0.05) is None


def test_buy_label_uses_positive_return() -> None:
    assert label_from_return("BUY", 0.01, cost_frac=0.0) == "WIN"
    assert label_from_return("BUY", -0.01, cost_frac=0.0) == "LOSS"


def test_sell_label_uses_negative_return() -> None:
    assert label_from_return("SELL", -0.01, cost_frac=0.0) == "WIN"
    assert label_from_return("SELL", 0.01, cost_frac=0.0) == "LOSS"
