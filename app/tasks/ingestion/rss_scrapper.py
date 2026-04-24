import logging
import re
import feedparser
from dateutil import parser as date_parser
from app.celery_app import celery_app
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

RETRY_BACKOFFS = [0, 30, 60, 120]

# Last-resort <img src="..."> extractor from HTML description/summary bodies.
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)', re.I)

# Regex to detect Hindi (Devanagari) characters.
# Range \u0900-\u097f covers the main Devanagari block.
_HINDI_CHAR_RE = re.compile(r'[\u0900-\u097f]')


def _extract_image(entry) -> str | None:
    """
    Fallback chain across common RSS image conventions:
      1. MediaRSS <media:content url="..."> (NDTV, NYT, Guardian)
      2. MediaRSS <media:thumbnail url="..."> (IndiaTV, BBC)
      3. <enclosure type="image/*" url="..."> (podcasts, some feeds)
      4. Inline <img src="..."> inside description/summary HTML (The Hindu)
    Returns None if the feed publishes no image for this entry.
    """
    for m in entry.get("media_content") or []:
        url = m.get("url")
        if url:
            return url
    for m in entry.get("media_thumbnail") or []:
        url = m.get("url")
        if url:
            return url
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image/") and enc.get("href"):
            return enc["href"]
    body = entry.get("summary") or entry.get("description") or ""
    match = _IMG_SRC_RE.search(body)
    if match:
        return match.group(1)
    return None


@celery_app.task(bind=True, max_retries=3, name="app.tasks.rss.crawl_rss_feed")
def crawl_rss_feed(self, feed_url: str, source_id: str, max_articles: int | None = None) -> None:
    """
    Celery task: fetch a generic RSS feed, standardise the data, and publish
    each article to the raw-articles Kafka topic.

    Entries with no description/summary are skipped — downstream pipeline
    relies on content for embedding + topic matching, so title-only items
    produce low-quality matches.
    """
    try:
        logger.info(f"Starting fetch for RSS feed: {feed_url}")

        feed = feedparser.parse(feed_url)

        if not feed.entries:
            logger.warning(f"No entries found for {feed_url}. Feed might be down.")
            return

        entries = feed.entries
        if max_articles:
            entries = entries[:max_articles]

        published = 0
        skipped_no_url = 0
        skipped_no_desc = 0

        for entry in entries:
            url = entry.get("link")
            if not url:
                skipped_no_url += 1
                continue

            raw_content = entry.get("summary") or entry.get("description") or ""
            if not raw_content.strip():
                skipped_no_desc += 1
                continue

            # Language Filter: Skip if Hindi characters are detected in title or content
            headline = entry.get("title", "")
            if _HINDI_CHAR_RE.search(headline) or _HINDI_CHAR_RE.search(raw_content):
                logger.info(f"Skipping Hindi article: {headline[:50]}...")
                continue

            raw_date = entry.get("published")
            iso_date = None
            if raw_date:
                try:
                    iso_date = date_parser.parse(raw_date).isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse date '{raw_date}' for URL {url}: {e}")

            article = {
                "url": url,
                "headline": entry.get("title", ""),
                "content": raw_content,
                "source_id": source_id,
                "published_at": iso_date,
                "image_url": _extract_image(entry),
            }

            publish_article(article)
            published += 1

        logger.info(
            "crawl_rss_feed complete for %s — published: %d, skipped_no_url: %d, skipped_no_desc: %d",
            feed_url,
            published,
            skipped_no_url,
            skipped_no_desc,
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
