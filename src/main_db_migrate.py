from __future__ import annotations

import argparse
import logging

from config import configure_logging
from db import healthcheck, run_migrations
from logging_utils import log_event, new_correlation_id


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL migrations for the Capital Kronos signal system.")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN. Defaults to POSTGRES_DSN.")
    parser.add_argument("--migrations-dir", default="migrations")
    return parser.parse_args()


def main() -> None:
    configure_logging(service_name="db_migrate")
    args = parse_args()
    migration_run_id = new_correlation_id("migration")
    log_event(
        LOGGER,
        logging.INFO,
        "db.migration.start",
        migration_run_id=migration_run_id,
        migrations_dir=args.migrations_dir,
    )
    status = healthcheck(args.dsn)
    if not status["ok"]:
        log_event(
            LOGGER,
            logging.ERROR,
            "db.migration.error",
            migration_run_id=migration_run_id,
            error=status.get("error"),
        )
        raise SystemExit(f"PostgreSQL is not reachable: {status['error']}")
    applied = run_migrations(args.dsn, args.migrations_dir)
    status = healthcheck(args.dsn)
    log_event(
        LOGGER,
        logging.INFO,
        "db.migration.completed",
        migration_run_id=migration_run_id,
        applied_count=len(applied),
        postgres_ok=bool(status.get("ok")),
    )
    print(f"Applied migrations: {applied if applied else 'none'}")
    print(f"PostgreSQL health: {status}")


if __name__ == "__main__":
    main()
