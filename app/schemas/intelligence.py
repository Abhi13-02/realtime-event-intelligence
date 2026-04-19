"""Intelligence layer Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── GET /topics/{topic_id}/intelligence ───────────────────────────────────────

class RepresentativeArticle(BaseModel):
    """The GDELT article closest to the sub-theme centroid."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    headline: str
    url: str
    image_url: str | None
    source_name: str


class SubThemeItem(BaseModel):
    """Single sub-theme as returned by GET /topics/{id}/intelligence."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str | None
    description: str | None
    keywords: list[str]
    status: str
    article_count: int
    reddit_post_count: int
    total_volume: int
    sentiment_score: float | None
    representative_article: RepresentativeArticle | None
    first_seen_at: datetime
    last_seen_at: datetime


class IntelligenceResponse(BaseModel):
    """Response for GET /topics/{topic_id}/intelligence."""
    topic_id: UUID
    topic_name: str
    sensitivity: str
    sub_themes: list[SubThemeItem]


# ── GET /topics/{topic_id}/intelligence/timeline ──────────────────────────────

class SnapshotItem(BaseModel):
    """A single point-in-time snapshot of a sub-theme."""
    model_config = ConfigDict(from_attributes=True)

    snapshot_at: datetime
    article_count: int
    reddit_post_count: int
    total_volume: int
    sentiment_score: float | None
    status: str


class TimelineResponse(BaseModel):
    """Response for GET /topics/{topic_id}/intelligence/timeline."""
    sub_theme_id: UUID
    sub_theme_label: str | None
    snapshots: list[SnapshotItem]


# ── GET /intelligence-alerts ──────────────────────────────────────────────────

class IntelligenceAlertItem(BaseModel):
    """Single intelligence alert row."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: str
    topic_id: UUID
    topic_name: str
    sub_theme_id: UUID
    channel: str
    status: str
    payload: dict[str, Any]
    created_at: datetime


class IntelligenceAlertListResponse(BaseModel):
    """Paginated intelligence alert list."""
    data: list[IntelligenceAlertItem]
    total_count: int
    page: int
    limit: int

# ── GET /topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}/articles ──

class SubThemeArticleItem(BaseModel):
    """An article belonging to a specific sub-theme."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    headline: str
    url: str
    image_url: str | None
    summary: str | None
    published_at: datetime | None
    source_name: str
    membership_type: str
    similarity_to_centroid: float | None

class SubThemeArticlesResponse(BaseModel):
    """Paginated list of articles for a sub-theme."""
    data: list[SubThemeArticleItem]
    total_count: int
    page: int
    limit: int

