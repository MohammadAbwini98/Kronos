from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from dashboard_db import postgres_dashboard_snapshot
from dashboard_ui import dashboard_html
from prediction_store import prediction_summary
from prediction_log_report import generate_prediction_log_report


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"


def _latest_file(pattern: str) -> Path | None:
    files = sorted(OUTPUT_DIR.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _safe_json(path: str | Path | None) -> dict:
    if not path:
        return {}
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def _safe_csv(path: str | Path | None, limit: int | None = None) -> list[dict]:
    if not path:
        return []
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        return []
    df = pd.read_csv(source)
    if "timestamps" in df.columns:
        df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True).dt.tz_convert("Asia/Amman").astype(str)
    if limit is not None:
        df = df.tail(limit)
    return df.to_dict(orient="records")


def _metadata_stamp(path: Path) -> str:
    return path.stem.split("_")[-1]


def _latest_metadata() -> tuple[Path | None, dict]:
    path = _latest_file("forecast_metadata_ETHUSD_*.json") or _latest_file("forecast_metadata_*.json")
    return path, _safe_json(path)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _content_type(path: Path) -> str:
    if path.suffix.lower() == ".html":
        return "text/html; charset=utf-8"
    if path.suffix.lower() == ".json":
        return "application/json; charset=utf-8"
    if path.suffix.lower() == ".csv":
        return "text/csv; charset=utf-8"
    return "text/plain; charset=utf-8"


def _run(cmd: list[str], timeout: int = 420) -> dict:
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    return {"returncode": result.returncode, "output": output}


def _history(limit: int = 20) -> list[dict]:
    rows = []
    for path in sorted(OUTPUT_DIR.glob("forecast_metadata_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        metadata = _safe_json(path)
        validation = _safe_json(metadata.get("validation_report_path"))
        validation_body = validation.get("forecast_quality_validation", validation)
        rows.append(
            {
                "metadata_path": str(path),
                "forecast_path": metadata.get("forecast_csv_path"),
                "generated_at_local": metadata.get("generated_at_local"),
                "forecast_start": metadata.get("forecast_start_timestamp"),
                "forecast_end": metadata.get("forecast_end_timestamp"),
                "epic": metadata.get("epic"),
                "resolution": metadata.get("resolution"),
                "direction": validation_body.get("forecast_direction"),
                "last_input_close": metadata.get("last_input_close"),
                "last_forecast_close": validation_body.get("last_forecast_close"),
                "quality_status": validation_body.get("quality_status"),
            }
        )
    return rows


def _prediction_db_summary() -> dict:
    try:
        return prediction_summary(limit=20)
    except Exception as exc:  # keep dashboard status available if the local DB is locked or missing
        return {"error": str(exc)}


def _postgres_snapshot() -> dict:
    try:
        return postgres_dashboard_snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"postgres": {"ok": False, "error": str(exc)}}


def _dashboard_html() -> str:
    return dashboard_html()


def _html() -> str:
    return _dashboard_html()


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = _html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/status":
            metadata_path, metadata = _latest_metadata()
            validation = _safe_json(metadata.get("validation_report_path"))
            validation_body = validation.get("forecast_quality_validation", validation)
            forecast = _safe_csv(metadata.get("forecast_csv_path"))
            input_tail = _safe_csv(metadata.get("input_csv_path"), limit=100)
            latest_actual = _latest_file(f"actual_for_forecast_{metadata.get('epic', 'ETHUSD')}_{metadata.get('resolution', 'MINUTE_5')}_*.csv")
            actual_tail = _safe_csv(latest_actual, limit=100) or input_tail
            baseline_reports = sorted(OUTPUT_DIR.glob("forecast_quality_report_BASELINE_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            baseline_summary = {p.stem: _safe_json(p).get("forecast_quality_validation", {}) for p in baseline_reports[:6]}
            postgres_snapshot = _postgres_snapshot()
            _json_response(
                self,
                200,
                {
                    "metadata": metadata,
                    "validation": validation_body,
                    "forecast": forecast,
                    "actual_tail": actual_tail,
                    "history": _history(),
                    "prediction_db": postgres_snapshot.get("prediction_db", _prediction_db_summary()),
                    "postgres_snapshot": postgres_snapshot,
                    "baseline_summary": baseline_summary,
                    "files": {
                        "metadata": str(metadata_path) if metadata_path else None,
                        "input": metadata.get("input_csv_path"),
                        "forecast": metadata.get("forecast_csv_path"),
                        "validation": metadata.get("validation_report_path"),
                        "latest_actual": str(latest_actual) if latest_actual else None,
                    },
                },
            )
            return
        if parsed.path == "/file":
            target = Path(parse_qs(parsed.query).get("path", [""])[0])
            if not target.is_absolute():
                target = ROOT / target
            try:
                resolved = target.resolve()
                if not str(resolved).startswith(str(ROOT.resolve())):
                    raise FileNotFoundError
                body = resolved.read_bytes()
            except FileNotFoundError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", _content_type(resolved))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if parsed.path == "/api/predict":
            self._predict(payload)
            return
        if parsed.path == "/api/fetch-actual":
            self._fetch_actual()
            return
        if parsed.path == "/api/validate-actual":
            self._validate_actual()
            return
        if parsed.path == "/api/baselines":
            self._baselines()
            return
        self.send_error(404)

    def _predict(self, payload: dict) -> None:
        market = payload.get("market", "ETHUSD")
        resolution = payload.get("resolution", "MINUTE_5")
        pred_len = str(int(payload.get("pred_len", 12)))
        lookback = str(int(payload.get("lookback", 512)))
        feature_set = payload.get("feature_set", "auto")
        repair = bool(payload.get("repair_ohlc", True))
        cmd = [
            sys.executable,
            "src/main_forecast_latest.py",
            "--market",
            market,
            "--resolution",
            resolution,
            "--max",
            "512",
            "--lookback",
            lookback,
            "--pred-len",
            pred_len,
            "--price-side",
            "mid",
            "--env",
            "demo",
            "--feature-set",
            feature_set,
        ]
        if repair:
            cmd.append("--repair-ohlc")
        result = _run(cmd)
        report_url = None
        report_path = None
        if result["returncode"] == 0:
            metadata_path = _latest_file(f"forecast_metadata_{market}_*.json") or _latest_file("forecast_metadata_*.json")
            if metadata_path:
                metadata = _safe_json(metadata_path)
                forecast_path = ROOT / metadata["forecast_csv_path"]
                validation_path = ROOT / metadata["validation_report_path"]
                stamp = _metadata_stamp(metadata_path)
                report_path = OUTPUT_DIR / f"prediction_log_report_{metadata['epic']}_{metadata['resolution']}_{stamp}.html"
                generate_prediction_log_report(forecast_path, metadata_path, validation_path, report_path)
                report_url = f"/file?path={report_path.relative_to(ROOT).as_posix()}"
        _json_response(
            self,
            200 if result["returncode"] == 0 else 500,
            {**result, "error": None if result["returncode"] == 0 else result["output"], "report_path": str(report_path) if report_path else None, "report_url": report_url},
        )

    def _fetch_actual(self) -> None:
        metadata_path, _ = _latest_metadata()
        if not metadata_path:
            _json_response(self, 404, {"error": "No forecast metadata found"})
            return
        result = _run(
            [
                sys.executable,
                "src/main_fetch_actual_for_forecast.py",
                "--metadata",
                str(metadata_path),
                "--price-side",
                "mid",
                "--env",
                "demo",
                "--buffer-candles",
                "2",
            ],
            timeout=180,
        )
        _json_response(self, 200 if result["returncode"] == 0 else 500, result)

    def _validate_actual(self) -> None:
        metadata_path, metadata = _latest_metadata()
        if not metadata_path:
            _json_response(self, 404, {"error": "No forecast metadata found"})
            return
        stamp = _metadata_stamp(metadata_path)
        epic = metadata.get("epic", "ETHUSD")
        resolution = metadata.get("resolution", "MINUTE_5")
        actual = OUTPUT_DIR / f"actual_for_forecast_{epic}_{resolution}_{stamp}.csv"
        if not actual.exists():
            _json_response(self, 404, {"error": f"Actual CSV not found: {actual}"})
            return
        result = _run(
            [
                sys.executable,
                "src/main_validate_forecast_quality.py",
                "--forecast",
                metadata["forecast_csv_path"],
                "--actual",
                str(actual),
                "--resolution",
                resolution,
                "--price-side",
                metadata.get("price_side", "mid"),
                "--epic",
                epic,
                "--metadata",
                str(metadata_path),
                "--output",
                str(OUTPUT_DIR / f"forecast_quality_report_{epic}_{resolution}_{stamp}.json"),
            ],
            timeout=180,
        )
        _json_response(self, 200 if result["returncode"] == 0 else 500, result)

    def _baselines(self) -> None:
        metadata_path, metadata = _latest_metadata()
        if not metadata_path:
            _json_response(self, 404, {"error": "No forecast metadata found"})
            return
        stamp = _metadata_stamp(metadata_path)
        epic = metadata.get("epic", "ETHUSD")
        resolution = metadata.get("resolution", "MINUTE_5")
        actual = OUTPUT_DIR / f"actual_for_forecast_{epic}_{resolution}_{stamp}.csv"
        methods = ["naive", "moving_average", "drift", "last_direction"]
        logs: list[str] = []
        for method in methods:
            baseline_csv = OUTPUT_DIR / f"baseline_{method}_{epic}_{resolution}_{stamp}.csv"
            generated = _run(
                [
                    sys.executable,
                    "src/main_generate_baseline_forecasts.py",
                    "--input",
                    metadata["input_csv_path"],
                    "--resolution",
                    resolution,
                    "--pred-len",
                    str(metadata.get("forecast_rows", 12)),
                    "--method",
                    method,
                    "--output",
                    str(baseline_csv),
                ],
                timeout=120,
            )
            logs.append(generated["output"])
            if generated["returncode"] == 0 and actual.exists():
                validated = _run(
                    [
                        sys.executable,
                        "src/main_validate_forecast_quality.py",
                        "--forecast",
                        str(baseline_csv),
                        "--actual",
                        str(actual),
                        "--resolution",
                        resolution,
                        "--price-side",
                        metadata.get("price_side", "mid"),
                        "--epic",
                        epic,
                        "--output",
                        str(OUTPUT_DIR / f"forecast_quality_report_BASELINE_{method}_{epic}_{resolution}_{stamp}.json"),
                    ],
                    timeout=120,
                )
                logs.append(validated["output"])
        _json_response(self, 200, {"returncode": 0, "output": "\n".join(logs)})

    def log_message(self, format: str, *args) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start local Capital.com Kronos dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open the dashboard in the default browser.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
