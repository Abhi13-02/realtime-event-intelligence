"""
Admin-only routes for system management and multi-user oversight.
Protected by the X-Admin-Key header.

Pure HTTP controllers: authenticate, validate, delegate. Every SQL statement
lives in app/services/admin.py.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import get_db
from app.services import admin as service

settings = get_settings()

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request models ───────────────────────────────────────────────────────────

class SystemSettingUpdate(BaseModel):
    value: Any


class SourceUpdate(BaseModel):
    is_active: Optional[bool] = None
    poll_interval: Optional[int] = None
    articles_per_crawl: Optional[int] = None


class FeedUpdate(BaseModel):
    is_active: Optional[bool] = None
    articles_per_crawl: Optional[int] = None


class RedditSubredditCreate(BaseModel):
    name: str
    limit_per_crawl: int = 10
    sort: str = "new"


class RedditSubredditUpdate(BaseModel):
    is_active: Optional[bool] = None
    limit_per_crawl: Optional[int] = None
    sort: Optional[str] = None


async def require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Dependency to ensure the request has a valid admin secret key."""
    if not x_admin_key or x_admin_key != settings.admin_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin secret key",
        )


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users_admin(db: AsyncSession = Depends(get_db)):
    """List all users in the system with their topic counts."""
    return await service.list_users(db)


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
async def delete_user_admin(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a user and all their associated data (topics, alerts, etc.)."""
    return await service.delete_user(db, user_id)


@router.get("/users/{user_id}/topics", dependencies=[Depends(require_admin)])
async def list_user_topics_admin(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all topics for a specific user."""
    return await service.list_user_topics(db, user_id)


# ── Discovery triggers ───────────────────────────────────────────────────────

@router.post(
    "/users/{user_id}/topics/{topic_id}/discover",
    dependencies=[Depends(require_admin)],
)
async def discover_topic_admin(user_id: uuid.UUID, topic_id: uuid.UUID):
    """Trigger sub-theme discovery for a specific topic."""
    task = celery_app.send_task(
        "app.tasks.subtheme_discovery.run_subtheme_discovery_for_topic",
        args=[str(topic_id)],
    )
    return {"task_id": task.id, "status": "queued"}


@router.post("/discover/all", dependencies=[Depends(require_admin)])
async def discover_all_admin():
    """Trigger sub-theme discovery for all topics globally."""
    task = celery_app.send_task("app.tasks.subtheme_discovery.run_subtheme_discovery")
    return {"task_id": task.id, "status": "queued"}


# ── System stats ─────────────────────────────────────────────────────────────

@router.get("/sources", dependencies=[Depends(require_admin)])
async def source_stats(db: AsyncSession = Depends(get_db)):
    """Articles per source — total, last 24h, last 1h."""
    return await service.source_stats(db)


@router.get("/pipeline", dependencies=[Depends(require_admin)])
async def pipeline_stats(db: AsyncSession = Depends(get_db)):
    """Article counts by pipeline_status and summary presence."""
    return await service.pipeline_stats(db)


# ── Sub-themes ───────────────────────────────────────────────────────────────

@router.get("/subthemes", dependencies=[Depends(require_admin)])
async def subtheme_stats(db: AsyncSession = Depends(get_db)):
    """All sub-themes across all users."""
    return await service.subtheme_stats(db)


@router.get(
    "/users/{user_id}/topics/{topic_id}/subthemes",
    dependencies=[Depends(require_admin)],
)
async def list_topic_subthemes_admin(
    user_id: uuid.UUID, topic_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """List sub-themes for a specific topic."""
    return await service.list_topic_subthemes(db, topic_id)


@router.delete("/subthemes/{subtheme_id}", dependencies=[Depends(require_admin)])
async def delete_subtheme_admin(subtheme_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a specific sub-theme."""
    return await service.delete_subtheme(db, subtheme_id)


@router.delete(
    "/users/{user_id}/topics/{topic_id}/subthemes",
    dependencies=[Depends(require_admin)],
)
async def delete_topic_subthemes_admin(
    user_id: uuid.UUID, topic_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """Delete all sub-themes for a specific topic."""
    return await service.delete_topic_subthemes(db, topic_id)


@router.delete("/subthemes", dependencies=[Depends(require_admin)])
async def delete_all_subthemes_admin(db: AsyncSession = Depends(get_db)):
    """Wipe ALL sub_themes rows."""
    return await service.delete_all_subthemes(db)


# ── Articles ─────────────────────────────────────────────────────────────────

@router.get("/articles", dependencies=[Depends(require_admin)])
async def list_articles_admin(
    db: AsyncSession = Depends(get_db),
    include_dropped: bool = False,
    limit: int = Query(500, ge=1, le=5000),
):
    """
    List articles for debugging.

    Articles with pipeline_status='dropped' are excluded by default — pass
    include_dropped=true to see them.
    """
    return await service.list_articles(db, include_dropped=include_dropped, limit=limit)


@router.delete("/articles", dependencies=[Depends(require_admin)])
async def delete_all_articles_admin(db: AsyncSession = Depends(get_db)):
    """Wipe all articles (and cascaded data)."""
    return await service.delete_all_articles(db)


# ── Ingestion control ────────────────────────────────────────────────────────

@router.get("/ingestion/sources", dependencies=[Depends(require_admin)])
async def list_sources_admin(db: AsyncSession = Depends(get_db)):
    """List all sources with their current config and status."""
    return await service.list_sources(db)


@router.patch("/ingestion/sources/{source_id}", dependencies=[Depends(require_admin)])
async def update_source_admin(
    source_id: uuid.UUID, update: SourceUpdate, db: AsyncSession = Depends(get_db)
):
    """Update source-level config (toggle active, interval, etc.)."""
    return await service.update_source(db, source_id, update.model_dump(exclude_unset=True))


@router.get(
    "/ingestion/sources/{source_id}/feeds", dependencies=[Depends(require_admin)]
)
async def list_source_feeds_admin(
    source_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """List all RSS feeds for a specific source."""
    return await service.list_source_feeds(db, source_id)


@router.patch("/ingestion/feeds/{feed_id}", dependencies=[Depends(require_admin)])
async def update_feed_admin(
    feed_id: uuid.UUID, update: FeedUpdate, db: AsyncSession = Depends(get_db)
):
    """Update feed-level config (toggle active, limit)."""
    return await service.update_feed(db, feed_id, update.model_dump(exclude_unset=True))


@router.get("/ingestion/reddit/subreddits", dependencies=[Depends(require_admin)])
async def list_reddit_subreddits_admin(db: AsyncSession = Depends(get_db)):
    """List all subreddits being monitored."""
    return await service.list_reddit_subreddits(db)


@router.post("/ingestion/reddit/subreddits", dependencies=[Depends(require_admin)])
async def add_reddit_subreddit_admin(
    subreddit: RedditSubredditCreate, db: AsyncSession = Depends(get_db)
):
    """Add a new subreddit to monitor."""
    return await service.add_reddit_subreddit(db, subreddit.model_dump())


@router.patch("/ingestion/reddit/subreddits/{id}", dependencies=[Depends(require_admin)])
async def update_reddit_subreddit_admin(
    id: uuid.UUID, update: RedditSubredditUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit subreddit settings or toggle active state."""
    return await service.update_reddit_subreddit(
        db, id, update.model_dump(exclude_unset=True)
    )


@router.delete("/ingestion/reddit/subreddits/{id}", dependencies=[Depends(require_admin)])
async def delete_reddit_subreddit_admin(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Stop monitoring a subreddit."""
    return await service.delete_reddit_subreddit(db, id)


# ── System settings ──────────────────────────────────────────────────────────

@router.get("/settings", dependencies=[Depends(require_admin)])
async def list_settings_admin(db: AsyncSession = Depends(get_db)):
    """List all system settings. Seeds any that are missing."""
    return await service.list_settings(db)


@router.patch("/settings/{key}", dependencies=[Depends(require_admin)])
async def update_setting_admin(
    key: str, update: SystemSettingUpdate, db: AsyncSession = Depends(get_db)
):
    """Update a specific system setting."""
    return await service.update_setting(db, key, update.value)
