"""Auth route handlers — email + password credentials owned by the backend."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.schemas.users import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Create a user with a bcrypt-hashed password and return a signed JWT."""
    email = payload.email.lower()

    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        name=payload.name,
        email=email,
        password_hash=await hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Race: same email registered between the SELECT and the INSERT
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    await db.refresh(user)

    token, expires_in = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Verify credentials and return a signed JWT plus the user profile."""
    email = payload.email.lower()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Same error for unknown email and wrong password — do not leak which
    # emails have accounts.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

    if user is None or user.password_hash is None:
        # Burn a bcrypt verification anyway so response timing does not
        # reveal whether the email exists.
        await verify_password(payload.password, _DUMMY_HASH)
        raise invalid

    if not await verify_password(payload.password, user.password_hash):
        raise invalid

    token, expires_in = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


# Valid bcrypt hash of a random unguessable string; used only to equalise
# login timing for nonexistent accounts.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZDCbkfESKu3xEcHDlLm64ZBoYK9OZG"
