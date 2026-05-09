from __future__ import annotations

import argparse
import logging
import time

from config import configure_logging, load_trade_execution_settings, log_trade_execution_startup
from logging_utils import log_event
from service_runtime import write_heartbeat
from trade_execution import TradeExecutionQueueService, TradeLifecycleReconciliationService


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process Capital.com demo trade execution queue.")
    parser.add_argument("--once", action="store_true", help="Drain the queue and reconcile once, then exit.")
    parser.add_argument("--sleep-seconds", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    configure_logging(service_name="trade_execution_worker")
    args = parse_args()
    settings = load_trade_execution_settings()
    log_trade_execution_startup(settings, LOGGER)
    queue = TradeExecutionQueueService(settings=settings)
    reconciliation = TradeLifecycleReconciliationService(settings=settings, repository=queue.repository)

    log_event(LOGGER, logging.INFO, "trade_execution_worker.start", once=args.once)
    while True:
        try:
            drained = queue.drain_once()
            reconciled = reconciliation.run_once()
            log_event(
                LOGGER,
                logging.INFO,
                "trade_execution_worker.tick",
                drained=drained,
                reconciled=reconciled,
            )
            write_heartbeat(
                "trade_execution_worker",
                "OK",
                {"drained": drained, "reconciled": reconciled, "auto_execute_signals": settings.auto_execute_signals},
                None,
            )
        except Exception as exc:  # noqa: BLE001
            log_event(
                LOGGER,
                logging.ERROR,
                "trade_execution_worker.error",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            try:
                write_heartbeat("trade_execution_worker", "ERROR", {"error": str(exc)}, None)
            except Exception:  # noqa: BLE001
                pass
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(1.0, args.sleep_seconds))


if __name__ == "__main__":
    main()
