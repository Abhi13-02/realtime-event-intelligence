from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.alerts import router as alerts_router
from app.api.debug import router as debug_router
from app.api.intelligence import router as intelligence_router
from app.api.topics import router as topics_router
from app.api.users import router as users_router
from app.services.topics import TopicServiceError
from app.alert.consumer import run_alert_consumer
from app.alert.intelligence_consumer import run_intelligence_consumer
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


def _handle_intel_consumer_done(task: asyncio.Task[None]) -> None:
    """Log any unexpected intelligence-consumer crash as soon as the task exits."""
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Intelligence consumer background task cancelled.")
    except Exception:
        logger.exception("Intelligence consumer background task crashed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan — runs startup logic before the first request,
    and shutdown logic after the last request.

    On startup: launch two Kafka consumers as asyncio background tasks.
      - Stream A (run_alert_consumer): reads matched-articles, routes article alerts.
      - Stream B (run_intelligence_consumer): reads sub-theme-events, routes intelligence alerts.
      Both share the same ConnectionManager so WebSocket delivery needs no IPC.

    On shutdown: cancel both tasks cleanly so in-flight messages are not silently
      dropped (Kafka will replay uncommitted offsets on next start).
    """
    # Stream A — article alerts
    alert_task = asyncio.create_task(run_alert_consumer(connection_manager))
    alert_task.add_done_callback(_handle_alert_consumer_done)
    app.state.alert_consumer_task = alert_task
    logger.info("Alert consumer (Stream A) background task started.")

    # Stream B — intelligence alerts
    intel_task = asyncio.create_task(run_intelligence_consumer(connection_manager))
    intel_task.add_done_callback(_handle_intel_consumer_done)
    app.state.intel_consumer_task = intel_task
    logger.info("Intelligence consumer (Stream B) background task started.")

    yield  # FastAPI serves requests while we're here

    # Shutdown — cancel both consumers
    alert_task.cancel()
    try:
        await alert_task
    except asyncio.CancelledError:
        pass

    intel_task.cancel()
    try:
        await intel_task
    except asyncio.CancelledError:
        pass

    app.state.alert_consumer_task = None
    app.state.intel_consumer_task = None
    logger.info("Both consumer background tasks stopped.")


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
    alert_task: asyncio.Task[None] | None  = getattr(request.app.state, "alert_consumer_task", None)
    intel_task: asyncio.Task[None] | None  = getattr(request.app.state, "intel_consumer_task", None)

    alert_status = "stopped" if (alert_task is not None and alert_task.done()) else "running"
    intel_status = "stopped" if (intel_task is not None and intel_task.done()) else "running"

    overall = "ok" if alert_status == "running" and intel_status == "running" else "degraded"
    status_code = 200 if overall == "ok" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "alert_consumer": alert_status,
            "intelligence_consumer": intel_status,
        },
    )


app.include_router(topics_router, prefix="/v1")
app.include_router(users_router, prefix="/v1")
app.include_router(alerts_router, prefix="/v1")
app.include_router(ws_router, prefix="/v1")
app.include_router(intelligence_router, prefix="/v1")
app.include_router(debug_router, prefix="/v1")
