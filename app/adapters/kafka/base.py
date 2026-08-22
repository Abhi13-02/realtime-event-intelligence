"""Port for publishing pipeline events onto the message bus."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class EventBusInterface(ABC):
    @abstractmethod
    def publish_matched_article(
        self,
        article_id: UUID,
        topic_id: UUID,
        relevance_score: float,
        user_id: UUID,
    ) -> None:
        """Publish an event to the message bus for the Alert Service to consume."""
