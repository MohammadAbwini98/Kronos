from __future__ import annotations

import argparse
import json
from pathlib import Path

from db import healthcheck
from prediction_store import prediction_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect PostgreSQL prediction WIN/LOSS summary.")
    parser.add_argument("--postgres-dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--db", default=None, help="Deprecated alias for --postgres-dsn.")
    parser.add_argument("--output", default=None, help="Optional JSON summary output path.")
    parser.add_argument("--limit", type=int, default=20, help="Recent runs to include.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dsn = args.postgres_dsn or args.db
    status = healthcheck(dsn)
    if not status["ok"]:
        raise SystemExit(f"PostgreSQL is not reachable: {status['error']}")
    summary = prediction_summary(dsn, limit=args.limit)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
