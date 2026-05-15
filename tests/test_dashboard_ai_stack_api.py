from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server
import gold_analyzer.db.repositories as repositories


class _ForecastRepo:
    def list_forecasts(self, *, epic, timeframe, limit):
        return {"runs": [{"epic": epic, "timeframe": timeframe, "limit": limit}], "forecasts": []}

    def list_ensemble(self, *, epic, timeframe, limit):
        return {"rows": [{"epic": epic, "timeframe": timeframe, "limit": limit}]}


class _ValidationRepo:
    def list_regime(self, *, epic, timeframe, limit):
        return {"rows": [{"kind": "regime", "epic": epic, "timeframe": timeframe, "limit": limit}]}

    def list_validation(self, *, epic, timeframe, limit):
        return {"rows": [{"kind": "validation", "epic": epic, "timeframe": timeframe, "limit": limit}]}


class _ScoreRepo:
    def list_scores(self, *, epic, timeframe, limit):
        return {"rows": [{"kind": "score", "epic": epic, "timeframe": timeframe, "limit": limit}]}


def test_ai_forecast_payload_uses_query_context(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "ForecastRepository", _ForecastRepo)

    payload = dashboard_server._ai_forecasts_payload(
        {"epic": ["GOLD"], "timeframe": ["MINUTE_5"], "limit": ["5"]}
    )

    assert payload["runs"] == [{"epic": "GOLD", "timeframe": "MINUTE_5", "limit": 5}]


def test_ai_ensemble_payload_uses_query_context(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "ForecastRepository", _ForecastRepo)

    payload = dashboard_server._ai_ensemble_payload(
        {"symbol": ["GOLD"], "resolution": ["MINUTE_5"], "limit": ["3"]}
    )

    assert payload["rows"] == [{"epic": "GOLD", "timeframe": "MINUTE_5", "limit": 3}]


def test_ai_payload_accepts_plan_tf_query(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "ForecastRepository", _ForecastRepo)

    payload = dashboard_server._ai_forecasts_payload({"symbol": ["XAUUSD"], "tf": ["5m"], "limit": ["7"]})

    assert payload["runs"] == [{"epic": "XAUUSD", "timeframe": "MINUTE_5", "limit": 7}]


def test_ai_regime_scorer_and_validation_payloads_use_query_context(monkeypatch) -> None:
    monkeypatch.setattr(repositories, "ValidationRepository", _ValidationRepo)
    monkeypatch.setattr(repositories, "SignalScoreRepository", _ScoreRepo)

    query = {"symbol": ["XAUUSD"], "tf": ["1h"], "limit": ["2"]}

    assert dashboard_server._ai_regime_payload(query)["rows"] == [
        {"kind": "regime", "epic": "XAUUSD", "timeframe": "HOUR", "limit": 2}
    ]
    assert dashboard_server._ai_scorer_payload(query)["rows"] == [
        {"kind": "score", "epic": "XAUUSD", "timeframe": "HOUR", "limit": 2}
    ]
    assert dashboard_server._ai_forecast_validation_payload(query)["rows"] == [
        {"kind": "validation", "epic": "XAUUSD", "timeframe": "HOUR", "limit": 2}
    ]
