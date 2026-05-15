from __future__ import annotations

import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dashboard_server


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class DashboardPathContainmentTests(unittest.TestCase):
    def test_resolve_path_within_root_accepts_in_tree_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "output" / "ok.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("ok", encoding="utf-8")

            with patch.object(dashboard_server, "ROOT", root):
                resolved = dashboard_server._resolve_path_within_root("output/ok.txt")

        self.assertEqual(target.resolve(), resolved)

    def test_resolve_path_within_root_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            outside = Path(temp_dir) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")

            with patch.object(dashboard_server, "ROOT", root):
                with self.assertRaises(ValueError):
                    dashboard_server._resolve_path_within_root("../outside.txt")


class MetadataContextTests(unittest.TestCase):
    def test_metadata_lookup_uses_selected_symbol_resolution_when_run_missing(self):
        with patch.object(dashboard_server, "_latest_metadata", return_value=(None, {})) as mocked_latest:
            dashboard_server._metadata_for_run_id(None, symbol="BTCUSD", resolution="HOUR")

        mocked_latest.assert_called_once_with("BTCUSD", "HOUR")

    def test_metadata_lookup_rejects_context_mismatch_for_run_id(self):
        fake_row = {"metadata_path": "output/forecast_metadata_ETHUSD_MINUTE_1.json"}
        fake_metadata = {"epic": "ETHUSD", "resolution": "MINUTE"}

        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(dashboard_server, "connect", return_value=_FakeConnection(fake_row)))
            _stack.enter_context(patch.object(dashboard_server, "_safe_json", return_value=fake_metadata))
            path, metadata = dashboard_server._metadata_for_run_id(
                "run-123",
                symbol="BTCUSD",
                resolution="MINUTE",
            )

        self.assertIsNone(path)
        self.assertEqual({}, metadata)

    def test_metadata_lookup_accepts_matching_context_for_run_id(self):
        fake_row = {"metadata_path": "output/forecast_metadata_ETHUSD_MINUTE_1.json"}
        fake_metadata = {"epic": "ETHUSD", "resolution": "MINUTE"}

        with contextlib.ExitStack() as _stack:
            _stack.enter_context(patch.object(dashboard_server, "connect", return_value=_FakeConnection(fake_row)))
            _stack.enter_context(patch.object(dashboard_server, "_safe_json", return_value=fake_metadata))
            _stack.enter_context(patch.object(dashboard_server, "ROOT", ROOT))
            path, metadata = dashboard_server._metadata_for_run_id(
                "run-123",
                symbol="ethusd",
                resolution="minute",
            )

        self.assertIsNotNone(path)
        self.assertEqual("ETHUSD", metadata["epic"])


class ActionContextValidationTests(unittest.TestCase):
    def test_action_context_defaults(self):
        symbol, resolution = dashboard_server._action_context({})
        self.assertEqual("XAUUSD", symbol)
        self.assertEqual("MINUTE_5", resolution)

    def test_action_context_rejects_invalid_resolution(self):
        with self.assertRaises(ValueError):
            dashboard_server._action_context({"symbol": "ETHUSD", "resolution": "BAD"})


if __name__ == "__main__":
    unittest.main()
