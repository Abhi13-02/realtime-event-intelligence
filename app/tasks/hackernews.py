import logging
import requests
from app.celery_app import celery_app
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

HN_SOURCE_ID = "a1b2c3d4-0005-0005-0005-000000000005"
HN_ALGOLIA_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story&hitsPerPage=50"
)

# Retry countdown in seconds indexed by retry attempt number.
# self.request.retries is 0 on the first retry, 1 on the second, etc.
# Per celery-lld.md: max 3 retries, backoffs at 0s → 30s → 60s → 120s.
RETRY_BACKOFFS = [0, 30, 60, 120]


@celery_app.task(bind=True, max_retries=3, name="app.tasks.hackernews.crawl_hackernews")
def crawl_hackernews(self) -> None:
    """
    Celery task: fetch the latest HN stories and publish each one
    to the raw-articles Kafka topic.

    Runs every 10 minutes via Celery Beat (configured in celery_app.py).
    bind=True gives us access to `self` so we can call self.retry()
    and inspect self.request.retries for the backoff countdown.
    """
    try:
        response = requests.get(HN_ALGOLIA_URL, timeout=10)
        response.raise_for_status()
        hits = response.json().get("hits", [])

        published = 0
        skipped = 0

        for hit in hits:
            url = hit.get("url")

            # Skip discussion posts (Ask HN, Show HN) — they have no
            # external article URL. The pipeline expects a real article URL.
            if not url:
                skipped += 1
                continue

            article = {
                "url": url,
                "headline": hit.get("title") or "",
                # story_text is present on text posts; null on link posts.
                # Pass whatever exists — the pipeline preprocesses it.
                "content": hit.get("story_text") or "",
                "source_id": HN_SOURCE_ID,
                # created_at from Algolia is ISO 8601 — pipeline accepts that.
                "published_at": hit.get("created_at"),
            }

            publish_article(article)
            published += 1

        logger.info(
            "crawl_hackernews complete — published: %d, skipped: %d",
            published,
            skipped,
        )

    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.warning(
            "crawl_hackernews failed (attempt %d/%d): %s — retrying in %ds",
            self.request.retries + 1,
            self.max_retries,
            exc,
            countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)
