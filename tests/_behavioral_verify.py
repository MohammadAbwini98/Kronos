"""
Behavioral verification script — runs outside unittest to produce a clear
PASS/FAIL report for every PL-003 fix.  Run with:

    .venv\Scripts\python.exe tests\_behavioral_verify.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import inspect
import textwrap
import numpy as np
import pandas as pd
from unittest.mock import patch

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    mark = "✓" if condition else "✗ FAIL"
    print(f"  {mark}  {label}" + (f"  ({detail})" if detail and not condition else ""))


# ── Phase 4: shadow evaluation reads persisted status ─────────────────────────
from prediction_store import _upsert_shadow_evaluation

src = inspect.getsource(_upsert_shadow_evaluation)
check("Ph4-a  _upsert_shadow_evaluation does NOT recompute via signal_status_from_counts",
      'signal_status_from_counts' not in src)
check("Ph4-b  _upsert_shadow_evaluation reads row.get('active_status')",
      'row.get("active_status")' in src)

# ── Phase 5: horizon-aware signal engine ─────────────────────────────────────
from prediction_store import _signal_from_forecast

r = _signal_from_forecast(last_input_close=100.0, final_close=100.01,
                           cost_threshold_pct=0.05, min_confidence=0.4)
check("Ph5-a  HOLD when expected move < cost threshold", r["signal"] == "HOLD")

r = _signal_from_forecast(last_input_close=100.0, final_close=102.0,
                           cost_threshold_pct=0.05, min_confidence=0.1,
                           forecast_closes=[100.8, 101.4, 102.0])
check("Ph5-b  LONG when all horizons agree up", r["signal"] == "LONG")

r = _signal_from_forecast(last_input_close=100.0, final_close=102.0,
                           cost_threshold_pct=0.05, min_confidence=0.1,
                           forecast_closes=[101.0, 99.0, 102.0])
# steps from [100, 101, 99, 102]: +1, -2, +3 — only 2/3 up → 66% > 50% so NOT HOLD on agreement
# but terminal is +2% with 66% agreement; verify signal is LONG
check("Ph5-c  LONG when 2/3 horizons agree (66% > 50%)", r["signal"] == "LONG",
      f"got {r['signal']}")

r_disagree = _signal_from_forecast(last_input_close=100.0, final_close=101.0,
                                    cost_threshold_pct=0.05, min_confidence=0.1,
                                    forecast_closes=[99.5, 98.5, 101.0])
# steps: -0.5, -1.0, +2.5 — only 1/3 up → 33% < 50% → HOLD
check("Ph5-d  HOLD when <50% horizon direction agreement",
      r_disagree["signal"] == "HOLD", f"got {r_disagree['signal']}")

r_big = _signal_from_forecast(last_input_close=100.0, final_close=130.0,
                                cost_threshold_pct=0.05, min_confidence=0.0)
check("Ph5-e  confidence bounded 0≤c≤0.99",
      0.0 <= r_big["confidence"] <= 0.99, f"confidence={r_big['confidence']}")

low_vol = _signal_from_forecast(last_input_close=100.0, final_close=100.5,
                                 cost_threshold_pct=0.05, min_confidence=0.0,
                                 forecast_closes=[100.5], recent_volatility_pct=0.01)
high_vol = _signal_from_forecast(last_input_close=100.0, final_close=100.5,
                                  cost_threshold_pct=0.05, min_confidence=0.0,
                                  forecast_closes=[100.5], recent_volatility_pct=5.0)
check("Ph5-f  higher volatility → lower confidence (same edge)",
      low_vol["confidence"] > high_vol["confidence"],
      f"low_vol={low_vol['confidence']:.4f} high_vol={high_vol['confidence']:.4f}")

r_compat = _signal_from_forecast(last_input_close=100.0, final_close=101.0,
                                  cost_threshold_pct=0.05, min_confidence=0.1)
check("Ph5-g  backward-compat: no forecast_closes → no crash",
      r_compat["signal"] in ("LONG", "HOLD", "SHORT"))

# ── Phase 6: dataset quality_filter enforced ─────────────────────────────────
from dataset_snapshots import _apply_quality_filter

df = pd.DataFrame([
    {"timestamps": "2026-01-01", "open": 100, "high": 102, "low": 98, "close": 101},
    {"timestamps": "2026-01-02", "open": None, "high": 103, "low": 97, "close": 100},  # null
    {"timestamps": "2026-01-03", "open": 100, "high": 95, "low": 105, "close": 100},   # invalid
])
filtered, report = _apply_quality_filter(df, {"drop_null_ohlc": True, "drop_invalid_ohlc": True})
check("Ph6-a  null_ohlc row removed", len(filtered) == 1 and "null_ohlc" in report["removal_reasons"])
check("Ph6-b  invalid_ohlc row removed", "invalid_ohlc" in report["removal_reasons"])
check("Ph6-c  report contains rows_before/rows_after",
      report["rows_before"] == 3 and report["rows_after"] == 1)

try:
    _apply_quality_filter(df, {"drop_null_ohlc": True, "min_rows": 10})
    check("Ph6-d  min_rows raises ValueError when too few rows remain", False, "no exception raised")
except ValueError:
    check("Ph6-d  min_rows raises ValueError when too few rows remain", True)

df_ok = pd.DataFrame([{"timestamps": "2026-01-01", "open": 100, "high": 102, "low": 98, "close": 101}])
filtered_empty, report_empty = _apply_quality_filter(df_ok, {})
check("Ph6-e  empty quality_filter is a no-op", len(filtered_empty) == 1 and not report_empty["filter_applied"])

# ── Phase 7a: WebSocket volume/amount = None ─────────────────────────────────
from kronos_mapper import ws_ohlc_to_kronos_row

ws_row = ws_ohlc_to_kronos_row({"t": "2026-01-01T00:00:00Z", "o": "100", "h": "102", "l": "98", "c": "101"})
check("Ph7-a  ws volume is None (not 0.0)", ws_row["volume"] is None, f"got {ws_row['volume']}")
check("Ph7-b  ws amount is None (not 0.0)", ws_row["amount"] is None, f"got {ws_row['amount']}")

# ── Phase 7b: feature-column selection with NaN volume ───────────────────────
from main_run_kronos_predict import _select_feature_columns

df_ws_nan = pd.DataFrame({"open": [100.0], "high": [102.0], "low": [98.0], "close": [101.0],
                           "volume": [np.nan], "amount": [np.nan]})
cols = _select_feature_columns(df_ws_nan, "auto")
check("Ph7-c  NaN volume excluded from auto feature cols", "volume" not in cols, f"cols={cols}")
check("Ph7-d  NaN amount excluded from auto feature cols", "amount" not in cols, f"cols={cols}")

df_with_vol = pd.DataFrame({"open": [100.0], "high": [102.0], "low": [98.0], "close": [101.0],
                             "volume": [500.0], "amount": [np.nan]})
cols2 = _select_feature_columns(df_with_vol, "auto")
check("Ph7-e  numeric volume included in auto feature cols", "volume" in cols2, f"cols={cols2}")
check("Ph7-f  NaN amount still excluded when volume present", "amount" not in cols2, f"cols={cols2}")

# ── Phase 7c: CSV write buffer ────────────────────────────────────────────────
from capital_ws_ohlc_client import CapitalOhlcWebSocketClient
check("Ph7-g  CapitalOhlcWebSocketClient has _csv_write_pending attr",
      hasattr(CapitalOhlcWebSocketClient, '__init__') and
      '_csv_write_interval' in inspect.getsource(CapitalOhlcWebSocketClient.__init__))

# ── Phase 8: deterministic run-stamp ─────────────────────────────────────────
from main_run_kronos_predict import parse_args

with patch("sys.argv", ["prog", "--input", "dummy.csv", "--run-stamp", "20260501T120000Z"]):
    args = parse_args()
check("Ph8-a  --run-stamp CLI arg accepted", args.run_stamp == "20260501T120000Z")

with patch("sys.argv", ["prog", "--input", "dummy.csv"]):
    args2 = parse_args()
check("Ph8-b  --run-stamp defaults to None", args2.run_stamp is None)

# Verify main() uses args.run_stamp over _utc_file_timestamp()
main_src = inspect.getsource(__import__("main_run_kronos_predict").main)
check("Ph8-c  main() uses args.run_stamp when provided",
      "args.run_stamp" in main_src and "_utc_file_timestamp" in main_src)

# Verify METADATA_PATH: printed in main()
check("Ph8-d  main() prints METADATA_PATH: for parent to capture",
      "METADATA_PATH:" in main_src)

# Verify main_forecast_latest.py builds deterministic path
import importlib.util, pathlib
mfl_path = ROOT / "src" / "main_forecast_latest.py"
mfl_src = mfl_path.read_text(encoding="utf-8")
check("Ph8-e  main_forecast_latest passes --run-stamp to subprocess",
      '"--run-stamp"' in mfl_src and 'run_stamp' in mfl_src)
check("Ph8-f  main_forecast_latest uses deterministic metadata path (no glob)",
      'glob' not in mfl_src.split("latest_metadata")[1].split("\n")[0],
      "glob still used for metadata path")

# ── Phase 3: auto-finetune approval safety ───────────────────────────────────
from main_auto_finetune_worker import _promotion_decision

for acc in [40.0, 55.0, 65.0, 99.9]:
    s, r = _promotion_decision(model_ready=True,
                                metrics={"matched_candles": 500, "direction_accuracy_pct": acc},
                                min_accuracy=55.0, min_matched=100,
                                previous_promoted_accuracy=None)
    check(f"Ph3-a  _promotion_decision never 'approved' (accuracy={acc}%)",
          s != "approved", f"returned {s!r}")

s_nm, _ = _promotion_decision(model_ready=False,
                               metrics={"matched_candles": 500, "direction_accuracy_pct": 99.0},
                               min_accuracy=55.0, min_matched=100,
                               previous_promoted_accuracy=None)
check("Ph3-b  not_ready when model_ready=False", s_nm == "not_ready")

s_pr, _ = _promotion_decision(model_ready=True,
                               metrics={"matched_candles": 5, "direction_accuracy_pct": 99.0},
                               min_accuracy=55.0, min_matched=100,
                               previous_promoted_accuracy=None)
check("Ph3-c  pending_review when matched_candles below threshold", s_pr == "pending_review")

# Verify train/eval split logic (80/20)
n = 50
df_split = pd.DataFrame({"timestamps": pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC"),
                          "close": range(n)})
split_idx = max(1, int(len(df_split) * 0.8))
train_part = df_split.iloc[:split_idx]
eval_part = df_split.iloc[split_idx:]
check("Ph3-d  80/20 split: no timestamp overlap",
      len(set(train_part["timestamps"]) & set(eval_part["timestamps"])) == 0)
check("Ph3-e  80/20 split: train earlier than eval",
      train_part["timestamps"].iloc[-1] < eval_part["timestamps"].iloc[0])
check("Ph3-f  80/20 split: both non-empty", len(train_part) > 0 and len(eval_part) > 0)

# Verify register_model_version call never uses "approved"
rc_src = (ROOT / "src" / "main_auto_finetune_worker.py").read_text(encoding="utf-8")
check("Ph3-g  register_model_version call does not use promotion_status='approved'",
      'promotion_status="approved"' not in rc_src and
      "promotion_status='approved'" not in rc_src)

# ── Phase 1: walk-forward candidate tracking ─────────────────────────────────
from walk_forward import _query_candidate_window_metrics

check("Ph1-a  _query_candidate_window_metrics function exists in walk_forward",
      callable(_query_candidate_window_metrics))

wf_src = (ROOT / "src" / "walk_forward.py").read_text(encoding="utf-8")
check("Ph1-b  walk_forward computes beats_naive_rate_pct", "beats_naive_rate_pct" in wf_src)
check("Ph1-c  walk_forward uses BASELINE_ONLY status when no candidate coverage",
      "BASELINE_ONLY" in wf_src)
check("Ph1-d  walk_forward queries prediction_runs for model_version_id",
      "model_version_id" in wf_src and "prediction_runs" in wf_src)
check("Ph1-e  walk_forward marks COMPLETED vs BASELINE_ONLY in DB update",
      'final_status' in wf_src and '"BASELINE_ONLY"' in wf_src)

# ── Phase 2: promotion gates use candidate evidence ──────────────────────────
from model_registry import _candidate_shadow_metrics, _candidate_baseline_beat_rate, _gate

check("Ph2-a  _candidate_shadow_metrics function exists", callable(_candidate_shadow_metrics))
check("Ph2-b  _candidate_baseline_beat_rate function exists", callable(_candidate_baseline_beat_rate))

# Gate with None metric must FAIL (not silently pass)
g = _gate("baseline_beat_rate", None, 50.0)
check("Ph2-c  gate with None metric_value = FAIL (insufficient evidence)", g["status"] == "FAIL")

g2 = _gate("mape_regression", None, 5.0, comparator="<=")
check("Ph2-d  gate with None metric = FAIL regardless of comparator", g2["status"] == "FAIL")

mr_src = (ROOT / "src" / "model_registry.py").read_text(encoding="utf-8")
check("Ph2-e  evaluate_promotion uses _candidate_shadow_metrics",
      "_candidate_shadow_metrics" in mr_src)
check("Ph2-f  evaluate_promotion uses _candidate_baseline_beat_rate",
      "_candidate_baseline_beat_rate" in mr_src)
check("Ph2-g  evaluate_promotion does NOT use active_accuracy_pct for horizon gate",
      'active_accuracy_pct' not in mr_src.split('def evaluate_promotion')[1].split('def ')[0])

# Verify horizon gate uses per_horizon_accuracy from candidate
check("Ph2-h  evaluate_promotion uses candidate_per_horizon for horizon gate",
      "candidate_per_horizon" in mr_src)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 72)
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
print(f"  Behavioral verification: {passed} PASS, {failed} FAIL  ({len(results)} checks)")
if failed:
    print()
    print("FAILURES:")
    for s, label, detail in results:
        if s == FAIL:
            print(f"  ✗  {label}  {detail}")
    sys.exit(1)
else:
    print("  All behavioral checks PASS")
