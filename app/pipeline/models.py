from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class RawArticle(BaseModel):
    """
    Input schema directly from the ingestion service (e.g. via Kafka).
    """
    url: HttpUrl
    headline: str
    content: str
    source_id: UUID
    published_at: Optional[datetime] = None

class Topic(BaseModel):
    """
    Represents a tracked user topic.
    """
    id: UUID
    user_id: UUID
    name: str
    sensitivity: str
    embedding: List[float]
    expanded_description: Optional[str] = None
    gdelt_theme_ids: List[str] = Field(default_factory=list)
    
class ProcessedArticle(BaseModel):
    """
    Article representation as it passes through the pipeline.
    """
    raw: RawArticle
    clean_text: Optional[str] = None
    embedding: Optional[List[float]] = None
    id: Optional[UUID] = None # Assigned by database
    summary: Optional[str] = None

class ScoredMatch(BaseModel):
    """
    Represents an article matching a user topic above the topic's threshold.
    """
    topic_id: UUID
    relevance_score: float
    credibility_score: float
