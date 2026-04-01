"""
FastAPI dependencies shared across all route handlers.

get_current_user is currently a STUB that returns a hardcoded mock user.
This lets every endpoint work end-to-end during development without auth.

When auth is built (Step 7), swap this function's body to verify the
NextAuth JWT from the Authorization header and do just-in-time provisioning.
Nothing else in the codebase needs to change — all routes already call
Depends(get_current_user), so swapping the implementation here is enough.
"""

import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db

# Stable UUID for the dev mock user.
# Every route that calls Depends(get_current_user) will receive this user.
_MOCK_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    """
    Returns the authenticated user.

    DEV STUB: always returns a fixed mock user. Creates the user row on
    first call so all foreign key constraints are satisfied.

    PRODUCTION: replace body with NextAuth JWT verification.
    """
    result = await db.execute(select(User).where(User.id == _MOCK_USER_ID))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=_MOCK_USER_ID,
            name="Dev User",
            email="dev@localhost",
            google_sub="mock-google-sub-dev",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user
