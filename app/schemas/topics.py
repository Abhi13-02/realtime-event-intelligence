"""Topic schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)


class SensitivityLevel(str, Enum):
    """Allowed user-facing sensitivity values."""

    broad = "broad"
    balanced = "balanced"
    high = "high"


class DeliveryChannel(str, Enum):
    """Allowed delivery channel values."""

    email = "email"
    sms = "sms"
    websocket = "websocket"


class TopicCreateRequest(BaseModel):
    """Payload for creating a topic."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sensitivity: SensitivityLevel = SensitivityLevel.balanced

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TopicPatchRequest(BaseModel):
    """Partial payload for updating a topic."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sensitivity: SensitivityLevel | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_nullable_name(self) -> "TopicPatchRequest":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        return self


class TopicResponse(BaseModel):
    """Full topic response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    expanded_description: str | None
    sensitivity: SensitivityLevel
    is_active: bool
    created_at: datetime


class TopicListItem(BaseModel):
    """Topic list row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    sensitivity: SensitivityLevel
    is_active: bool
    created_at: datetime


class TopicListResponse(BaseModel):
    """Paginated list of topics."""

    data: list[TopicListItem]
    total_count: int
    page: int
    limit: int


class TopicSubtopicItem(BaseModel):
    """Single subtopic row returned by GET /topics/{id}/subtopics."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    created_at: datetime


class TopicSubtopicsResponse(BaseModel):
    """Response for GET /topics/{id}/subtopics."""

    topic_id: UUID
    topic_name: str
    subtopics: list[TopicSubtopicItem]
    count: int


class TopicChannelItem(BaseModel):
    """Channel item used by PUT /topics/{id}/channels."""

    channel: DeliveryChannel


class TopicChannelsUpdateRequest(RootModel[list[TopicChannelItem]]):
    """Raw list payload for replacing topic channels."""


class TopicChannelsResponse(RootModel[list[TopicChannelItem]]):
    """Raw list response for current topic channels."""
