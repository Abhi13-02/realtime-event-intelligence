"""Topic services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Topic, TopicChannel, User
from app.schemas.topics import (
    DeliveryChannel,
    TopicChannelItem,
    TopicCreateRequest,
    TopicListItem,
    TopicListResponse,
    TopicPatchRequest,
    TopicResponse,
)


class TopicServiceError(Exception):
    """Structured API-facing error from the topic service."""

    def __init__(self, status_code: int, error: str, code: str) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.code = code


@dataclass(slots=True)
class TopicDerivedFields:
    """Expanded topic text and embedding used for persistence."""

    expanded_description: str
    embedding: list[float]


def _normalize_topic_name(name: str) -> str:
    return name.strip()


def _normalized_name_key(name: str) -> str:
    return _normalize_topic_name(name).casefold()


async def _topic_count_for_user(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Topic).where(Topic.user_id == user_id)
    )
    return int(result.scalar_one())


async def _find_duplicate_topic(
    db: AsyncSession,
    *,
    user_id: UUID,
    normalized_name: str,
    exclude_topic_id: UUID | None = None,
) -> Topic | None:
    query = select(Topic).where(
        Topic.user_id == user_id,
        func.lower(func.btrim(Topic.name)) == normalized_name,
    )
    if exclude_topic_id is not None:
        query = query.where(Topic.id != exclude_topic_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _get_owned_topic(db: AsyncSession, *, topic_id: UUID, user_id: UUID) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise TopicServiceError(404, "Topic not found.", "TOPIC_NOT_FOUND")
    return topic


async def _derive_topic_fields(name: str, description: str | None) -> TopicDerivedFields:
    from app.core.embeddings import EmbeddingGenerationError, get_embedder
    from app.core.gemini import TopicExpansionError, get_topic_expander

    expander = get_topic_expander()
    embedder = get_embedder()

    try:
        expanded_description = await asyncio.to_thread(
            expander.expand_topic,
            name,
            description,
        )
    except TopicExpansionError as exc:
        raise TopicServiceError(
            503,
            "Gemini API unavailable during topic expansion.",
            "GEMINI_UNAVAILABLE",
        ) from exc

    try:
        embedding = await asyncio.to_thread(embedder.encode_text, expanded_description)
    except EmbeddingGenerationError as exc:
        raise TopicServiceError(
            503,
            "Embedding model unavailable during topic processing.",
            "EMBEDDING_UNAVAILABLE",
        ) from exc

    return TopicDerivedFields(
        expanded_description=expanded_description,
        embedding=embedding,
    )


def _topic_response(topic: Topic) -> TopicResponse:
    return TopicResponse.model_validate(topic)


def _topic_list_item(topic: Topic) -> TopicListItem:
    return TopicListItem.model_validate(topic)


def _unique_channels(channels: list[TopicChannelItem]) -> list[DeliveryChannel]:
    unique_values = dict.fromkeys(item.channel for item in channels)
    return list(unique_values)


async def create_topic(
    db: AsyncSession,
    *,
    user: User,
    payload: TopicCreateRequest,
) -> TopicResponse:
    normalized_name = _normalized_name_key(payload.name)

    duplicate = await _find_duplicate_topic(
        db,
        user_id=user.id,
        normalized_name=normalized_name,
    )
    if duplicate is not None:
        raise TopicServiceError(
            409,
            "User already has a topic with this name.",
            "DUPLICATE_TOPIC_NAME",
        )

    if await _topic_count_for_user(db, user.id) >= 10:
        raise TopicServiceError(
            400,
            "A user can track at most 10 topics.",
            "TOPIC_LIMIT_REACHED",
        )

    derived_fields = await _derive_topic_fields(payload.name, payload.description)
    topic = Topic(
        user_id=user.id,
        name=_normalize_topic_name(payload.name),
        description=payload.description,
        expanded_description=derived_fields.expanded_description,
        embedding=derived_fields.embedding,
        sensitivity=payload.sensitivity.value,
        is_active=True,
    )

    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return _topic_response(topic)


async def list_topics(
    db: AsyncSession,
    *,
    user: User,
    page: int,
    limit: int,
) -> TopicListResponse:
    total_count = await _topic_count_for_user(db, user.id)
    offset = (page - 1) * limit

    result = await db.execute(
        select(Topic)
        .where(Topic.user_id == user.id)
        .order_by(Topic.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    topics = result.scalars().all()

    return TopicListResponse(
        data=[_topic_list_item(topic) for topic in topics],
        total_count=total_count,
        page=page,
        limit=limit,
    )


async def get_topic(
    db: AsyncSession,
    *,
    user: User,
    topic_id: UUID,
) -> TopicResponse:
    topic = await _get_owned_topic(db, topic_id=topic_id, user_id=user.id)
    return _topic_response(topic)


async def update_topic(
    db: AsyncSession,
    *,
    user: User,
    topic_id: UUID,
    payload: TopicPatchRequest,
) -> TopicResponse:
    topic = await _get_owned_topic(db, topic_id=topic_id, user_id=user.id)
    provided_fields = payload.model_fields_set

    if "name" in provided_fields:
        normalized_name = _normalized_name_key(payload.name or "")
        duplicate = await _find_duplicate_topic(
            db,
            user_id=user.id,
            normalized_name=normalized_name,
            exclude_topic_id=topic.id,
        )
        if duplicate is not None:
            raise TopicServiceError(
                409,
                "User already has a topic with this name.",
                "DUPLICATE_TOPIC_NAME",
            )

    new_name = topic.name if "name" not in provided_fields else _normalize_topic_name(payload.name or "")
    new_description = topic.description if "description" not in provided_fields else payload.description

    text_changed = (
        "name" in provided_fields
        and new_name != topic.name
    ) or (
        "description" in provided_fields
        and new_description != topic.description
    )

    if "name" in provided_fields:
        topic.name = new_name
    if "description" in provided_fields:
        topic.description = new_description
    if payload.sensitivity is not None:
        topic.sensitivity = payload.sensitivity.value
    if payload.is_active is not None:
        topic.is_active = payload.is_active

    if text_changed:
        derived_fields = await _derive_topic_fields(new_name, new_description)
        topic.expanded_description = derived_fields.expanded_description
        topic.embedding = derived_fields.embedding

    await db.commit()
    await db.refresh(topic)
    return _topic_response(topic)


async def delete_topic(
    db: AsyncSession,
    *,
    user: User,
    topic_id: UUID,
) -> None:
    topic = await _get_owned_topic(db, topic_id=topic_id, user_id=user.id)
    await db.delete(topic)
    await db.commit()


async def replace_topic_channels(
    db: AsyncSession,
    *,
    user: User,
    topic_id: UUID,
    channels: list[TopicChannelItem],
) -> list[TopicChannelItem]:
    topic = await _get_owned_topic(db, topic_id=topic_id, user_id=user.id)
    unique_channels = _unique_channels(channels)

    if DeliveryChannel.sms in unique_channels and not user.phone_number:
        raise TopicServiceError(
            400,
            "SMS channel requested but no phone number is configured for this user.",
            "PHONE_NUMBER_REQUIRED",
        )

    await db.execute(delete(TopicChannel).where(TopicChannel.topic_id == topic.id))

    for channel in unique_channels:
        db.add(TopicChannel(topic_id=topic.id, channel=channel.value))

    await db.commit()
    return [TopicChannelItem(channel=channel) for channel in unique_channels]
