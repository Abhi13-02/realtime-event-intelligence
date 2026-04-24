"""
FastAPI dependencies shared across all route handlers.
get_current_user verifies Clerk JWT tokens and does just-in-time user provisioning.
"""
import logging
import uuid
import jwt
import httpx
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

logger = logging.getLogger(__name__)
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
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    x_as_user_id: Optional[uuid.UUID] = Header(None, alias="X-As-User-Id"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Returns the authenticated user. Supports:
    1. Clerk JWT token (normal user)
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

    # 2. Normal Clerk JWT logic
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
        
    token = credentials.credentials
    
    try:
        # Decode without verification first to get header
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        
        jwks = await get_clerk_jwks()
        public_key = None
        
        def find_key(kid, jwks_dict):
            for key in jwks_dict['keys']:
                if key['kid'] == kid:
                    return jwt.algorithms.RSAAlgorithm.from_jwk(key)
            return None

        public_key = find_key(kid, jwks)

        # FIX: If key isn't found, Clerk might have rotated keys!
        # Clear the cache and force a fresh fetch.
        if not public_key:
            global _clerk_jwks
            _clerk_jwks = None # Clear stale cache
            jwks = await get_clerk_jwks() # Fetch fresh keys
            public_key = find_key(kid, jwks) # Try finding it again
            
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
        options={"verify_aud": False},
        leeway=60  # Add some leeway for clock skew
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
            # Fetch user details from Clerk API because they aren't in the JWT by default
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://api.clerk.com/v1/users/{clerk_user_id}",
                        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"}
                    )
                    if resp.status_code == 200:
                        clerk_data = resp.json()
                        email_addresses = clerk_data.get("email_addresses", [])
                        if email_addresses:
                            email = email_addresses[0].get("email_address", email)
                        first_name = clerk_data.get("first_name", "")
                        last_name = clerk_data.get("last_name", "")
                        if first_name or last_name:
                            name = f"{first_name} {last_name}".strip()
            except Exception as e:
                logger.error("Failed to fetch Clerk user info: %s", e)

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
        logger.critical("Auth error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )