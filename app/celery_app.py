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
    include=[
        # "app.tasks.hackernews",  # replaced by GDELT ingestion
        "app.tasks.reddit",
        "app.tasks.sms",
        "app.tasks.email",
        "app.tasks.intelligence_sms",
        "app.tasks.subtheme_discovery",
    ],

    # Serialise task messages as JSON (human-readable, language-agnostic)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Use UTC everywhere — avoids timezone bugs in scheduled tasks
    timezone="UTC",
    enable_utc=True,

    beat_schedule={
        # "crawl-hackernews-every-10min": replaced by GDELT ingestion
        "send-email-digest-midnight": {
            # Sweeps all pending email alerts (article + intelligence) and sends one digest per user.
            "task": "app.tasks.email.send_email_digest",
            "schedule": timedelta(hours=24),  # effectively daily; use crontab(hour=0, minute=0) in prod
        },
        "crawl-reddit-every-10min": {
            "task": "app.tasks.reddit.crawl_reddit",
            "schedule": timedelta(minutes=settings.reddit_poll_interval_minutes),
        },
        "run-subtheme-discovery": {
            # Triggered every SUBTHEME_DISCOVERY_INTERVAL_HOURS hours.
            # Reads from PostgreSQL, clusters GDELT articles, runs VADER sentiment,
            # calls Cohere for labeling, detects evolution, persists and publishes
            # to sub-theme-events Kafka topic.
            "task": "app.tasks.subtheme_discovery.run_subtheme_discovery",
            "schedule": timedelta(hours=settings.subtheme_discovery_interval_hours),
        },
    },
)
