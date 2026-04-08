"""
Seed script — publishes articles from a TSV file to Kafka (raw-articles topic).
Articles flow through the real pipeline: dedup → embed → topic match → summarise.

Run INSIDE the celery-worker container:
    python /app/tests/seed_mind.py

news.tsv columns (tab-separated):
    0: NewsID
    1: Category
    2: SubCategory
    3: Title
    4: Abstract
    5: URL
"""

import json
import time
import logging

from kafka import KafkaProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
MIND_TSV      = "/tmp/news.tsv"
KAFKA_SERVERS = "kafka:29092"
KAFKA_TOPIC   = "raw-articles"
SOURCE_ID     = "a1b2c3d4-0002-0002-0002-000000000002"  # NYT (valid FK in sources)


def _load_articles() -> list:
    """Read every row from the TSV and return a flat list of article dicts."""
    articles = []

    with open(MIND_TSV, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue

            title    = parts[3]
            abstract = parts[4] if len(parts) > 4 else ""
            url      = parts[5] if len(parts) > 5 else ""

            if not title or not url:
                continue

            articles.append({
                "url":          url,
                "headline":     title,
                "content":      abstract or title,
                "source_id":    SOURCE_ID,
                "published_at": None,
            })

    return articles


def main():
    logger.info("Loading articles from %s ...", MIND_TSV)
    articles = _load_articles()
    logger.info("Total to publish: %d", len(articles))

    if not articles:
        logger.error("No articles loaded — check MIND_TSV path.")
        return

    logger.info("Connecting to Kafka at %s ...", KAFKA_SERVERS)
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    for i, article in enumerate(articles, 1):
        producer.send(KAFKA_TOPIC, value=article)
        if i % 50 == 0:
            producer.flush()
            logger.info("  %d / %d published...", i, len(articles))
            time.sleep(0.5)

    producer.flush()
    producer.close()
    logger.info("Done — %d articles published to '%s'.", len(articles), KAFKA_TOPIC)
    logger.info("")
    logger.info("Watch pipeline-consumer logs:")
    logger.info("  docker compose logs -f pipeline-consumer")
    logger.info("")
    logger.info("Once processed, trigger discovery:")
    logger.info("  docker compose exec celery-worker celery -A app.celery_app call app.tasks.discovery.subtheme_discovery.run_subtheme_discovery")


if __name__ == "__main__":
    main()
