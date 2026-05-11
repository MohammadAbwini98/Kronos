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
    def test_apple_inspired_design_tokens_are_present(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("--font-ui: -apple-system", html)
        self.assertIn("color-scheme: light", html)
        self.assertIn("@media (prefers-color-scheme: dark)", html)
        self.assertIn("backdrop-filter: saturate(180%) blur(22px)", html)
        self.assertIn("--focus-ring:", html)
        self.assertIn("Apple-inspired visual system override", html)

    def test_primary_dashboard_controls_keep_expected_ids(self):
        html = dashboard_ui.dashboard_html()

        for control_id in (
            "market",
            "resolution",
            "predLen",
            "lookback",
            "featureSet",
            "autoRefresh",
            "repairOhlc",
            "autoPredict",
            "predict",
            "refresh",
            "fetchActual",
            "validateActual",
            "runBaselines",
            "closeChart",
            "candleChart",
            "toast",
            "loader",
        ):
            self.assertIn(f'id="{control_id}"', html)

    def test_tab_buttons_and_panels_stay_mapped(self):
        html = dashboard_ui.dashboard_html()

        for tab_id in (
            "overview",
            "validation",
            "modelPerformance",
            "risk",
            "trades",
            "baselines",
            "history",
            "files",
            "logs",
            "report",
        ):
            self.assertIn(f'data-tab="{tab_id}"', html)
            self.assertIn(f'id="{tab_id}"', html)

        self.assertIn("document.querySelectorAll('.tab').forEach", html)
        self.assertIn("setTab(button.dataset.tab)", html)

    def test_signal_table_actions_keep_event_delegation_hooks(self):
        html = dashboard_ui.dashboard_html()

        for hook in (
            "data-copy=",
            "data-copy-label=",
            "data-audit-run=",
            "data-signal-page=",
            "signalsApply",
            "signalsReset",
            "signalsFirst",
            "signalsPrev",
            "signalsNext",
            "signalsLast",
            "signalsPageSize",
        ):
            self.assertIn(hook, html)

        self.assertIn("target.dataset.copy", html)
        self.assertIn("target.dataset.auditRun", html)
        self.assertIn("target.closest('[data-signal-page]')", html)

    def test_fetch_endpoints_remain_wired_to_expected_helpers(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("fetch(`/api/status?${currentStatusQuery()}`", html)
        self.assertIn("fetch(`/api/model-performance?${currentStatusQuery()}`", html)
        self.assertIn("fetch(`/api/signals?${getSignalQuery(page)}`", html)
        self.assertIn("postJson('/api/predict'", html)
        self.assertIn("postJson('/api/fetch-actual'", html)
        self.assertIn("postJson('/api/validate-actual'", html)
        self.assertIn("postJson('/api/baselines'", html)

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

    def test_validation_direction_falls_back_to_signal_validation_payload(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("['Direction', v.forecast_direction || sv.forecast_direction || 'n/a']", html)

    def test_validation_metrics_include_explicit_pending_outcome_reason(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("const metricPendingLabel = source === 'none'", html)
        self.assertIn("'n/a (waiting for WIN/LOSS outcomes)'", html)
        self.assertIn("['Metrics status', metricsStatusNote]", html)

    def test_score_breakdown_includes_blocked_reason_hint(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("All component scores are 0.00 because this run is BLOCKED", html)
        self.assertIn("${scoreStatusHtml}", html)

    def test_validation_banner_states_and_markup_are_present(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn(".validation-banner {", html)
        self.assertIn("const validationHealth = blockedSignal", html)
        self.assertIn("title: 'Validation blocked'", html)
        self.assertIn("title: 'Awaiting matched outcomes'", html)
        self.assertIn("title: 'Validation healthy'", html)
        self.assertIn("${validationBannerHtml}", html)

    def test_executed_signals_tab_uses_single_filtered_table(self):
        html = dashboard_ui.dashboard_html()

        for hook in (
            "tradeLifecycleFilter",
            "tradeDateFromFilter",
            "tradeDateToFilter",
            "tradeStatusFilter",
            "tradeOutcomeFilter",
            "tradeSideFilter",
            "tradeSignalFilter",
            "tradeTransactionFilter",
            "tradeApply",
            "tradeReset",
            "normalizeTradeExecutionRows",
            "filterTradeExecutionRows",
            "tradeExecutionTableRows",
            "tradeExecutionReason",
            "tradeTransactionText",
            "tradeOutcomeHtml",
            "tradeOutcomeCounts",
            "formatSignedCount",
            "buildTradePaginationButtons",
            "data-trade-page",
            "tradePrev",
            "tradeNext",
        ):
            self.assertIn(hook, html)

        self.assertIn("Capital.com demo executions, queue requests, transaction IDs, and historical outcomes in one filtered table.", html)
        self.assertIn("<th>Signal Status</th>", html)
        self.assertIn("<th>Broker / Queue Ref</th>", html)
        self.assertIn("<th>Transaction ID</th>", html)
        self.assertIn("<th>Outcome</th>", html)
        self.assertIn("Executed Win Rate", html)
        self.assertIn("Closed finalized executed trades only", html)
        self.assertIn("Total Net P/L", html)
        self.assertIn("Expectancy", html)
        self.assertIn("Average Win", html)
        self.assertIn("Average Loss", html)
        self.assertIn("Drawdown", html)
        self.assertIn("Spread Impact", html)
        self.assertIn("Slippage Impact", html)
        self.assertIn("Finalization Pending", html)
        self.assertIn("Execution Decision Reasons", html)
        self.assertIn("<th>Date / Time</th>", html)
        self.assertIn("Dates are interpreted in Asia/Amman timezone.", html)
        self.assertIn("net_expected_edge_pct", html)
        self.assertIn("TRADE_EXECUTION_PAGE_SIZE = 10", html)
        self.assertIn("row.trade_outcome", html)
        self.assertIn("tradeExecutionFilters.outcome", html)
        self.assertIn("tradeExecutionFilters.dateFrom", html)
        self.assertIn("tradeExecutionFilters.dateTo", html)
        self.assertIn("All outcomes", html)
        self.assertIn("row.transaction_id", html)
        self.assertIn("tradeExecutionFilters.transactionId", html)
        self.assertIn("transaction_lookup_error", html)
        self.assertIn("row.signal_status || 'UNKNOWN'", html)
        self.assertIn("Broker lookup blocked", html)
        self.assertIn("Awaiting broker outcome", html)
        self.assertIn("not evaluated", html)
        self.assertIn("not filled", html)
        self.assertIn("MarketNotTradeableError", html)
        self.assertIn("Retry scheduled", html)
        self.assertNotIn("data-fetch-transaction", html)
        self.assertNotIn("Fetching transaction history...", html)
        self.assertNotIn("Current Active Executed Trades", html)
        self.assertNotIn("Pending And Submitted Trades", html)
        self.assertNotIn("<h3 style=\"margin-top: 14px;\">Execution Queue</h3>", html)
        self.assertNotIn("<h3 style=\"margin-top: 14px;\">Historical Trades</h3>", html)


if __name__ == "__main__":
    unittest.main()
