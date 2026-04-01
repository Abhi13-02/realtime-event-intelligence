from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.topics import router as topics_router
from app.services.topics import TopicServiceError

app = FastAPI(title="RealTime Event Intelligence")


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
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(topics_router, prefix="/v1")
