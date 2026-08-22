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
import logging
import time

from app.adapters.kafka.consumers import build_sync_consumer
from app.core.logging import set_trace_id, setup_logging

from app.core.constants import get_sync_db_url
from app.pipeline.orchestrator import ArticlePipeline
from app.pipeline.models import RawArticle
from app.pipeline.exceptions import PipelineError, DuplicateArticleError, NoTopicMatchError
from app.pipeline.db_adapter import PostgresAdapter
from app.adapters.ai.client import get_embedding_client
from app.adapters.ai.groq_summarizer import GroqAdapter
from app.adapters.kafka.event_bus import KafkaAdapter

logger = logging.getLogger(__name__)

# How often to reload topics from the DB into the pipeline's in-memory cache.
# 300s = 5 minutes. New topics added by users won't be matched until the next refresh.
TOPIC_CACHE_REFRESH_INTERVAL = 300



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
    """Load active topics and system settings from DB into the pipeline cache. Returns current time."""
    # 1. Refresh topics
    topics = db.get_active_topics()
    pipeline.refresh_topic_cache(topics)
    logger.info("Topic cache refreshed — %d active topics loaded", len(topics))

    # 2. Refresh system thresholds
    settings = db.get_system_settings()
    thresholds = {
        "broad":    settings.get("threshold_broad", 0.3),
        "balanced": settings.get("threshold_balanced", 0.35),
        "high":     settings.get("threshold_high", 0.4),
    }
    pipeline.thresholds = thresholds
    logger.info("Pipeline thresholds refreshed: %s", thresholds)

    return time.time()


def run() -> None:
    """
    Main consumer loop. Runs forever until the process is killed.
    Called directly by the pipeline-consumer Docker container.
    """
    # ── Initialise adapters ───────────────────────────────────────────────
    # Each adapter is created once — they are expensive to initialise.
    # The embedder is an HTTP client now — the model itself lives in the
    # embedding-service container, so nothing here loads PyTorch.

    logger.info("Initialising pipeline adapters...")

    db = PostgresAdapter(get_sync_db_url())

    embedder = get_embedding_client()

    # GroqAdapter reads GROQ_API_KEY from os.environ directly.
    llm = GroqAdapter()

    # No bootstrap_servers argument: that would open a second producer
    # connection alongside the shared one. KafkaAdapter() reuses it.
    bus = KafkaAdapter()

    # ── Initialise pipeline ───────────────────────────────────────────────
    # Fetch initial thresholds from DB
    sys_settings = db.get_system_settings()
    thresholds = {
        "broad":    sys_settings.get("threshold_broad", 0.3),
        "balanced": sys_settings.get("threshold_balanced", 0.35),
        "high":     sys_settings.get("threshold_high", 0.4),
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
    consumer = build_sync_consumer("raw-articles", group_id="pipeline-consumer-group")

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


def _process_message(pipeline: ArticlePipeline, consumer, message) -> None:
    """
    Process a single Kafka message through the pipeline.
    Commits offset on success. Does NOT commit on failure — message will
    be redelivered on the next consumer restart.
    """
    try:
        data = message.value

        # Bind before anything else runs: every log line emitted while handling
        # this article — including from deep inside the stages — is stamped with
        # it automatically. See app/core/logging.py.
        set_trace_id(data.get("trace_id"))

        raw_article = RawArticle(
            url=data["url"],
            headline=data["headline"],
            content=data["content"],
            source_id=data["source_id"],
            published_at=data.get("published_at"),
            image_url=data.get("image_url"),
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
    setup_logging()
    run()
