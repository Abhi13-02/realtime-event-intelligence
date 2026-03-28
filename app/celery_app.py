from celery import Celery
from app.config import get_settings

settings = get_settings()

# broker  — where Celery Beat drops task messages (Redis db=0)
# backend — where task results are stored (same Redis db=0)
# Tasks in this project don't use result storage (fire-and-forget),
# but setting backend=broker is standard practice.
celery_app = Celery(
    "realtimeintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    # Serialise task messages as JSON (human-readable, language-agnostic)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Use UTC everywhere — avoids timezone bugs in scheduled tasks
    timezone="UTC",
    enable_utc=True,

    # Beat schedule — empty for now.
    # Crawl tasks (crawl_bbc, crawl_reddit, etc.) will be registered here
    # when the ingestion service is implemented.
    beat_schedule={},
)
