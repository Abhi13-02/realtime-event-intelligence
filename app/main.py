from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.alerts import router as alerts_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.intelligence import router as intelligence_router
from app.api.topics import router as topics_router
from app.api.users import router as users_router
from app.services.exceptions import ServiceError
from app.services.topics import TopicServiceError
from app.alert.websocket import router as ws_router, run_backplane_subscriber
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def _handle_subscriber_done(task: asyncio.Task[None]) -> None:
    """Log an unexpected subscriber crash as soon as the task exits."""
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Alert backplane subscriber cancelled.")
    except Exception:
        logger.exception("Alert backplane subscriber crashed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan — runs startup logic before the first request,
    and shutdown logic after the last request.

    On startup: subscribe to the Redis alert backplane.

      The two alert consumers used to run here as asyncio tasks. They now live
      in their own container (app/alert/runner.py) and broadcast over Redis,
      so this process only listens and delivers to the sockets it holds. That
      is what lets this service run more than one replica: previously an alert
      consumed by replica B could not reach a user connected to replica A.

    On shutdown: cancel the subscriber so it unsubscribes cleanly.
    """
    subscriber_task = asyncio.create_task(run_backplane_subscriber())
    subscriber_task.add_done_callback(_handle_subscriber_done)
    app.state.backplane_task = subscriber_task
    logger.info("Alert backplane subscriber started.")

    yield  # FastAPI serves requests while we're here

    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass

    app.state.backplane_task = None
    logger.info("Alert backplane subscriber stopped.")


app = FastAPI(title="RealTime Event Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://localhost:5174", 
        "http://localhost:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "https://realtime-topic-intelligence-1up3vxs6r.vercel.app",
        "https://realtime-topic-intelligence.vercel.app",
        "https://realtime-topic-intelligence-8eq7xocl0.vercel.app",
        "https://realtime-topic-intelligence-7cc3k2q7p.vercel.app",
        "https://narrative.abhinavdev.online",
        "https://abhinavdev.online",
        "https://www.abhinavdev.online"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(TopicServiceError)
async def handle_topic_service_error(
    request: Request,
    exc: TopicServiceError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "code": exc.code},
    )


@app.exception_handler(ServiceError)
async def handle_service_error(
    request: Request,
    exc: ServiceError,
) -> JSONResponse:
    """
    Render service-layer errors exactly as fastapi.HTTPException used to.

    The intelligence and admin services raise ServiceError subclasses instead
    of HTTPException so they stay free of web-framework imports. Keeping the
    body as {"detail": ...} means the wire format is unchanged for the
    frontend, which is the whole point — this extraction must be invisible
    from outside.
    """
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


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
    """
    Liveness for this gateway replica.

    It reports on the backplane subscriber only. The alert consumers are a
    different container now and have their own lifecycle — this endpoint
    saying "ok" means this replica can deliver what it is handed, not that
    the alert pipeline as a whole is healthy.
    """
    task: asyncio.Task[None] | None = getattr(request.app.state, "backplane_task", None)
    subscriber_status = "stopped" if (task is not None and task.done()) else "running"

    overall = "ok" if subscriber_status == "running" else "degraded"

    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={"status": overall, "alert_backplane": subscriber_status},
    )


app.include_router(auth_router, prefix="/v1")
app.include_router(topics_router, prefix="/v1")
app.include_router(users_router, prefix="/v1")
app.include_router(alerts_router, prefix="/v1")
app.include_router(ws_router, prefix="/v1")
app.include_router(intelligence_router, prefix="/v1")
app.include_router(admin_router, prefix="/v1")
