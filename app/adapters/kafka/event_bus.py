"""Message-bus adapter used by the NLP pipeline to announce topic matches."""

from __future__ import annotations

import logging
from uuid import UUID

from app.adapters.kafka.base import EventBusInterface
from app.adapters.kafka.producer import KafkaPublisher, get_publisher

logger = logging.getLogger(__name__)

MATCHED_ARTICLES_TOPIC = "matched-articles"


class MockKafkaAdapter(EventBusInterface):
    """
    A placeholder adapter for the Message Bus Interface.
    Logs published messages without requiring a live Kafka broker.
    Can be seamlessly swapped with a real Kafka producer.
    """

    def publish_matched_article(
        self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID
    ) -> None:
        logger.info(
            "[MOCK KAFKA] matched article=%s topic=%s score=%.3f user=%s",
            article_id, topic_id, relevance_score, user_id,
        )


class KafkaAdapter(EventBusInterface):
    """
    Publishes matched articles to 'matched-articles' for the Alert Service.

    Flushes on every publish. The pipeline processes one article at a time and
    commits its Kafka offset only after this returns, so an unflushed buffer
    would let the consumer commit an offset for a message that never left the
    process.
    """

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        topic: str = MATCHED_ARTICLES_TOPIC,
        publisher: KafkaPublisher | None = None,
    ) -> None:
        self.topic = topic
        self._publisher = publisher or (
            KafkaPublisher(bootstrap_servers) if bootstrap_servers else get_publisher()
        )

    def publish_matched_article(
        self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID
    ) -> None:
        self._publisher.publish(self.topic, {
            "article_id": str(article_id),
            "topic_id": str(topic_id),
            "relevance_score": relevance_score,
            "user_id": str(user_id),
        })
        self._publisher.flush()
