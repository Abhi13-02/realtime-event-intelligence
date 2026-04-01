"""Async engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

# One engine for the entire process — holds the async connection pool.
engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,   # drop stale connections before handing them to a request
)

# One factory for the entire process — stamps out AsyncSession objects on demand.
# expire_on_commit=False: prevents SQLAlchemy from expiring loaded attributes after
# a commit, which would trigger implicit lazy-loads and crash in an async context.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency. Yields one AsyncSession per request, then closes it.

    Usage:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
