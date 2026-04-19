"""Alert schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlertItem(BaseModel):
    """Single alert row as returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_id: UUID
    topic_name: str
    article_id: UUID
    headline: str
    summary: str | None
    url: str
    image_url: str | None
    source_name: str
    relevance_score: float
    channel: str
    created_at: datetime


class AlertListResponse(BaseModel):
    """Paginated alert list."""

    data: list[AlertItem]
    total_count: int
    page: int
    limit: int
