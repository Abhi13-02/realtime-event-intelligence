"""
Pipeline Consumer — claims raw-articles from the queue, runs the NLP pipeline.

Lifecycle:
  1. On startup: initialise all pipeline adapters (DB, embedder, LLM, bus)
  2. Load active topics into the pipeline's in-memory cache
  3. Claim batches of pending messages in a loop
  4. For each message: payload -> RawArticle -> pipeline.process_article()
  5. Ack only on success — a failed message returns to 'pending' and is retried
  6. Refresh the topic cache every TOPIC_CACHE_REFRESH_INTERVAL seconds

This used to poll Kafka. The change is the transport only: claim() replaces
poll(), ack() replaces commit(). See app/adapters/queue/pg_queue.py for why
SELECT ... FOR UPDATE SKIP LOCKED gives the same competing-consumer guarantee
a Kafka consumer group did, and why this scales to more than one replica
without partitions to divide.
"""
import logging
import time

from app.adapters.ai.client import get_embedding_client
from app.adapters.ai.groq_summarizer import GroqAdapter
from app.adapters.queue.event_bus import PgEventBus
from app.adapters.queue.names import RAW_ARTICLES
from app.adapters.queue.pg_queue import PgQueue
from app.core.constants import get_sync_db_url
from app.core.logging import set_trace_id, setup_logging
from app.pipeline.db_adapter import PostgresAdapter
from app.pipeline.exceptions import PipelineError, DuplicateArticleError, NoTopicMatchError
from app.pipeline.models import RawArticle
from app.pipeline.orchestrator import ArticlePipeline

logger = logging.getLogger(__name__)

# How often to reload topics from the DB into the pipeline's in-memory cache.
# 300s = 5 minutes. New topics added by users won't be matched until the next refresh.
TOPIC_CACHE_REFRESH_INTERVAL = 300

# How long to sleep when the queue came back empty. Kafka pushed messages, so
# there was nothing to tune here; a claim has to be asked for.
#
# 2s costs one indexed query every two seconds per worker — roughly 0.5 queries
# per second against a database that handles thousands — and adds at most 2s to
# an end-to-end budget of 5 minutes. Lowering it buys latency nobody can
# measure; raising it saves cost nobody can measure.
POLL_INTERVAL_SECONDS = 2

# Messages per claim. Matches the old max_poll_records so the amount of work
# held by one worker at a time is unchanged.
CLAIM_BATCH_SIZE = 10

# How often to sweep for messages abandoned by a worker that died mid-article.
# Rare by definition, so this is cheap to run infrequently.
REAP_INTERVAL_SECONDS = 60


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

    # No arguments: that would open a second connection alongside the shared
    # publisher. PgEventBus() reuses it.
    bus = PgEventBus()

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

    # ── Initialise queue consumer ─────────────────────────────────────────
    # Its own connection, separate from PostgresAdapter's: the queue runs in
    # autocommit and the pipeline's adapter manages its own transactions.
    queue = PgQueue(get_sync_db_url())

    logger.info(
        "Pipeline consumer started — claiming from '%s' (backlog: %d).",
        RAW_ARTICLES, queue.depth(RAW_ARTICLES),
    )

    last_reap = 0.0

    # ── Main loop ─────────────────────────────────────────────────────────
    try:
        while True:

            # Refresh topic cache every 5 minutes.
            if time.time() - last_cache_refresh >= TOPIC_CACHE_REFRESH_INTERVAL:
                last_cache_refresh = _refresh_cache(pipeline, db)

            # Recover anything a previously crashed worker left claimed.
            if time.time() - last_reap >= REAP_INTERVAL_SECONDS:
                queue.reap_stalled(RAW_ARTICLES)
                last_reap = time.time()

            messages = queue.claim(RAW_ARTICLES, limit=CLAIM_BATCH_SIZE)

            if not messages:
                # Nothing pending. Sleep rather than spin — this is the one
                # cost a pull-based queue has that a pushed one does not.
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            for message in messages:
                _process_message(pipeline, queue, message)

    except KeyboardInterrupt:
        logger.info("Pipeline consumer shutting down...")
    finally:
        queue.close()
        db.close()
        logger.info("Pipeline consumer stopped.")


def _process_message(pipeline: ArticlePipeline, queue: PgQueue, message) -> None:
    """
    Process a single queue message through the pipeline.

    Acks on success. On an unexpected failure the message goes back to
    'pending' and is retried on a later claim — under Kafka an uncommitted
    offset sat until the container restarted and blocked its partition while it
    waited.
    """
    try:
        data = message.payload

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

        # Only ack AFTER successful processing.
        queue.ack(message.id)
        logger.debug("Processed and acked: %s", data.get("url"))

    except (DuplicateArticleError, NoTopicMatchError):
        # Expected early exits — article was intentionally dropped.
        # Ack so we don't reprocess it.
        queue.ack(message.id)

    except KeyError as exc:
        # The payload is missing a required field. Retrying cannot fix that, so
        # park it in 'failed' immediately rather than burning five attempts.
        logger.error("Malformed raw-articles payload, parking as failed: missing %s", exc)
        queue.fail(message.id, f"malformed payload: missing {exc}")

    except PipelineError as exc:
        # Summarisation failed permanently (LLM rate-limited, etc.)
        # Article is already stored in DB with summary=NULL.
        # Ack so the pipeline keeps moving — resume_article() will retry
        # summarisation on the next restart.
        logger.warning(
            "Pipeline Stage 6 failed — acking, article stored without summary: %s", exc
        )
        queue.ack(message.id)

    except Exception as exc:
        # Unexpected crash — could be transient (embedding service restarting,
        # database blip). Return it to 'pending' so the next claim retries it.
        # After max_attempts the queue parks it in 'failed' by itself.
        logger.error("Unexpected error processing message %s, will retry: %s", message.id, exc)
        queue.retry(message.id, str(exc))


if __name__ == "__main__":
    setup_logging()
    run()
