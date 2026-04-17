"""
Pipeline Consumer — reads raw-articles from Kafka, runs the NLP pipeline.

Lifecycle:
  1. On startup: initialise all pipeline adapters (DB, embedder, LLM, bus)
  2. Load active topics into the pipeline's in-memory cache
  3. Poll Kafka for messages in a loop
  4. For each message: deserialise → RawArticle → pipeline.process_article()
  5. Commit offset only on success — failed messages are reprocessed on restart
  6. Refresh the topic cache every TOPIC_CACHE_REFRESH_INTERVAL seconds
"""
import json
import logging
import time

from kafka import KafkaConsumer

from app.config import get_settings
from app.pipeline.orchestrator import ArticlePipeline
from app.pipeline.models import RawArticle
from app.pipeline.exceptions import PipelineError, DuplicateArticleError, NoTopicMatchError
from app.pipeline.adapters.db_adapter import PostgresAdapter
from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.pipeline.adapters.groq_adapter import GroqAdapter
from app.pipeline.adapters.bus_adapter import KafkaAdapter

logger = logging.getLogger(__name__)

# How often to reload topics from the DB into the pipeline's in-memory cache.
# 300s = 5 minutes. New topics added by users won't be matched until the next refresh.
TOPIC_CACHE_REFRESH_INTERVAL = 300


def _build_sync_db_url(database_url: str) -> str:
    """
    Convert the async DB URL to a sync one for psycopg2.
    postgresql+asyncpg://... → postgresql://...
    """
    return database_url.replace("postgresql+asyncpg", "postgresql")


def _resume_pending(pipeline: ArticlePipeline, db: PostgresAdapter) -> None:
    """
    On startup, find all articles stuck at pipeline_status='passed_dedup' with
    summary=NULL and resume them from Stage 6. These are articles that passed
    URL dedup, embedding, vector dedup, topic matching, and storage but whose
    summarisation failed before the last shutdown.
    """
    pending = db.get_pending_summary_articles()
    if not pending:
        logger.info("Resume check: no pending articles found.")
        return

    logger.info("Resume check: found %d article(s) pending summarisation.", len(pending))
    for item in pending:
        processed_article = item["processed_article"]
        scored_matches = item["scored_matches"]
        try:
            pipeline.resume_article(processed_article, scored_matches)
        except PipelineError as exc:
            # Still failing — leave it, will retry on next restart.
            logger.error("Resume failed for article %s: %s", processed_article.id, exc)


def _refresh_cache(pipeline: ArticlePipeline, db: PostgresAdapter) -> float:
    """Load active topics from DB into the pipeline cache. Returns current time."""
    topics = db.get_active_topics()
    pipeline.refresh_topic_cache(topics)
    logger.info("Topic cache refreshed — %d active topics loaded", len(topics))
    return time.time()


def run() -> None:
    """
    Main consumer loop. Runs forever until the process is killed.
    Called directly by the pipeline-consumer Docker container.
    """
    settings = get_settings()

    # ── Initialise adapters ───────────────────────────────────────────────
    # Each adapter is created once — they are expensive to initialise.
    # SentenceBertAdapter downloads and loads the BERT model (~500MB) on first run.

    logger.info("Initialising pipeline adapters...")

    db = PostgresAdapter(_build_sync_db_url(settings.database_url))

    embedder = SentenceBertAdapter()

    # GroqAdapter reads GROQ_API_KEY from os.environ directly.
    llm = GroqAdapter()

    bus = KafkaAdapter(bootstrap_servers=settings.kafka_bootstrap_servers)

    # ── Initialise pipeline ───────────────────────────────────────────────
    thresholds = {
        "broad":    settings.threshold_broad,
        "balanced": settings.threshold_balanced,
        "high":     settings.threshold_high,
    }
    pipeline = ArticlePipeline(db=db, embedder=embedder, llm=llm, bus=bus, thresholds=thresholds)

    # Load topics before we start consuming — pipeline can't match without them.
    last_cache_refresh = _refresh_cache(pipeline, db)

    # Resume any articles stuck at passed_dedup from a previous crashed run.
    _resume_pending(pipeline, db)

    # ── Initialise Kafka consumer ─────────────────────────────────────────
    # enable_auto_commit=False: we manually commit after successful processing.
    # If the process crashes mid-article, the offset is not committed and the
    # message will be redelivered on restart.
    consumer = KafkaConsumer(
        "raw-articles",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="pipeline-consumer-group",
        enable_auto_commit=False,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        auto_offset_reset="earliest",  # on first run, read from the beginning
        max_poll_records=10,
        session_timeout_ms=30000,
    )

    logger.info("Pipeline consumer started — polling raw-articles...")

    # ── Main loop ─────────────────────────────────────────────────────────
    try:
        while True:

            # Refresh topic cache every 5 minutes.
            if time.time() - last_cache_refresh >= TOPIC_CACHE_REFRESH_INTERVAL:
                last_cache_refresh = _refresh_cache(pipeline, db)

            # poll() fetches up to max_poll_records messages.
            # timeout_ms=1000: if no messages, return after 1 second so we
            # can check the cache refresh timer above.
            records = consumer.poll(timeout_ms=1000)

            for partition, messages in records.items():
                for message in messages:
                    _process_message(pipeline, consumer, message)

    except KeyboardInterrupt:
        logger.info("Pipeline consumer shutting down...")
    finally:
        consumer.close()
        db.close()
        logger.info("Pipeline consumer stopped.")


def _process_message(pipeline: ArticlePipeline, consumer: KafkaConsumer, message) -> None:
    """
    Process a single Kafka message through the pipeline.
    Commits offset on success. Does NOT commit on failure — message will
    be redelivered on the next consumer restart.
    """
    try:
        data = message.value

        raw_article = RawArticle(
            url=data["url"],
            headline=data["headline"],
            content=data["content"],
            source_id=data["source_id"],
            published_at=data.get("published_at"),
        )

        pipeline.process_article(raw_article)

        # Only commit AFTER successful processing.
        consumer.commit()
        logger.debug("Processed and committed: %s", data.get("url"))

    except (DuplicateArticleError, NoTopicMatchError):
        # Expected early exits — article was intentionally dropped.
        # Commit the offset so we don't reprocess it.
        consumer.commit()

    except PipelineError as exc:
        # Summarisation failed permanently (LLM rate-limited, etc.)
        # Article is already stored in DB with summary=NULL.
        # Commit the offset so the pipeline keeps moving — resume_article()
        # will retry summarisation on next restart.
        logger.warning("Pipeline Stage 6 failed — committing offset, article stored without summary: %s", exc)
        consumer.commit()

    except Exception as exc:
        # Malformed message or unexpected crash.
        # Commit so a broken message doesn't block the consumer forever.
        logger.error("Unexpected error processing message, skipping: %s", exc)
        consumer.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
