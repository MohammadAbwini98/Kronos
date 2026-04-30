from __future__ import annotations

import argparse

from db import healthcheck, run_migrations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL migrations for the Capital Kronos signal system.")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--migrations-dir", default="migrations")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    status = healthcheck(args.dsn)
    if not status["ok"]:
        raise SystemExit(f"PostgreSQL is not reachable: {status['error']}")
    applied = run_migrations(args.dsn, args.migrations_dir)
    status = healthcheck(args.dsn)
    print(f"Applied migrations: {applied if applied else 'none'}")
    print(f"PostgreSQL health: {status}")


if __name__ == "__main__":
    main()
