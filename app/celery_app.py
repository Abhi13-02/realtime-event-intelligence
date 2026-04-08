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
        "app.tasks.ingestion.reddit",
        "app.tasks.ingestion.rss_scrapper",
        "app.tasks.ingestion.api_scrapers",
        "app.tasks.ingestion.hackernews",
        "app.tasks.notifications.sms",
        "app.tasks.notifications.email",
        "app.tasks.notifications.intelligence_sms",
        "app.tasks.discovery.subtheme_discovery",
    ],

    # Serialise task messages as JSON (human-readable, language-agnostic)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Use UTC everywhere — avoids timezone bugs in scheduled tasks
    timezone="UTC",
    enable_utc=True,

    beat_schedule={
        # ── Ingestion ──────────────────────────────────────────────────────
        "crawl-reddit": {
            "task": "app.tasks.reddit.crawl_reddit",
            "schedule": timedelta(minutes=settings.reddit_poll_interval_minutes),
        },
        # HackerNews disabled — link aggregator, articles have title only (no description).
        # Re-enable once full-article URL scraping is added.
        # "crawl-hackernews": {
        #     "task": "app.tasks.hackernews.crawl_hackernews",
        #     "schedule": timedelta(minutes=settings.hn_poll_interval_minutes),
        # },
        "crawl-bbc": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.rss_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },
        "crawl-nyt": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.rss_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },
        "crawl-aljazeera": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.rss_poll_interval_minutes),
            "args": ("https://www.aljazeera.com/xml/rss/all.xml", "a1b2c3d4-0003-0003-0003-000000000003"),
        },
        "crawl-newsapi": {
            "task": "app.tasks.apis.crawl_newsapi",
            "schedule": timedelta(minutes=settings.newsapi_poll_interval_minutes),
            "args": ("a1b2c3d4-0004-0004-0004-000000000004",),
        },
        "crawl-newsdata": {
            "task": "app.tasks.apis.crawl_newsdata",
            "schedule": timedelta(minutes=settings.newsdata_poll_interval_minutes),
            "args": ("a1b2c3d4-0007-0007-0007-000000000007",),
        },
        # ── Intelligence ───────────────────────────────────────────────────
        "run-subtheme-discovery": {
            # Reads from PostgreSQL, clusters GDELT articles, runs VADER sentiment,
            # calls Cohere for labeling, detects evolution, persists and publishes
            # to sub-theme-events Kafka topic.
            "task": "app.tasks.subtheme_discovery.run_subtheme_discovery",
            "schedule": timedelta(hours=settings.subtheme_discovery_interval_hours),
        },
        # ── Alerts ─────────────────────────────────────────────────────────
        "send-email-digest-midnight": {
            # Sweeps all pending email alerts (article + intelligence) and sends one digest per user.
            "task": "app.tasks.email.send_email_digest",
            "schedule": timedelta(hours=24),  # use crontab(hour=0, minute=0) in prod
        },
    },
)
