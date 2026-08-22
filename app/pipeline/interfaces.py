from abc import ABC, abstractmethod
from typing import List
from uuid import UUID
from app.pipeline.models import ProcessedArticle, ScoredMatch

# EmbeddingInterface is defined in app/adapters/ai/base.py — the API embeds text
# too, so the contract no longer belongs to the pipeline alone. Re-exported here
# so pipeline modules keep importing it from where they always did.
from app.adapters.ai.base import EmbeddingInterface  # noqa: F401

class DatabaseInterface(ABC):
    @abstractmethod
    def check_url_exists(self, url: str) -> bool:
        """Check if an article URL already exists in the database (pre-embedding dedup)."""
        pass

    @abstractmethod
    def vector_search_duplicate(self, embedding: List[float], threshold: float = 0.95) -> bool:
        """Check if a highly similar article exists after embedding generation."""
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
    def store_dropped_article(self, article: ProcessedArticle) -> None:
        """
        Store an article that matched no topic (status='dropped').

        Keeping it means check_url_exists() recognises the URL on the next
        crawl, so the embedding is never recomputed. The embedding itself is
        retained so a newly created topic can be backfilled against it.
        """
        pass

    @abstractmethod
    def update_article_summary(self, article_id: UUID, summary: str) -> None:
        """Update the article with the generated summary and set status='processed'."""
        pass


class LLMInterface(ABC):
    @abstractmethod
    def generate_summary(self, headline: str, content: str) -> str:
        """Generate a 2-3 sentence neutral summary of the article."""
        pass


class EventBusInterface(ABC):
    @abstractmethod
    def publish_matched_article(self, article_id: UUID, topic_id: UUID, relevance_score: float, user_id: UUID) -> None:
        """Publish an event to the message bus for the Alert Service to consume."""
        pass
