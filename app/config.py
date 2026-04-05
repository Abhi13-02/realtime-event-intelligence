from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All configuration is read from environment variables (your .env file).
    Pydantic validates types automatically — if DATABASE_URL is missing or
    SMTP_PORT is not a number, the app fails immediately on startup with a
    clear error instead of crashing later with a confusing AttributeError.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── App ───────────────────────────────────────────────────────────────
    auth_secret: str
    environment: str = "development"

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str                          # db=0 — Celery broker
    websocket_redis_url: str                # db=1 — WebSocket tickets

    # ── Kafka ─────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str

    # ── Ingestion ─────────────────────────────────────────────────────────
    hn_poll_interval_minutes: float = 10
    reddit_poll_interval_minutes: float = 10

    # ── Sensitivity thresholds ────────────────────────────────────────────
    # Cosine similarity floors per topic sensitivity level.
    # Stage 2 uses these to filter articles per-topic before storing/summarising.
    # Change and restart pipeline-consumer to take effect.
    threshold_broad: float = 0.2
    threshold_balanced: float = 0.4
    threshold_high: float = 0.5

    # ── External APIs ─────────────────────────────────────────────────────
    gemini_api_key: str
    cohere_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str

    # ── Reddit ────────────────────────────────────────────────────────────
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str

    # ── Email ─────────────────────────────────────────────────────────────
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_email: str

    # ── Logging ────────────────────────────────────────────────────────────
    newsapi_key: Optional[str] = None
    newsdata_key: Optional[str] = None
    guardian_key: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    @lru_cache means this function only reads and validates the .env file
    once — on the first call. Every subsequent call returns the same object
    from memory. This means:
      - No repeated disk I/O on every request
      - One consistent settings object shared across the entire app

    Usage in any file:
        from app.config import get_settings
        settings = get_settings()
        print(settings.database_url)
    """
    return Settings()
