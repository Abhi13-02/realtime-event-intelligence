"""Entrypoint for the standalone alert-consumer container.

Runs both Kafka alert streams on one event loop:

  Stream A  matched-articles   -> app/alert/consumer.py
  Stream B  sub-theme-events   -> app/alert/intelligence_consumer.py

Both are I/O-bound (Kafka, Postgres, Redis) so a single process handles them
comfortably; they are gathered rather than split into two containers because
they share the same database session factory and the same backplane.

They used to run as asyncio tasks inside FastAPI. Moving them here is what
allows the backend to scale past one replica — see
app/adapters/db/redis_pubsub.py for the full reasoning.

Run with:  python -m app.alert.runner
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.alert.consumer import run_alert_consumer
from app.alert.intelligence_consumer import run_intelligence_consumer
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


async def _run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    # SIGTERM is what `docker compose down` and a rolling restart send. Without
    # handling it the process is killed mid-message and the Kafka offset for an
    # alert already written to Postgres may or may not have been committed.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows dev boxes have no add_signal_handler; Ctrl-C still works.
            pass

    alert_task = asyncio.create_task(run_alert_consumer(), name="alert-consumer")
    intel_task = asyncio.create_task(run_intelligence_consumer(), name="intelligence-consumer")
    stop_task = asyncio.create_task(stop.wait(), name="shutdown-signal")

    logger.info("Alert consumer container started — both streams running.")

    done, pending = await asyncio.wait(
        {alert_task, intel_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    # If a consumer exits on its own it has crashed — the loops are infinite.
    # Log the reason before shutting the other one down, otherwise the
    # container just restarts with no explanation of what failed.
    for task in done:
        if task is stop_task:
            logger.info("Shutdown signal received.")
            continue
        try:
            task.result()
            logger.error("%s exited unexpectedly without an error.", task.get_name())
        except Exception:
            logger.exception("%s crashed.", task.get_name())

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    logger.info("Alert consumer container stopped.")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
