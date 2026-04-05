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
        "app.tasks.hackernews",
        "app.tasks.reddit",
        "app.tasks.sms",
        "app.tasks.email",
        "app.tasks.rss",
        "app.tasks.apis",
    ],

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
        "send-email-digest-midnight": {
            # Sweeps all pending email alerts and sends one digest per user.
            "task": "app.tasks.email.send_email_digest",
            "schedule": timedelta(hours=24),  # effectively daily; use crontab(hour=0, minute=0) in prod
        },
        "crawl-reddit-every-10min": {
            "task": "app.tasks.reddit.crawl_reddit",
            "schedule": timedelta(minutes=settings.reddit_poll_interval_minutes),
        },"crawl-bbc-every-10-mins": {
        "task": "app.tasks.rss.crawl_rss_feed",
        "schedule": 600.0,
        "args": ("https://feeds.bbci.co.uk/news/rss.xml", "38d5e791-5299-4fc3-88e8-b502f02e4dbb"),
    },
    "crawl-nyt-every-10-mins": {
        "task": "app.tasks.rss.crawl_rss_feed",
        "schedule": 600.0,
        "args": ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "ba5c2aa1-976d-4219-b67a-8d94c13929ba"),
    },
    "crawl-aljazeera-every-10-mins": {
        "task": "app.tasks.rss.crawl_rss_feed",
        "schedule": 600.0,
        "args": ("https://www.aljazeera.com/xml/rss/all.xml", "35e4feb7-4bef-412d-8854-280b7d8ca002"),
    }
    ,"crawl-newsapi-ai-hourly": {
        "task": "app.tasks.apis.crawl_newsapi",
        "schedule": 1800.0, # Run once an hour
        "args": ("api-uuid-1111",),
    },
    "crawl-newsdata-tech-hourly": {
        "task": "app.tasks.apis.crawl_newsdata",
        "schedule": 1800.0, # Run once an hour
        "args": ("api-uuid-2222",),
    },
    },
)
