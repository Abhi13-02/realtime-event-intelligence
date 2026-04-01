"""Topic route handlers."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.services.topics import (
    create_topic,
    delete_topic,
    get_topic,
    list_topics,
    replace_topic_channels,
    update_topic,
)

router = APIRouter(prefix="/topics", tags=["topics"])


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
