"""Intelligence route handlers.

Pure HTTP controllers: parse and validate the request, call the service, return
the response model. Every SQL statement lives in app/services/intelligence.py.

  GET /topics/{id}/intelligence                        current sub-theme state
  GET /topics/{id}/intelligence/history/timestamps     available run timestamps
  GET /topics/{id}/intelligence/history                state at one run
  GET /topics/{id}/intelligence/sub-themes/{id}        one sub-theme
  GET /topics/{id}/intelligence/sub-themes/{id}/articles  its evidence list
  GET /topics/{id}/intelligence/timeline               one sub-theme's history
  GET /intelligence-alerts                             paginated alert history
  GET /articles/{id}/comments                          Reddit comments
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.intelligence import (
    IntelligenceAlertListResponse,
    IntelligenceResponse,
    RedditCommentsResponse,
    SnapshotTimestampResponse,
    SubThemeArticlesResponse,
    SubThemeItem,
    TimelineResponse,
)
from app.services import intelligence as service

router = APIRouter(tags=["intelligence"])


@router.get("/topics/{topic_id}/intelligence", response_model=IntelligenceResponse)
async def get_topic_intelligence(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceResponse:
    """Current state of all sub-themes for a topic."""
    return await service.get_topic_intelligence(db, topic_id, str(current_user.id))


@router.get(
    "/topics/{topic_id}/intelligence/history/timestamps",
    response_model=SnapshotTimestampResponse,
)
async def get_history_timestamps(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SnapshotTimestampResponse:
    """Timestamps of every discovery run for this topic, newest first."""
    return await service.get_history_timestamps(db, topic_id, str(current_user.id))


@router.get("/topics/{topic_id}/intelligence/history", response_model=IntelligenceResponse)
async def get_topic_history(
    topic_id: UUID,
    timestamp: datetime = Query(..., description="Point-in-time to retrieve narrative state"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceResponse:
    """State of all sub-themes at a specific historical point. Powers the slider."""
    return await service.get_topic_history(db, topic_id, str(current_user.id), timestamp)


@router.get(
    "/topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}",
    response_model=SubThemeItem,
)
async def get_sub_theme(
    topic_id: UUID,
    sub_theme_id: UUID,
    at: datetime | None = Query(
        default=None,
        description="Run timestamp to render. Omit for the most recent snapshot.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubThemeItem:
    """One sub-theme, at a point in time. No status filter — dormant resolves fine."""
    return await service.get_sub_theme(
        db, topic_id, sub_theme_id, str(current_user.id), at=at
    )


@router.get("/topics/{topic_id}/intelligence/timeline", response_model=TimelineResponse)
async def get_intelligence_timeline(
    topic_id: UUID,
    sub_theme_id: UUID = Query(..., description="Sub-theme whose snapshot history to return"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TimelineResponse:
    """Snapshot history for one sub-theme, newest first."""
    return await service.get_timeline(
        db, topic_id, sub_theme_id, str(current_user.id), limit
    )


@router.get("/intelligence-alerts", response_model=IntelligenceAlertListResponse)
async def list_intelligence_alerts(
    topic_id: UUID | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IntelligenceAlertListResponse:
    """Intelligence alerts for the authenticated user, newest first."""
    return await service.list_intelligence_alerts(
        db,
        str(current_user.id),
        topic_id=topic_id,
        alert_type=alert_type,
        page=page,
        limit=limit,
    )


@router.get(
    "/topics/{topic_id}/intelligence/sub-themes/{sub_theme_id}/articles",
    response_model=SubThemeArticlesResponse,
)
async def get_sub_theme_articles(
    topic_id: UUID,
    sub_theme_id: UUID,
    at: datetime | None = Query(
        default=None,
        description="Run timestamp to render. Omit for the most recent run.",
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubThemeArticlesResponse:
    """Paginated articles belonging to a sub-theme, as of one discovery run."""
    return await service.get_sub_theme_articles(
        db, topic_id, sub_theme_id, str(current_user.id), at=at, page=page, limit=limit
    )


@router.get("/articles/{article_id}/comments", response_model=RedditCommentsResponse)
async def get_article_comments(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RedditCommentsResponse:
    """Analyzed Reddit comments for a specific article/post."""
    return await service.get_article_comments(db, article_id)
