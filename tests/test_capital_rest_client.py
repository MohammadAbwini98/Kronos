from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from capital_rest_client import CapitalRestClient


class MarketSelectionTests(unittest.TestCase):
    def test_select_best_market_prefers_exact_requested_epic(self):
        candidates = [
            {
                "epic": "ETHWUSD",
                "instrumentName": "ETHW/USD",
                "marketStatus": "TRADEABLE",
                "streamingPricesAvailable": True,
            },
            {
                "epic": "ETHUSD",
                "instrumentName": "ETH/USD",
                "marketStatus": "TRADEABLE",
                "streamingPricesAvailable": True,
            },
        ]

        selected = CapitalRestClient._select_best_market(candidates, streaming=True, requested="ETHUSD")

        self.assertEqual("ETHUSD", selected["epic"])

    def test_select_best_market_keeps_exact_match_even_if_non_streaming(self):
        candidates = [
            {
                "epic": "ETHUSD",
                "instrumentName": "ETH/USD",
                "marketStatus": "TRADEABLE",
                "streamingPricesAvailable": False,
            },
            {
                "epic": "ETHUSDX",
                "instrumentName": "ETH/USD CFD",
                "marketStatus": "TRADEABLE",
                "streamingPricesAvailable": True,
            },
        ]

        selected = CapitalRestClient._select_best_market(candidates, streaming=True, requested="ETHUSD")

        self.assertEqual("ETHUSD", selected["epic"])


if __name__ == "__main__":
    unittest.main()
