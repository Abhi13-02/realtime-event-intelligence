import logging
import feedparser
from dateutil import parser as date_parser
from app.celery_app import celery_app
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

# Retry countdown in seconds indexed by retry attempt number.
RETRY_BACKOFFS = [0, 30, 60, 120]

@celery_app.task(bind=True, max_retries=3, name="app.tasks.rss.crawl_rss_feed")
def crawl_rss_feed(self, feed_url: str, source_id: str) -> None:
    """
    Celery task: fetch a generic RSS feed, standardize the data, 
    and publish each article to the raw-articles Kafka topic.
    """
    try:
        logger.info(f"Starting fetch for RSS feed: {feed_url}")
        
        # feedparser handles the network request and XML parsing
        feed = feedparser.parse(feed_url)
        
        # Check if feed failed to load (feedparser sets bozo to 1 on bad XML, 
        # but we mainly care if entries exist)
        if not feed.entries:
            logger.warning(f"No entries found for {feed_url}. Feed might be down.")
            return

        published = 0
        skipped = 0

        for entry in feed.entries:
            url = entry.get("link")
            
            if not url:
                skipped += 1
                continue

            # FIX 1: The Content Fallback
            # Try summary, then description. If both are empty, fallback to the title.
            raw_content = entry.get("summary") or entry.get("description") or entry.get("title", "")
            
            # FIX 2: Standardizing the Date
            # Convert "Sat, 04 Apr 2026 16:19:25 GMT" into a clean ISO 8601 string
            raw_date = entry.get("published")
            iso_date = None
            if raw_date:
                try:
                    parsed_date = date_parser.parse(raw_date)
                    iso_date = parsed_date.isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse date '{raw_date}' for URL {url}: {e}")

            article = {
                "url": url,
                "headline": entry.get("title", ""),
                "content": raw_content,
                "source_id": source_id,
                "published_at": iso_date,
            }

            publish_article(article)
            published += 1

        logger.info(
            "crawl_rss_feed complete for %s — published: %d, skipped: %d",
            feed_url,
            published,
            skipped,
        )

    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.warning(
            "crawl_rss_feed failed (attempt %d/%d) for %s: %s — retrying in %ds",
            self.request.retries + 1,
            self.max_retries,
            feed_url,
            exc,
            countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)