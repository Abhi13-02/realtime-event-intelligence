"""Topic route handlers."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.config import get_settings
from app.core.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.topics import (
    TopicChannelsResponse,
    TopicChannelsUpdateRequest,
    TopicCreateRequest,
    TopicListResponse,
    TopicPatchRequest,
    TopicResponse,
    TopicSubtopicsResponse,
)
from app.services.topics import (
    create_topic,
    delete_topic,
    get_topic,
    list_topic_subtopics,
    list_topics,
    replace_topic_channels,
    update_topic,
)

router = APIRouter(prefix="/topics", tags=["topics"])

_redis: aioredis.Redis | None = None
def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


@router.post("", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
async def create_topic_route(
    payload: TopicCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicResponse:
    return await create_topic(db, user=current_user, payload=payload)


@router.get("", response_model=TopicListResponse)
async def list_topics_route(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicListResponse:
    return await list_topics(db, user=current_user, page=page, limit=limit)


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic_route(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicResponse:
    return await get_topic(db, user=current_user, topic_id=topic_id)


@router.patch("/{topic_id}", response_model=TopicResponse)
async def update_topic_route(
    topic_id: UUID,
    payload: TopicPatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicResponse:
    return await update_topic(db, user=current_user, topic_id=topic_id, payload=payload)


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic_route(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    await delete_topic(db, user=current_user, topic_id=topic_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{topic_id}/subtopics", response_model=TopicSubtopicsResponse)
async def list_topic_subtopics_route(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicSubtopicsResponse:
    return await list_topic_subtopics(db, user=current_user, topic_id=topic_id)


@router.put("/{topic_id}/channels", response_model=TopicChannelsResponse)
async def replace_topic_channels_route(
    topic_id: UUID,
    payload: TopicChannelsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TopicChannelsResponse:
    channels = await replace_topic_channels(
        db,
        user=current_user,
        topic_id=topic_id,
        channels=payload.root,
    )
    return TopicChannelsResponse(root=channels)


@router.post("/{topic_id}/discover")
async def trigger_topic_discovery(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Trigger sub-theme discovery for one of the authenticated user's topics.
    Tracks job in Redis and returns immediately to avoid blocking.
    """
    # Ownership check — raises TopicServiceError (404) if not user's topic
    await get_topic(db, user=current_user, topic_id=topic_id)

    redis = get_redis()
    redis_key = f"discovery_task:{topic_id}"
    
    # Check if a discovery task is already running
    existing_task_id = await redis.get(redis_key)
    if existing_task_id:
        result = AsyncResult(existing_task_id, app=celery_app)
        if result.state in ["PENDING", "STARTED", "PROGRESS"]:
            raise HTTPException(status_code=400, detail="Discovery is already running for this topic.")

    # Debounce check to prevent spam-clicking
    debounce_key = f"discovery_debounce:{topic_id}"
    if await redis.get(debounce_key):
        raise HTTPException(status_code=429, detail="Discovery triggered too recently. Please wait a few minutes.")
    await redis.setex(debounce_key, 300, "1")  # 5 minutes cooldown

    task = celery_app.send_task(
        "app.tasks.subtheme_discovery.run_subtheme_discovery_for_topic",
        args=[str(topic_id)],
    )

    # Store task ID with a 1-hour expiration
    await redis.setex(redis_key, 3600, task.id)

    return {"task_id": task.id, "topic_id": str(topic_id), "status": "processing"}


@router.get("/{topic_id}/discovery/status")
async def get_topic_discovery_status(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Check the progress of a running discovery task.
    """
    # Verify ownership
    await get_topic(db, user=current_user, topic_id=topic_id)
    
    redis = get_redis()
    task_id = await redis.get(f"discovery_task:{topic_id}")
    
    if not task_id:
        return {"status": "idle", "progress": 0}
        
    result = AsyncResult(task_id, app=celery_app)
    
    progress = 0
    message = "Discovering..."
    if result.state == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info.get("progress", 0)
        message = result.info.get("message", "Discovering...")
    elif result.state == "SUCCESS":
        progress = 100
        message = "Discovery Complete"
        
    return {
        "status": result.state,
        "progress": progress,
        "message": message
    }
