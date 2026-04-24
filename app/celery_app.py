from celery import Celery
from app.config import get_settings
from app.tasks.beat_schedules.registry import BEAT_SCHEDULE

settings = get_settings()

celery_app = Celery(
    "realtimeintel",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    include=[
        "app.tasks.ingestion.reddit",
        "app.tasks.ingestion.rss_scrapper",
        "app.tasks.ingestion.api_scrapers",
        "app.tasks.ingestion.dispatchers",
        "app.tasks.notifications.sms",
        "app.tasks.notifications.email",
        "app.tasks.notifications.intelligence_sms",
        "app.tasks.discovery.subtheme_discovery",
    ],

    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    task_routes={
        "app.tasks.subtheme_discovery.*": {"queue": "discovery"},
    },

    beat_schedule=BEAT_SCHEDULE,
)
