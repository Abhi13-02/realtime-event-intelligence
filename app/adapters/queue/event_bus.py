"""Message-bus adapter used by the NLP pipeline to announce topic matches."""

from __future__ import annotations

import logging
from uuid import UUID

from app.adapters.queue.names import MATCHED_ARTICLES
from app.adapters.queue.publisher import QueuePublisher, get_publisher
from app.core.logging import get_trace_id
from app.pipeline.interfaces import EventBusInterface

logger = logging.getLogger(__name__)


class MockEventBus(EventBusInterface):
    """
    A placeholder adapter for the Message Bus Interface.
    Logs published messages without requiring a database.
    Can be seamlessly swapped with the real publisher.
    """

    def publish_matched_article(
        self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID
    ) -> None:
        logger.info(
            "[MOCK BUS] matched article=%s topic=%s score=%.3f user=%s",
            article_id, topic_id, relevance_score, user_id,
        )


class PgEventBus(EventBusInterface):
    """
    Publishes matched articles to the 'matched-articles' queue for the Alert
    Service.

    Flushes on every publish. The pipeline processes one article at a time and
    acks its queue message only after this returns, so an unflushed buffer
    would let the consumer ack a message whose matches were never written.
    """

    def __init__(
        self,
        queue: str = MATCHED_ARTICLES,
        publisher: QueuePublisher | None = None,
    ) -> None:
        self.queue = queue
        self._publisher = publisher or get_publisher()

    def publish_matched_article(
        self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID
    ) -> None:
        self._publisher.publish(self.queue, {
            "article_id": str(article_id),
            "topic_id": str(topic_id),
            "relevance_score": relevance_score,
            "user_id": str(user_id),
            # Read off the ContextVar rather than threaded through the call
            # chain — the pipeline set it when it picked the article up, and
            # every stage between here and there stays unaware of it.
            "trace_id": get_trace_id(),
        })
        self._publisher.flush()
