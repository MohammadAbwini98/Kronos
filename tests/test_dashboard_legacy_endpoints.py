from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server


def test_existing_dashboard_endpoints_still_work(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_server, "_postgres_snapshot", lambda symbol, resolution: {"candles": [], "live_quote": {}})
    expected = {
        "/api/snapshot",
        "/api/corr",
        "/api/lagcorr",
        "/api/rolling",
        "/api/signals/history",
        "/api/calibration",
        "/api/equity",
        "/api/candles",
        "/api/price",
        "/api/meta",
        "/api/health",
        "/api/notify/test",
    }

    assert expected.issubset(dashboard_server.LEGACY_GET_ENDPOINTS)
    assert dashboard_server._legacy_dashboard_payload("/api/health", {})["ok"] is True
    assert "rows" in dashboard_server._legacy_dashboard_payload("/api/corr", {})


def test_dashboard_empty_states_do_not_crash(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_server, "_postgres_snapshot", lambda symbol, resolution: {"candles": [], "live_quote": None})

    assert dashboard_server._legacy_dashboard_payload("/api/candles", {})["rows"] == []
    assert dashboard_server._legacy_dashboard_payload("/api/price", {})["row"] == {}
