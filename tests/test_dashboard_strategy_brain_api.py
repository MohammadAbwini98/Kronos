from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server
import gold_analyzer.repositories as repositories


class _StrategyDecisionRepo:
    def list_latest(self, *, symbol, timeframe, limit):
        return {
            "rows": [
                {
                    "id": 101,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "computed_at": "2026-05-14T00:00:00Z",
                    "signal": "BUY",
                    "strategy_type": "trend_pullback",
                    "regime": "TREND_UP",
                    "decision_status": "APPROVED",
                    "reason": "STRATEGY_CANDIDATE_APPROVED",
                    "blocked_by": [],
                    "position_size": 1.25,
                    "risk_score": 87.5,
                    "indicators_json": {"ATR_14": 2.0},
                    "risk_json": {"approved": True, "details": {"risk_per_trade": 0.005, "stop_distance_atr": 1.0}},
                    "ai_json": {"status": "SUPPORTED"},
                }
            ]
            * max(1, int(limit))
        }


class _AISupportRepo:
    def list_for_decision(self, decision_id):
        return {"rows": [{"strategy_decision_id": decision_id, "model_key": "kronos", "support_value": 1.0}]}


class _StrategyPerformanceRepo:
    def list_latest(self, *, symbol, timeframe, limit):
        return {"rows": [{"symbol": symbol, "timeframe": timeframe, "limit": limit, "profit_factor": 1.4}]}


class _EmptyStrategyPerformanceRepo:
    saved_summary = None

    def list_latest(self, *, symbol, timeframe, limit):
        if self.saved_summary:
            return {"rows": [{**self.saved_summary, "id": 123, "details_json": self.saved_summary.get("details")}]}
        return {"rows": []}

    def executed_trade_summary(self, *, symbol, timeframe):
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_type": "executed_trade_proxy",
            "lookback_trades": 4,
            "win_rate": 0.25,
            "profit_factor": 0.5,
            "expectancy": -0.1,
            "details": {
                "source": "executed_trades",
                "approved_for_paper": False,
                "approval_gates": [{"gate_name": "minimum_profit_factor", "status": "FAIL"}],
            },
        }

    def save_summary(self, summary):
        type(self).saved_summary = dict(summary)
        return 123


def test_strategy_brain_latest_and_history_payloads_use_query_context(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "StrategyDecisionRepository", _StrategyDecisionRepo)

    latest = dashboard_server._strategy_brain_latest_payload({"symbol": ["GOLD"], "tf": ["5m"]})
    history = dashboard_server._strategy_brain_history_payload({"symbol": ["GOLD"], "resolution": ["MINUTE_5"], "limit": ["3"]})

    assert latest["row"]["symbol"] == "GOLD"
    assert latest["row"]["timeframe"] == "5m"
    assert history["rows"][0]["timeframe"] == "5m"
    assert len(history["rows"]) == 3


def test_strategy_brain_ai_support_payload_uses_decision_id(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "AISupportRepository", _AISupportRepo)

    payload = dashboard_server._strategy_brain_ai_support_payload(123)

    assert payload["decision_id"] == 123
    assert payload["rows"] == [{"strategy_decision_id": 123, "model_key": "kronos", "support_value": 1.0}]


def test_strategy_brain_performance_payload_uses_query_context(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "StrategyPerformanceRepository", _StrategyPerformanceRepo)

    payload = dashboard_server._strategy_brain_performance_payload({"epic": ["XAUUSD"], "tf": ["1h"], "limit": ["2"]})

    assert payload["rows"] == [{"symbol": "XAUUSD", "timeframe": "1h", "limit": 2, "profit_factor": 1.4}]


def test_strategy_brain_performance_bootstraps_from_executed_trades_when_empty(monkeypatch) -> None:
    _EmptyStrategyPerformanceRepo.saved_summary = None
    monkeypatch.setattr(repositories, "StrategyPerformanceRepository", _EmptyStrategyPerformanceRepo)

    payload = dashboard_server._strategy_brain_performance_payload({"epic": ["XAUUSD"], "tf": ["5m"], "limit": ["2"]})

    assert payload["source"] == "executed_trades_bootstrap"
    assert payload["rows"][0]["strategy_type"] == "executed_trade_proxy"
    assert payload["rows"][0]["details_json"]["source"] == "executed_trades"
    assert payload["rows"][0]["details_json"]["approval_gates"][0]["status"] == "FAIL"


def test_strategy_brain_regime_and_risk_state_payloads_use_latest_decision(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "StrategyDecisionRepository", _StrategyDecisionRepo)

    regime_payload = dashboard_server._strategy_brain_regime_payload({"symbol": ["GOLD"], "tf": ["5m"]})
    risk_payload = dashboard_server._strategy_brain_risk_state_payload({"symbol": ["GOLD"], "tf": ["5m"]})

    assert regime_payload["row"]["regime"] == "TREND_UP"
    assert regime_payload["row"]["decision_id"] == 101
    assert risk_payload["row"]["risk_state"] == "APPROVED"
    assert risk_payload["row"]["risk_per_trade"] == 0.005
    assert risk_payload["row"]["stop_distance_atr"] == 1.0
