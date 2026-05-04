from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_ui


class DashboardUiContractTests(unittest.TestCase):
    def test_baselines_button_id_is_unique_and_not_shared_with_panel(self):
        html = dashboard_ui.dashboard_html()

        self.assertEqual(1, html.count('id="runBaselines"'))
        self.assertEqual(1, html.count('id="baselines"'))
        self.assertIn("$('runBaselines').addEventListener('click'", html)

    def test_action_payloads_include_symbol_and_resolution_context(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("function actionContextPayload(extra = {})", html)
        self.assertIn("symbol: $('market').value || 'ETHUSD'", html)
        self.assertIn("resolution: $('resolution').value || 'MINUTE_5'", html)
        self.assertIn("postJson('/api/fetch-actual', actionContextPayload()", html)
        self.assertIn("postJson('/api/validate-actual', actionContextPayload({ scoring_version: 'v1' })", html)
        self.assertIn("postJson('/api/baselines', actionContextPayload()", html)


if __name__ == "__main__":
    unittest.main()
