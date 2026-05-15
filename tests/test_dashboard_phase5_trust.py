from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server  # noqa: E402
import dashboard_ui  # noqa: E402


def _payload() -> dict:
    metadata = {
        "generated_at_utc": "2026-05-09T12:00:00+00:00",
        "input_rows_used": 512,
        "forecast_rows": 12,
        "feature_mode": "OHLCV_ONLY",
        "amount_available": False,
        "input_quality_snapshot": {
            "requested_lookback": 512,
            "actual_lookback": 512,
            "missing_candle_count": 0,
            "largest_gap_minutes": 5,
            "source_counts": {"latest_fetch": 512},
            "amount_available": False,
            "feature_mode": "OHLCV_ONLY",
            "last_timestamp_utc": "2026-05-09T11:55:00+00:00",
            "strict_policy_passed": True,
        },
    }
    validation = {
        "matched_candles": 6,
        "direction_accuracy_pct": 66.6,
        "quality_status": "PARTIAL_PROGRESS",
        "mae": 1.2,
        "rmse": 1.4,
        "mape_pct": 0.5,
    }
    postgres = {
        "horizon_metrics": [{"horizon_index": 1, "samples": 2, "wins": 1, "losses": 1, "direction_accuracy_pct": 50.0}],
        "prediction_db": {
            "metric_categories": {
                "forecast_quality": {
                    "directional_forecast_hit_rate_pct": 70.0,
                    "wins": 7,
                    "losses": 3,
                    "pending": 2,
                },
                "signal_quality": {
                    "distributions": [
                        {"signal": "LONG", "status": "PENDING", "validation_status": "BLOCKED", "count": 2, "average_validation_score": 20.0, "mismatch_count": 2},
                        {"signal": "SHORT", "status": "WIN", "validation_status": "SHORT", "count": 1, "average_validation_score": 80.0, "mismatch_count": 0},
                    ],
                    "raw_signal_validation_mismatch_count": 2,
                },
                "executed_trade_performance": {
                    "wins": 1,
                    "losses": 1,
                    "closed_trade_count": 3,
                    "finalized_trade_count": 2,
                    "unknown_outcome_count": 1,
                    "executed_trade_win_rate_pct": 50.0,
                    "total_net_pnl": 4.0,
                    "expectancy": 2.0,
                    "average_win": 10.0,
                    "average_loss": -6.0,
                    "average_spread_cost": 0.2,
                    "average_slippage_estimate": 0.1,
                },
                "baseline_comparisons": {"rows": [{"baseline_name": "naive_momentum", "model_metric": 70.0, "baseline_metric": 50.0, "delta": 20.0, "sample_count": 10, "enough_samples": False}]},
            }
        },
    }
    trade_execution = {
        "trades": [
            {"status": "CLOSED", "outcome_finalized_at": "2026-05-09T12:10:00+00:00", "net_pnl": 10.0, "closed_at": "2026-05-09T12:10:00+00:00"},
            {"status": "CLOSED", "outcome_finalized_at": "2026-05-09T12:20:00+00:00", "net_pnl": -6.0, "closed_at": "2026-05-09T12:20:00+00:00"},
            {"status": "OPEN", "net_pnl": 999.0},
        ],
        "execution_decisions": [
            {
                "signal_id": "sig-block",
                "raw_signal": "LONG",
                "execution_decision": "BLOCK",
                "block_reason": "VALIDATION_STATUS_BLOCKED:WATCH",
                "validation_status": "WATCH",
                "validation_score": 42.0,
                "net_expected_edge_pct": -0.02,
                "spread_pct": 0.04,
                "estimated_fee_pct": 0.0,
                "estimated_slippage_pct": 0.02,
            }
        ],
    }
    return dashboard_server._dashboard_trust_payload(
        metadata=metadata,
        validation_body=validation,
        postgres_snapshot=postgres,
        trade_execution=trade_execution,
        baseline_summary={},
    )


class DashboardPhase5TrustTests(unittest.TestCase):
    def test_forecast_hit_rate_does_not_appear_as_executed_win_rate(self):
        trust = _payload()

        self.assertEqual(70.0, trust["forecast_quality"]["directional_forecast_hit_rate_pct"])
        self.assertEqual(50.0, trust["executed_trade_performance"]["executed_trade_win_rate_pct"])
        self.assertIn("not executed-trade win rate", trust["forecast_quality"]["metric_definition"])

    def test_executed_win_rate_ignores_non_closed_trades(self):
        trust = _payload()

        perf = trust["executed_trade_performance"]
        self.assertEqual(3, perf["closed_trade_count"])
        self.assertEqual(2, perf["finalized_trade_count"])
        self.assertEqual(1, perf["unknown_outcome_count"])
        self.assertEqual(50.0, perf["executed_trade_win_rate_pct"])
        self.assertEqual(-6.0, perf["max_drawdown"])

    def test_partial_validation_is_labeled_partial(self):
        trust = _payload()

        self.assertEqual("PARTIAL", trust["forecast_quality"]["partial_or_final"])
        self.assertFalse(trust["forecast_quality"]["actual_future_horizon_complete"])
        self.assertEqual("PARTIAL", trust["latest_state"]["validation_partial_or_final"])

    def test_lookback_requested_actual_values_are_exposed(self):
        trust = _payload()

        health = trust["data_input_health"]
        self.assertEqual(512, health["requested_lookback"])
        self.assertEqual(512, health["actual_lookback"])
        self.assertEqual(512, health["actual_rows_used"])
        self.assertEqual(512, health["max_supported_lookback"])
        self.assertTrue(health["lookback_honored"])

    def test_blocked_execution_reason_is_visible(self):
        trust = _payload()

        row = trust["execution_decision_reasons"]["rows"][0]
        self.assertEqual("BLOCK", row["execution_decision"])
        self.assertEqual("VALIDATION_STATUS_BLOCKED:WATCH", row["block_reason"])
        self.assertEqual("WATCH", row["validation_status"])

    def test_dashboard_labels_are_trust_separated(self):
        html = dashboard_ui.dashboard_html()

        self.assertIn("Directional Forecast Hit Rate", html)
        self.assertIn("Executed Win Rate", html)
        self.assertIn("Signal Quality", html)
        self.assertIn("Data/Input Health", html)
        self.assertIn("Execution Decision Reasons", html)
        self.assertNotIn("kpi('Win Rate'", html)
        self.assertNotIn("Prediction Accuracy", html)


if __name__ == "__main__":
    unittest.main()
