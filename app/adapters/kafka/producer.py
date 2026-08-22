"""Shared synchronous Kafka producer.

There used to be three separate KafkaProducer constructions in this codebase —
one for raw-articles (ingestion), one for matched-articles (pipeline), one for
sub-theme-events (discovery) — each with slightly different tuning. All three
run in synchronous contexts, so they collapse into a single publisher.

They now share the ingestion tuning, which was the most deliberate of the
three. The other two were on kafka-python defaults, which means retries=0:
a transient broker blip dropped the message with no retry. That is now 3.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from kafka import KafkaProducer

from app.core.config import get_settings
from app.core.logging import new_trace_id, set_trace_id

logger = logging.getLogger(__name__)


class KafkaPublisher:
    """
    Thin wrapper over KafkaProducer with JSON serialisation.

    Creating a producer opens a TCP connection to the broker, so instances are
    expensive. Use get_publisher() to share one per process rather than
    constructing this per task.
    """

    def __init__(self, bootstrap_servers: str | None = None) -> None:
        servers = bootstrap_servers or get_settings().kafka_bootstrap_servers
        self._producer = KafkaProducer(
            bootstrap_servers=servers,
            # The lambda receives a Python dict and returns bytes.
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            # acks=1: wait for the Kafka leader to confirm the write. Balances
            # durability vs latency — leader failure before replication could
            # lose the message, but that is acceptable for these streams
            # (an article will be re-crawled next cycle).
            acks=1,
            # Batch messages for up to 100ms before sending. Reduces network
            # round-trips when several events are published in quick succession.
            linger_ms=100,
            retries=3,
        )
        logger.info("Kafka producer connected to %s", servers)

    def publish(self, topic: str, value: dict, key: str | None = None) -> None:
        """Publish one JSON message. Buffered — call flush() to force delivery."""
        self._producer.send(topic, value=value, key=key)

    def flush(self) -> None:
        """Block until every buffered message has been delivered."""
        self._producer.flush()

    def close(self) -> None:
        """Close the underlying connection. Not for the shared singleton."""
        self._producer.close()


@lru_cache
def get_publisher() -> KafkaPublisher:
    """Return the process-wide publisher, connecting on first use."""
    return KafkaPublisher()


# ── Ingestion helpers ────────────────────────────────────────────────────
# Kept as module-level functions because the RSS, Reddit and API scrapers all
# call them directly and have no reason to know about the publisher object.

def publish_article(article: dict) -> None:
    """
    Publish one raw article to the raw-articles Kafka topic.

    article must contain: url, headline, content, source_id, published_at
    article may optionally contain: image_url (str | None)
    Partition key is source_id — all articles from the same source land on the
    same partition, preserving insertion order per source.

    A trace_id is minted here — this is where an article enters the system, so
    it is the only place that can be the origin of its id. Every downstream
    process reads it back off the message and logs under it. See
    app/core/logging.py.
    """
    article = {**article, "trace_id": article.get("trace_id") or new_trace_id()}
    set_trace_id(article["trace_id"])

    get_publisher().publish(
        "raw-articles",
        value=article,
        key=article.get("source_id"),
    )
    logger.debug("Published article to raw-articles: %s", article.get("url"))


def flush_producer() -> None:
    """Flush buffered messages to Kafka. Call once at the end of each scraper task."""
    get_publisher().flush()
