"""Shared queue publisher — the drop-in replacement for the Kafka producer.

The API is deliberately identical to the one it replaces (publish / flush,
publish_article / flush_producer), because the three ingestion scrapers and the
discovery task all call it and none of them should have to care that the
transport underneath changed.

WHY IT STILL BUFFERS
--------------------
The Kafka producer batched with linger_ms=100 and every scraper ended its run
with flush(). That pattern is worth keeping for a different reason here: a
crawl cycle produces a burst of articles at once, and 450 separate INSERT
statements cost 450 round trips while one multi-row INSERT costs one. Buffering
until flush() turns the burst into a single statement — about 20ms of work.

The durability trade is the same one Kafka made. A process that dies with
articles still in the buffer loses them, exactly as it lost anything still
inside linger_ms. Neither case is a problem: the article is re-crawled on the
next cycle, and articles.url is UNIQUE so the retry is idempotent.

MAX_BUFFERED bounds the memory a runaway crawl can consume — past that the
buffer flushes itself rather than growing without limit.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.adapters.queue.names import RAW_ARTICLES
from app.adapters.queue.pg_queue import PgQueue
from app.core.constants import get_sync_db_url
from app.core.logging import new_trace_id, set_trace_id

logger = logging.getLogger(__name__)

# Flush automatically once this many messages are buffered, so a scraper that
# never reaches its flush() cannot grow the buffer without bound.
MAX_BUFFERED = 200


class QueuePublisher:
    """
    Buffering writer over PgQueue.

    Creating one opens a database connection, so instances are expensive. Use
    get_publisher() to share one per process rather than constructing this per
    Celery task.
    """

    def __init__(self, connection_string: str | None = None) -> None:
        self._queue = PgQueue(connection_string or get_sync_db_url())
        self._buffer: dict[str, list[dict]] = {}
        logger.info("Queue publisher connected.")

    def publish(self, queue: str, value: dict) -> None:
        """Buffer one message. Call flush() to write them."""
        bucket = self._buffer.setdefault(queue, [])
        bucket.append(value)
        if len(bucket) >= MAX_BUFFERED:
            self._flush_queue(queue)

    def _flush_queue(self, queue: str) -> None:
        pending = self._buffer.get(queue)
        if not pending:
            return
        self._queue.publish_many(queue, pending)
        logger.debug("Flushed %d message(s) to '%s'.", len(pending), queue)
        self._buffer[queue] = []

    def flush(self) -> None:
        """Write every buffered message. One INSERT per queue."""
        for queue in list(self._buffer):
            self._flush_queue(queue)

    def close(self) -> None:
        """Flush and close. Not for the shared singleton."""
        try:
            self.flush()
        finally:
            self._queue.close()


@lru_cache
def get_publisher() -> QueuePublisher:
    """Return the process-wide publisher, connecting on first use."""
    return QueuePublisher()


# ── Ingestion helpers ────────────────────────────────────────────────────
# Kept as module-level functions because the RSS, Reddit and API scrapers all
# call them directly and have no reason to know about the publisher object.

def publish_article(article: dict) -> None:
    """
    Publish one raw article to the raw-articles queue.

    article must contain: url, headline, content, source_id, published_at
    article may optionally contain: image_url (str | None)

    Kafka partitioned this stream by source_id to preserve per-source order.
    The queue does not need a key: queue_messages.id is a BIGSERIAL and the
    claim orders by it, so delivery is insertion order across the whole queue —
    a stronger guarantee than per-partition ordering, not a weaker one.

    A trace_id is minted here — this is where an article enters the system, so
    it is the only place that can be the origin of its id. Every downstream
    process reads it back off the message and logs under it. See
    app/core/logging.py.
    """
    article = {**article, "trace_id": article.get("trace_id") or new_trace_id()}
    set_trace_id(article["trace_id"])

    get_publisher().publish(RAW_ARTICLES, article)
    logger.debug("Published article to raw-articles: %s", article.get("url"))


def flush_producer() -> None:
    """Write buffered messages. Call once at the end of each scraper task."""
    get_publisher().flush()
