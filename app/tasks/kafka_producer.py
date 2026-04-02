import json
import logging
from kafka import KafkaProducer
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Module-level singleton — created once when the worker process starts,
# reused for every task invocation. Creating a producer is expensive
# (opens a TCP connection to Kafka), so we don't create one per task.
_producer: KafkaProducer | None = None


def _get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            # Serialize message values to JSON bytes automatically.
            # The lambda receives a Python dict and returns bytes.
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            # Serialize the partition key to bytes.
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            # acks=1: wait for the Kafka leader to confirm the write.
            # Balances durability vs latency — leader failure before
            # replication could lose the message, but that's acceptable
            # for raw ingestion (article will be re-crawled next cycle).
            acks=1,
            # Batch messages for up to 100ms before sending.
            # Reduces network round-trips when multiple articles are
            # published in quick succession.
            linger_ms=100,
            retries=3,
        )
    return _producer


def publish_article(article: dict) -> None:
    """
    Publish one raw article to the raw-articles Kafka topic.

    article must contain: url, headline, content, source_id, published_at
    Partition key is source_id — all articles from the same source land
    on the same partition, preserving insertion order per source.
    """
    producer = _get_producer()
    producer.send(
        topic="raw-articles",
        value=article,
        key=article.get("source_id"),
    )
    # flush() blocks until Kafka confirms delivery.
    # Called after every article so the task doesn't exit
    # before messages are actually sent.
    producer.flush()
    logger.debug("Published article to raw-articles: %s", article.get("url"))
