from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from app.pipeline.models import ProcessedArticle, Topic, ScoredMatch, RawArticle

class DatabaseInterface(ABC):
    @abstractmethod
    def check_url_exists(self, url: str) -> bool:
        """Check if an article URL already exists in the database."""
        pass

    @abstractmethod
    def vector_search_duplicate(self, embedding: List[float], threshold: float = 0.95) -> bool:
        """Check if a highly similar article exists (deduplication check)."""
        pass

    @abstractmethod
    def get_source_credibility(self, source_id: UUID) -> float:
        """Return the credibility score for a given source."""
        pass

    @abstractmethod
    def store_article_and_matches(self, article: ProcessedArticle, matches: List[ScoredMatch]) -> UUID:
        """
        Store the article (status='passed_dedup') and its topic matches.
        Should return the assigned article UUID.
        """
        pass

    @abstractmethod
    def update_article_summary(self, article_id: UUID, summary: str) -> None:
        """Update the article with the generated summary and set status='processed'."""
        pass

    @abstractmethod
    def get_users_meeting_threshold(self, topic_id: UUID, relevance_score: float) -> List[UUID]:
        """Return the list of active user IDs who track this topic and meet the threshold."""
        pass


class EmbeddingInterface(ABC):
    @abstractmethod
    def encode_text(self, text: str) -> List[float]:
        """Convert text into an embedding vector (384 dimensions)."""
        pass


class LLMInterface(ABC):
    @abstractmethod
    def generate_summary(self, headline: str, content: str) -> str:
        """Generate a 2-3 sentence neutral summary of the article."""
        pass


class EventBusInterface(ABC):
    @abstractmethod
    def publish_matched_article(self, article_id: UUID, topic_id: UUID, relevance_score: float, user_ids: List[UUID]) -> None:
        """Publish an event to the message bus for the Alert Service to consume."""
        pass
