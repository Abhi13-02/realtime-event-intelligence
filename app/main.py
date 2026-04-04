from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.alerts import router as alerts_router
from app.api.topics import router as topics_router
from app.api.users import router as users_router
from app.services.topics import TopicServiceError
from app.alert.consumer import run_alert_consumer
from app.alert.websocket import connection_manager, router as ws_router

logger = logging.getLogger(__name__)


def _handle_alert_consumer_done(task: asyncio.Task[None]) -> None:
    """Log any unexpected alert-consumer crash as soon as the task exits."""
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Alert consumer background task cancelled.")
    except Exception:
        logger.exception("Alert consumer background task crashed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan — runs startup logic before the first request,
    and shutdown logic after the last request.

    On startup: launch the alert consumer as a background asyncio task.
      It reads matched-articles from Kafka and routes alerts to users.
      It runs in the same event loop as FastAPI so it can call
      connection_manager.push() directly without inter-process communication.

    On shutdown: cancel the consumer task cleanly so in-flight messages
      are not silently dropped (the offset won't be committed for the
      message being processed, so Kafka will replay it on next start).
    """
    task = asyncio.create_task(run_alert_consumer(connection_manager))
    task.add_done_callback(_handle_alert_consumer_done)
    app.state.alert_consumer_task = task
    logger.info("Alert consumer background task started.")

    yield  # FastAPI serves requests while we're here

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.alert_consumer_task = None
    logger.info("Alert consumer background task stopped.")


app = FastAPI(title="RealTime Event Intelligence", lifespan=lifespan)


@app.exception_handler(TopicServiceError)
async def handle_topic_service_error(
    request: Request,
    exc: TopicServiceError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "code": exc.code},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else None
    error_message = first_error["msg"] if first_error else "Invalid request."
    return JSONResponse(
        status_code=400,
        content={"error": error_message, "code": "BAD_REQUEST"},
    )


@app.get("/")
async def health(request: Request) -> JSONResponse:
    task: asyncio.Task[None] | None = getattr(request.app.state, "alert_consumer_task", None)

    if task is not None and task.done():
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "alert_consumer": "stopped"},
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "alert_consumer": "running"},
    )


app.include_router(topics_router, prefix="/v1")
app.include_router(users_router, prefix="/v1")
app.include_router(alerts_router, prefix="/v1")
app.include_router(ws_router, prefix="/v1")
