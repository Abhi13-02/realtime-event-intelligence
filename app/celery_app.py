from celery import Celery
from datetime import timedelta
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
    # Modules the worker imports on startup — this is what causes
    # @celery_app.task decorated functions to register themselves.
    # Without this, [tasks] in the worker log is empty and Beat's
    # messages land in the queue but nobody can execute them.
    include=["app.tasks.hackernews"],

    # Serialise task messages as JSON (human-readable, language-agnostic)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Use UTC everywhere — avoids timezone bugs in scheduled tasks
    timezone="UTC",
    enable_utc=True,

    beat_schedule={
        "crawl-hackernews-every-10min": {
            # Must match the `name=` on the @celery_app.task decorator exactly.
            "task": "app.tasks.hackernews.crawl_hackernews",
            # */10 means "every minute that is divisible by 10": 00, 10, 20, 30, 40, 50.
            "schedule": timedelta(minutes=settings.hn_poll_interval_minutes),
        },
    },
)
