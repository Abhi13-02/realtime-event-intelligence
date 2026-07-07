"""
Password hashing and JWT issuing/verification.

bcrypt hashing is CPU-bound (~100ms by design), so the async wrappers run it
in a worker thread to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

JWT_ALGORITHM = "HS256"


def _hash_password_sync(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password_sync(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        # Malformed hash stored in the DB — treat as auth failure, not a 500
        return False


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(_verify_password_sync, password, password_hash)


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Sign an HS256 JWT for the user. Returns (token, expires_in_seconds)."""
    expires_in = settings.auth_jwt_expiry_days * 24 * 60 * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.auth_jwt_secret, algorithm=JWT_ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Verify signature + expiry and return the payload. Raises jwt exceptions."""
    return jwt.decode(
        token,
        settings.auth_jwt_secret,
        algorithms=[JWT_ALGORITHM],
        leeway=60,  # tolerate small clock skew
    )
