from app.config import get_settings

REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"

RETRY_BACKOFFS = [0, 60, 300, 1800]  # seconds between Twilio retry attempts


def get_sync_db_url() -> str:
    """Convert async DB URL to psycopg2-compatible sync URL."""
    return get_settings().database_url.replace("postgresql+asyncpg", "postgresql")
