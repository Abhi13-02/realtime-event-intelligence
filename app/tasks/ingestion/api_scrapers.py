import os
import logging
import requests
from dateutil import parser as date_parser
from app.celery_app import celery_app
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

# Load keys from the environment variables (set by .env)
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSDATA_KEY = os.getenv("NEWSDATA_KEY")

RETRY_BACKOFFS = [0, 30, 60, 120]

@celery_app.task(bind=True, max_retries=3, name="app.tasks.apis.crawl_newsapi")
def crawl_newsapi(self, source_id: str) -> None:
    """Fetches articles from NewsAPI.org and publishes to Kafka."""
    if not NEWSAPI_KEY:
        logger.error("NEWSAPI_KEY not found. Skipping task.")
        return

    try:
        # We request pageSize=50 to match your Hacker News limits
        url = f"https://newsapi.org/v2/top-headlines?country=us&language=en&pageSize=50&apiKey={NEWSAPI_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        articles = response.json().get("articles", [])
        published = 0
        skipped_no_desc = 0

        for item in articles:
            url_link = item.get("url")
            if not url_link:
                continue

            raw_content = (item.get("description") or "").strip()
            if not raw_content:
                skipped_no_desc += 1
                continue

            article = {
                "url": url_link,
                "headline": item.get("title", ""),
                "content": raw_content,
                "source_id": source_id,
                # NewsAPI already uses ISO 8601 format
                "published_at": item.get("publishedAt"),
                "image_url": item.get("urlToImage"),
            }

            publish_article(article)
            published += 1

        logger.info(
            f"NewsAPI complete — published: {published}, skipped_no_desc: {skipped_no_desc}"
        )
    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.warning(f"NewsAPI failed — retrying in {countdown}s: {exc}")
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(bind=True, max_retries=3, name="app.tasks.apis.crawl_newsdata")
def crawl_newsdata(self, source_id: str) -> None:
    """Fetches articles from Newsdata.io and publishes to Kafka."""
    if not NEWSDATA_KEY:
        logger.error("NEWSDATA_KEY not found. Skipping task.")
        return

    try:
        url = f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&language=en&category=top"
        response = requests.get(url, timeout=10)

        response.raise_for_status()
        
        results = response.json().get("results", [])
        published = 0
        skipped_no_desc = 0

        for item in results:
            url_link = item.get("link")
            if not url_link:
                continue

            raw_content = (item.get("description") or "").strip()
            if not raw_content:
                skipped_no_desc += 1
                continue

            # Convert '2026-04-04 06:56:27' to standard ISO 8601
            raw_date = item.get("pubDate")
            iso_date = None
            if raw_date:
                try:
                    iso_date = date_parser.parse(raw_date).isoformat()
                except Exception:
                    pass

            article = {
                "url": url_link,
                "headline": item.get("title", ""),
                "content": raw_content,
                "source_id": source_id,
                "published_at": iso_date,
                "image_url": item.get("image_url"),
            }

            publish_article(article)
            published += 1

        logger.info(
            f"Newsdata.io complete — published: {published}, skipped_no_desc: {skipped_no_desc}"
        )
    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.warning(f"Newsdata.io failed — retrying in {countdown}s: {exc}")
        raise self.retry(exc=exc, countdown=countdown)