from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import main_maintenance_worker


class MaintenanceBackfillMarketResolveTests(unittest.TestCase):
    def test_resolve_backfill_market_requires_epic_before_caching(self):
        args = argparse.Namespace(market="ETHUSD", epic=None)
        client = Mock()
        client.resolve_market.return_value = {}

        with patch("main_maintenance_worker.CapitalRestClient", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "Historical backfill market was not resolved"):
                main_maintenance_worker._resolve_backfill_market(object(), args)

        client.authenticate.assert_called_once()
        client.resolve_market.assert_called_once_with("ETHUSD", None, streaming=False)
        client.save_market_details.assert_not_called()

    def test_resolve_backfill_market_returns_client_and_selected_market(self):
        args = argparse.Namespace(market="ETHUSD", epic="ETHUSD")
        selected = {"epic": "ETHUSD", "instrumentName": "Ethereum/USD"}
        client = Mock()
        client.resolve_market.return_value = selected

        with patch("main_maintenance_worker.CapitalRestClient", return_value=client):
            resolved_client, resolved_market = main_maintenance_worker._resolve_backfill_market(object(), args)

        self.assertIs(client, resolved_client)
        self.assertEqual(selected, resolved_market)
        client.authenticate.assert_called_once()
        client.resolve_market.assert_called_once_with("ETHUSD", "ETHUSD", streaming=False)
        client.save_market_details.assert_called_once_with("ETHUSD")


if __name__ == "__main__":
    unittest.main()
