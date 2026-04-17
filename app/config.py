from functools import lru_cache
from typing import Any, Dict, List, Optional
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
    rss_poll_interval_minutes: float = 1
    hn_poll_interval_minutes: float = 1
    reddit_poll_interval_minutes: float = 1
    newsapi_poll_interval_minutes: float = 30
    newsdata_poll_interval_minutes: float = 30

    # ── Sensitivity thresholds ────────────────────────────────────────────
    # Cosine similarity floors per topic sensitivity level.
    # Stage 2 uses these to filter articles per-topic before storing/summarising.
    # Change and restart pipeline-consumer to take effect.
    threshold_broad: float = 0.40
    threshold_balanced: float = 0.45
    threshold_high: float = 0.55

    # ── External APIs ─────────────────────────────────────────────────────
    gemini_api_key: str
    cohere_api_key: str
    groq_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str

    # ── Reddit ────────────────────────────────────────────────────────────
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    reddit_subreddits: List[Dict[str, Any]] = [
        {"name": "MachineLearning", "limit": 10, "sort": "new"},
        {"name": "technology", "limit": 10, "sort": "new"},
        {"name": "worldnews", "limit": 10, "sort": "new"},
        {"name": "science", "limit": 10, "sort": "new"},
        {"name": "news", "limit": 10, "sort": "new"},
        {"name": "geopolitics", "limit": 10, "sort": "new"},
        {"name": "Futurology", "limit": 10, "sort": "new"},
        {"name": "inthenews", "limit": 10, "sort": "new"},
        {"name": "TrueReddit", "limit": 10, "sort": "new"}
    ]

    # ── Email ───────────────────────────────────────────────────────────────────
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_email: str

    # ── News API keys ─────────────────────────────────────────────────────
    newsapi_key: Optional[str] = None
    newsdata_key: Optional[str] = None
    guardian_key: Optional[str] = None

    # ── Intelligence layer (sub-theme discovery) ──────────────────────────
    # All thresholds configurable via env vars — nothing is hardcoded in tasks.
    # See docs/low-level-design/intelligence-lld.md Section 10 for full descriptions.
    subtheme_discovery_interval_hours: int        = 6
    subtheme_window_days: int                     = 3      # rolling window for all sources
    subtheme_min_articles: int                    = 5
    subtheme_min_cluster_size: int                = 3
    subtheme_min_samples: int                     = 2
    subtheme_centroid_match_threshold: float      = 0.80
    subtheme_reddit_assign_threshold: float       = 0.55
    subtheme_growing_threshold: float             = 0.5
    subtheme_disappearing_threshold: float        = 0.2
    subtheme_sentiment_shift_threshold: float     = 0.2
    subtheme_baseline_days: int                   = 7
    subtheme_relabel_volume_change_threshold: float = 0.5


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
