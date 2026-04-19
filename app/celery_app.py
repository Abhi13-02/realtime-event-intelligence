from celery import Celery
from datetime import timedelta
from app.config import get_settings

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

    beat_schedule={
        # ── BBC News (5 feeds, shared source_id -0001) ──────────────────────
        "crawl-bbc-top": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.bbc_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },
        "crawl-bbc-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.bbc_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/world/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },
        "crawl-bbc-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.bbc_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/business/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },
        "crawl-bbc-technology": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.bbc_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/technology/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },
        "crawl-bbc-science": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.bbc_poll_interval_minutes),
            "args": ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "a1b2c3d4-0001-0001-0001-000000000001"),
        },

        # ── New York Times (5 feeds, shared source_id -0002) ────────────────
        "crawl-nyt-home": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.nyt_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },
        "crawl-nyt-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.nyt_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },
        "crawl-nyt-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.nyt_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },
        "crawl-nyt-technology": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.nyt_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },
        "crawl-nyt-science": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.nyt_poll_interval_minutes),
            "args": ("https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "a1b2c3d4-0002-0002-0002-000000000002"),
        },

        # ── The Guardian (6 feeds, shared source_id -0008) ──────────────────
        "crawl-guardian-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/world/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },
        "crawl-guardian-technology": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/technology/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },
        "crawl-guardian-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/business/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },
        "crawl-guardian-science": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/science/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },
        "crawl-guardian-environment": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/environment/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },
        "crawl-guardian-sport": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.guardian_poll_interval_minutes),
            "args": ("https://www.theguardian.com/sport/rss", "a1b2c3d4-0008-0008-0008-000000000008"),
        },

        # ── NDTV (15 feeds, shared source_id -0010) ─────────────────────────
        "crawl-ndtv-top-stories": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-top-stories", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-latest": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-trending": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-trending-news", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-india": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-india-news", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-world-news", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvprofit-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-sports": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvsports-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-cricket": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvsports-cricket", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-tech": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/gadgets360-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-movies": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvmovies-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-south": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-south", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-indians-abroad": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-indians-abroad", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-health": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvcooks-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-people": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvnews-people", "a1b2c3d4-0010-0010-0010-000000000010"),
        },
        "crawl-ndtv-hindi": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.ndtv_poll_interval_minutes),
            "args": ("https://feeds.feedburner.com/ndtvkhabar-latest", "a1b2c3d4-0010-0010-0010-000000000010"),
        },

        # ── India TV (13 feeds, shared source_id -0011) ──────────────────────
        "crawl-indiatv-top": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-india": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-india.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-world.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-business.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-sports": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-sports.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-entertainment": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-entertainment.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-lifestyle": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-lifestyle.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-politics": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-politics.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-health": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-health.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-auto": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-auto.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-astrology": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-astrology.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-education": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-education.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },
        "crawl-indiatv-trending": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.indiatv_poll_interval_minutes),
            "args": ("https://www.indiatvnews.com/rssnews/topstory-trending.xml", "a1b2c3d4-0011-0011-0011-000000000011"),
        },

        # ── The Hindu (35 feeds, shared source_id -0009) ─────────────────────
        "crawl-hindu-home": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-india": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/news/national/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-world": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/news/international/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-opinion": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/opinion/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-sports": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sport/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-business": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/business/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-entertainment": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/entertainment/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-lifestyle": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-society": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/society/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-scitech": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-movies": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/entertainment/movies/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-technology": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/technology/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-food": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/food/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-books": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/books/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-data": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/data/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-children": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/children/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-cities": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/news/cities/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-health": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/health/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-education": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/education/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-agriculture": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/agriculture/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-industry": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/business/Industry/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-markets": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/business/markets/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-economy": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/business/Economy/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-realestate": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/real-estate/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-science": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/science/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-gadgets": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/technology/gadgets/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-fashion": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/fashion/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-fitness": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/fitness/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-environment": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sci-tech/energy-and-environment/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-music": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/entertainment/music/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-art": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/entertainment/art/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-travel": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/travel/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-luxury": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/life-and-style/luxury/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-cricket": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sport/cricket/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-football": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sport/football/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },
        "crawl-hindu-hockey": {
            "task": "app.tasks.rss.crawl_rss_feed",
            "schedule": timedelta(minutes=settings.hindu_poll_interval_minutes),
            "args": ("https://www.thehindu.com/sport/hockey/feeder/default.rss", "a1b2c3d4-0009-0009-0009-000000000009"),
        },

        # ── Social / APIs ────────────────────────────────────────────────────
        "crawl-reddit": {
            "task": "app.tasks.reddit.crawl_reddit",
            "schedule": timedelta(minutes=settings.reddit_poll_interval_minutes),
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

        # ── Intelligence ─────────────────────────────────────────────────────
        "run-subtheme-discovery": {
            "task": "app.tasks.subtheme_discovery.run_subtheme_discovery",
            "schedule": timedelta(hours=settings.subtheme_discovery_interval_hours),
        },

        # ── Alerts ───────────────────────────────────────────────────────────
        "send-email-digest-midnight": {
            "task": "app.tasks.email.send_email_digest",
            "schedule": timedelta(hours=24),
        },
    },
)
