"""
FastAPI dependencies shared across all route handlers.
get_current_user verifies Clerk JWT tokens and does just-in-time user provisioning.
"""
import uuid
import jwt
import httpx
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

security = HTTPBearer(auto_error=False)
settings = get_settings()

# Cache Clerk's public keys globally in memory
_clerk_jwks = None

async def get_clerk_jwks():
    """Asynchronously fetch JWKS to prevent blocking the FastAPI event loop."""
    global _clerk_jwks
    if _clerk_jwks is None:
        jwks_url = f"https://{settings.clerk_app_domain}/.well-known/jwks.json"
        # Using httpx instead of requests for async support
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url)
            _clerk_jwks = response.json()
    return _clerk_jwks


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Returns the authenticated user by verifying the Clerk JWT token.
    In development mode, skips Clerk and returns a seeded dev user.
    """
    if settings.environment == "development":
        dev_uuid = uuid.uuid5(uuid.NAMESPACE_URL, settings.dev_user_id)
        result = await db.execute(select(User).where(User.id == dev_uuid))
        user = result.scalar_one_or_none()
        if user is None:
            try:
                user = User(
                    id=dev_uuid,
                    name="Dev User",
                    email="dev@localhost",
                    google_sub=settings.dev_user_id,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
            except IntegrityError:
                await db.rollback()
                result = await db.execute(select(User).where(User.email == "dev@localhost"))
                user = result.scalar_one()
        return user

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    token = credentials.credentials
    
    try:
        # Decode without verification first to get header
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        
        # Await the async JWKS fetch
        jwks = await get_clerk_jwks()
        public_key = None
        for key in jwks['keys']:
            if key['kid'] == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
        
        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token key"
            )
        
        # Verify and decode the token
        payload = jwt.decode(
        token,
        public_key,
        algorithms=['RS256'],
        options={"verify_aud": False}
        )
        
        clerk_user_id = payload['sub']
        # Fallbacks just in case Clerk doesn't pass email/name in the token
        email = payload.get('email', f"{clerk_user_id}@clerk.local")
        name = payload.get('name', "Verified User")
        
        # FIX: Convert Clerk string ID to a deterministic UUID
        # This prevents SQLAlchemy from crashing and requires zero DB migrations.
        db_user_id = uuid.uuid5(uuid.NAMESPACE_URL, clerk_user_id)
        
        # Check if user exists, create if not
        result = await db.execute(select(User).where(User.id == db_user_id))
        user = result.scalar_one_or_none()
        
        if user is None:
            user = User(
                id=db_user_id,
                name=name,
                email=email,
                google_sub=clerk_user_id, # Safely store the original string here
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        return user
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    except Exception as e:
        print(f"CRITICAL AUTH ERROR: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )