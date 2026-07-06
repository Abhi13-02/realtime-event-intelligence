"""Auth schemas — register/login request and response payloads."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.users import UserResponse


class RegisterRequest(BaseModel):
    """Payload for POST /auth/register."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    """Returned by both register and login — token plus the user profile."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the token expires
    user: UserResponse
