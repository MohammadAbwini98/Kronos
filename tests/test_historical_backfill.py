from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import historical_backfill


def _df(*timestamps: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamps": pd.to_datetime(list(timestamps), utc=True),
            "open": [100.0 + i for i, _ in enumerate(timestamps)],
            "high": [101.0 + i for i, _ in enumerate(timestamps)],
            "low": [99.0 + i for i, _ in enumerate(timestamps)],
            "close": [100.5 + i for i, _ in enumerate(timestamps)],
            "volume": [1.0 for _ in timestamps],
            "amount": [0.0 for _ in timestamps],
        }
    )


class HistoricalBackfillTests(unittest.TestCase):
    def test_missing_timestamp_ranges_groups_contiguous_5m_gaps(self):
        start = pd.Timestamp("2026-05-01T00:00:00Z")
        end = pd.Timestamp("2026-05-01T00:20:00Z")
        existing = [
            pd.Timestamp("2026-05-01T00:00:00Z"),
            pd.Timestamp("2026-05-01T00:10:00Z"),
        ]

        ranges = historical_backfill.missing_timestamp_ranges(
            existing=existing,
            start=start,
            end=end,
            resolution="MINUTE_5",
        )

        self.assertEqual(
            [
                (pd.Timestamp("2026-05-01T00:05:00Z"), pd.Timestamp("2026-05-01T00:05:00Z")),
                (pd.Timestamp("2026-05-01T00:15:00Z"), pd.Timestamp("2026-05-01T00:20:00Z")),
            ],
            ranges,
        )

    def test_ensure_historical_candles_fetches_only_missing_ranges(self):
        start = pd.Timestamp("2026-05-01T00:00:00Z")
        end = pd.Timestamp("2026-05-01T00:20:00Z")
        selected_market = {"epic": "ETHUSD", "instrumentName": "Ethereum/USD"}

        with (
            patch("historical_backfill.history_window", return_value=(start, end)),
            patch(
                "historical_backfill._load_existing_timestamps",
                return_value=[
                    pd.Timestamp("2026-05-01T00:00:00Z"),
                    pd.Timestamp("2026-05-01T00:10:00Z"),
                ],
            ),
            patch("historical_backfill.upsert_instrument") as upsert_instrument,
            patch(
                "historical_backfill._fetch_range",
                side_effect=[
                    _df("2026-05-01T00:05:00Z"),
                    _df("2026-05-01T00:15:00Z", "2026-05-01T00:20:00Z"),
                ],
            ) as fetch_range,
            patch("historical_backfill.upsert_ohlcv_df", side_effect=lambda df, **_: len(df)) as upsert_ohlcv,
        ):
            summary = historical_backfill.ensure_historical_candles(
                client=object(),
                selected_market=selected_market,
                symbol="ETHUSD",
                resolution="MINUTE_5",
                price_side="mid",
                days=35,
                chunk_points=900,
                dsn=None,
                cap_to_latest_available=False,
            )

        upsert_instrument.assert_called_once()
        self.assertEqual(2, fetch_range.call_count)
        self.assertEqual(2, upsert_ohlcv.call_count)
        self.assertEqual(5, summary.expected_rows)
        self.assertEqual(2, summary.existing_rows)
        self.assertEqual(3, summary.missing_rows)
        self.assertEqual(2, summary.missing_ranges)
        self.assertEqual(3, summary.fetched_rows)
        self.assertEqual(3, summary.upserted_rows)


if __name__ == "__main__":
    unittest.main()
