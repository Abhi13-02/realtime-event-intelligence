"""Correlation-id logging, so one article can be followed across containers.

WHY
---
The pipeline used to be three processes. It is now six, connected by two Kafka
topics and a Redis channel:

    ingestion -> raw-articles -> pipeline -> matched-articles
              -> alert-consumer -> redis -> gateway -> socket

When a user says "I never got my alert", the only way to answer is to find
every log line about that one article. Without a shared id, each container's
logs are a separate haystack and the question is unanswerable.

HOW
---
One id is minted at ingestion and travels in the Kafka message body, into the
Redis payload, and out to the gateway. Each process puts it in a ContextVar as
soon as it picks a message up, and a logging filter stamps it onto every record
emitted while handling that message — so call sites need no changes at all.

    docker compose logs | grep 3f2a1b9c

The field is named trace_id rather than correlation_id on purpose. If this ever
graduates to OpenTelemetry, that is the name OTel uses, and the log format will
not have to change underneath whatever is already parsing it.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

# "-" rather than None so the formatter never has to special-case a missing id,
# and so a line logged outside any message handling is visibly unattached.
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [trace=%(trace_id)s] %(message)s"


def new_trace_id() -> str:
    """Mint a short id. 8 hex chars is plenty to disambiguate a day of logs."""
    return uuid.uuid4().hex[:8]


def set_trace_id(trace_id: str | None) -> str:
    """
    Bind a trace id to the current context, minting one if the message carried
    none (an older message replayed from Kafka, or a manually produced one).
    """
    resolved = trace_id or new_trace_id()
    _trace_id.set(resolved)
    return resolved


def get_trace_id() -> str:
    """Current trace id, or '-' outside of message handling."""
    return _trace_id.get()


class TraceIdFilter(logging.Filter):
    """Stamps the current trace id onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """
    Install the trace-aware formatter on the root logger.

    Called by every container entrypoint. Uvicorn installs its own handlers for
    its access logs, which are untouched — those are per-request and already
    identifiable by path.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
