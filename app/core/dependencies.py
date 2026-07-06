"""
FastAPI dependencies shared across all route handlers.
get_current_user verifies backend-issued HS256 JWTs (see app/core/security.py).
"""
import logging
import uuid
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
settings = get_settings()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    x_as_user_id: Optional[uuid.UUID] = Header(None, alias="X-As-User-Id"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Returns the authenticated user. Supports:
    1. Backend-issued JWT (normal user, sub = user UUID)
    2. Admin secret key + target user ID (admin acting as user)
    """
    # 1. Admin bypass logic
    if x_admin_key:
        if x_admin_key != settings.admin_secret_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin key"
            )

        if not x_as_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin must provide X-As-User-Id to call user routes"
            )

        result = await db.execute(select(User).where(User.id == x_as_user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return user

    # 2. Normal JWT logic
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists"
        )
    return user
