"""
Alert Consumer — claims matched-articles from the queue and routes each match
to the user's configured delivery channels.

Runs in the standalone alert-consumer container (app/alert/runner.py). It used
to be an asyncio task inside FastAPI, calling ConnectionManager.push() directly
because the socket lived in the same process. That is what capped the backend
at one replica — see app/adapters/redis_pubsub.py.

Delivery per channel:
  websocket → publish_alert()               (Redis backplane; a gateway delivers it)
  sms       → dispatch_sms_task.delay()     (enqueued to Celery worker, async)
  email     → pass (intentionally)          (alert row stays 'pending'; Celery Beat sweeps at midnight)

This process no longer marks an alert 'sent'. It cannot know whether delivery
happened — only the gateway holding the socket does, so the gateway writes that
back. An alert nobody was connected for stays 'pending' and is picked up by
GET /v1/alerts on reconnect, exactly as before.

Ack strategy (same principle as the pipeline consumer):
  - Channel lookup or article fetch fails → retry()  → returns to 'pending', claimed again
  - Bulk INSERT fails                     → retry()  → returns to 'pending', claimed again
  - Routing failure (WS disconnect, etc.) → ack()    → alert row exists, REST API is fallback
  - Malformed message                     → fail()   → parked; retrying cannot fix a missing field

The first two used to mean "do not commit the Kafka offset", which deferred the
retry until the container restarted and blocked the partition until then. They
now retry on the next claim, and a message that can never succeed is parked in
'failed' after max_attempts instead of blocking anything.
"""
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.queue.names import MATCHED_ARTICLES
from app.adapters.queue.pg_queue import AsyncPgQueue, QueueMessage
from app.adapters.redis_pubsub import publish_alert
from app.alert import db as alert_db
from app.core.logging import set_trace_id
from app.db.session import AsyncSessionLocal
from app.tasks.notifications.sms import dispatch_sms_task

logger = logging.getLogger(__name__)

# See app/pipeline/consumer.py for why 2 seconds. Same reasoning, same budget.
POLL_INTERVAL_SECONDS = 2
CLAIM_BATCH_SIZE = 10
REAP_INTERVAL_SECONDS = 60


async def run_alert_consumer() -> None:
    """
    Main consumer loop. Runs forever as an asyncio task.
    Started by app/alert/runner.py; cancelled cleanly on shutdown.
    """
    queue = AsyncPgQueue(AsyncSessionLocal)

    logger.info(
        "Alert consumer started — claiming from '%s' (backlog: %d).",
        MATCHED_ARTICLES, await queue.depth(MATCHED_ARTICLES),
    )

    last_reap = 0.0
    loop = asyncio.get_running_loop()

    try:
        while True:
            if loop.time() - last_reap >= REAP_INTERVAL_SECONDS:
                await queue.reap_stalled(MATCHED_ARTICLES)
                last_reap = loop.time()

            messages = await queue.claim(MATCHED_ARTICLES, limit=CLAIM_BATCH_SIZE)

            if not messages:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            for message in messages:
                await _process_message(queue, message)
    finally:
        logger.info("Alert consumer stopped.")


async def _process_message(queue: AsyncPgQueue, message: QueueMessage) -> None:
    data = message.payload

    # Bind the trace id the pipeline stamped on this event, so this container's
    # logs line up with the pipeline's for the same article.
    set_trace_id(data.get("trace_id"))

    # ── Validate message shape ────────────────────────────────────────────
    try:
        article_id      = data["article_id"]
        topic_id        = data["topic_id"]
        relevance_score = data["relevance_score"]
        user_id         = data["user_id"]
    except KeyError as exc:
        # Malformed message — park it. A missing field will still be missing on
        # the next attempt, so retrying only wastes claims.
        logger.error("Malformed matched-articles message, parking as failed: missing field %s", exc)
        await queue.fail(message.id, f"malformed payload: missing {exc}")
        return

    async with AsyncSessionLocal() as session:
        try:
            # ── Step 1: Channel lookup ────────────────────────────────────
            # If the topic was deactivated since the pipeline matched it,
            # channels is empty and we skip without writing anything.
            channels = await alert_db.get_channels(session, user_id, topic_id)
            if not channels:
                logger.debug("No active channels for user %s topic %s — skipping", user_id, topic_id)
                await queue.ack(message.id)
                return

            # ── Step 2: Fetch article and topic content ───────────────────
            article = await alert_db.get_article(session, article_id)
            if not article:
                logger.error("Article %s not found in DB — skipping alert", article_id)
                await queue.ack(message.id)
                return

            topic_name = await alert_db.get_topic_name(session, topic_id) or "Unknown Topic"

            # ── Step 3: Bulk INSERT one row per channel ───────────────────
            # If this INSERT fails (DB down, etc.) we do NOT ack — the message
            # returns to 'pending' and is claimed again.
            inserted = await alert_db.bulk_insert_alerts(
                session, user_id, article_id, topic_id, relevance_score, channels
            )
            # inserted = [(alert_id, channel), ...]

            # ── Step 4: Route each channel independently ──────────────────
            for alert_id, channel, created_at in inserted:
                try:
                    if channel == "websocket":
                        await _publish_websocket(
                            alert_id, user_id, topic_id, topic_name, relevance_score, article,
                            created_at
                        )
                    elif channel == "sms":
                        await _handle_sms(alert_id, user_id, session)
                    # email: intentionally left as pending — Celery Beat handles at midnight UTC

                except Exception as exc:
                    # A channel failure must not affect other channels for the same user
                    logger.error("Channel %s failed for alert %s: %s", channel, alert_id, exc)

            # ── Step 5: Ack ───────────────────────────────────────────────
            # Ack AFTER all channels are routed (not after delivery is confirmed).
            # "Routed" = WS push attempted, SMS task enqueued, email intentionally left.
            await queue.ack(message.id)

        except Exception as exc:
            # Bulk INSERT or article fetch failed — do NOT ack. The message goes
            # back to 'pending' and the next claim retries it.
            logger.error("Alert processing failed, message returned to queue: %s", exc)
            await queue.retry(message.id, str(exc))


async def _publish_websocket(
    alert_id: str,
    user_id: str,
    topic_id: str,
    topic_name: str,
    relevance_score: float,
    article,
    created_at,
) -> None:
    """
    Broadcast the alert to every gateway replica over the Redis backplane.

    We do not know, and cannot know from here, whether the user is connected —
    that state lives in whichever gateway holds the socket. So this always
    publishes; the gateway with the socket delivers and marks the row 'sent',
    and every other replica drops it. If nobody has the socket, the row stays
    'pending' and the frontend collects it from GET /v1/alerts on reconnect.
    """
    await publish_alert({
        "user_id": user_id,
        "alert_id": alert_id,
        "kind": "article",
        "event": "new_alert",
        "data": {
            "id": alert_id,
            "topic_id": topic_id,
            "topic_name": topic_name,
            "headline": article.headline,
            "summary": article.summary,
            "url": article.url,
            "image_url": article.image_url,
            "source_name": article.source_name,
            "relevance_score": relevance_score,
            "created_at": created_at.isoformat() if created_at else None,
        },
    })


async def _handle_sms(alert_id: str, user_id: str, session: AsyncSession) -> None:
    """
    Enqueue the SMS Celery task.
    If the handoff itself fails (Redis/Celery unavailable), mark the alert row failed.
    """
    try:
        dispatch_sms_task.delay(alert_id=alert_id, user_id=user_id)
    except Exception:
        await alert_db.mark_alert_failed(session, alert_id)
        raise
