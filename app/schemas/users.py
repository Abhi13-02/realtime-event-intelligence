"""User schemas."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserResponse(BaseModel):
    """Returned for GET /users/me and PATCH /users/me."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    phone_number: str | None
    created_at: datetime


class UserPatchRequest(BaseModel):
    """
    Partial update payload for PATCH /users/me.

    Only name and phone_number are user-editable.
    Email is read-only — it comes from Google OAuth.
    Send only the fields you want to change.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        # E.164 format: + followed by 7-15 digits
        if not re.fullmatch(r"\+[1-9]\d{6,14}", value):
            raise ValueError(
                "phone_number must be in E.164 format, e.g. +919876543210"
            )
        return value
