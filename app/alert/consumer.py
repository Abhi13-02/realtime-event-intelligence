"""
Alert Consumer — reads matched-articles from Kafka and routes each match
to the user's configured delivery channels.

Runs as an asyncio background task inside FastAPI (started via lifespan in main.py).
Co-located with FastAPI so it can call ConnectionManager.push() directly — no
inter-process communication needed in v1.

Delivery per channel:
  websocket → ConnectionManager.push()      (instant, in-process, async)
  sms       → dispatch_sms_task.delay()     (enqueued to Celery worker, async)
  email     → pass (intentionally)          (alert row stays 'pending'; Celery Beat sweeps at midnight)

Offset commit strategy (same principle as pipeline consumer):
  - Channel lookup or article fetch fails → do NOT commit → Kafka replays on restart
  - Bulk INSERT fails                     → do NOT commit → Kafka replays on restart
  - Routing failure (WS disconnect, etc.) → still commit → alert row exists, REST API is fallback
  - Malformed message                     → commit + skip → a broken message must not block the partition
"""
import json
import logging

from aiokafka import AIOKafkaConsumer
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.alert import db as alert_db
from app.alert.websocket import ConnectionManager
from app.tasks.notifications.sms import dispatch_sms_task

logger = logging.getLogger(__name__)


async def run_alert_consumer(connection_manager: ConnectionManager) -> None:
    """
    Main consumer loop. Runs forever as an asyncio task.
    Started by FastAPI lifespan on startup; cancelled cleanly on shutdown.
    """
    settings = get_settings()

    consumer = AIOKafkaConsumer(
        "matched-articles",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="alert-consumer-group",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    await consumer.start()
    logger.info("Alert consumer started — polling matched-articles...")

    try:
        async for message in consumer:
            await _process_message(consumer, message, connection_manager)
    finally:
        await consumer.stop()
        logger.info("Alert consumer stopped.")


async def _process_message(consumer, message, connection_manager: ConnectionManager) -> None:
    data = message.value

    # ── Validate message shape ────────────────────────────────────────────
    try:
        article_id      = data["article_id"]
        topic_id        = data["topic_id"]
        relevance_score = data["relevance_score"]
        user_id         = data["user_id"]
    except KeyError as exc:
        # Malformed message — commit and skip. Must not block the partition.
        logger.error("Malformed matched-articles message, skipping: missing field %s", exc)
        await consumer.commit()
        return

    async with AsyncSessionLocal() as session:
        try:
            # ── Step 1: Channel lookup ────────────────────────────────────
            # If the topic was deactivated since the pipeline matched it,
            # channels is empty and we skip without writing anything.
            channels = await alert_db.get_channels(session, user_id, topic_id)
            if not channels:
                logger.debug("No active channels for user %s topic %s — skipping", user_id, topic_id)
                await consumer.commit()
                return

            # ── Step 2: Fetch article content ─────────────────────────────
            article = await alert_db.get_article(session, article_id)
            if not article:
                logger.error("Article %s not found in DB — skipping alert", article_id)
                await consumer.commit()
                return

            # ── Step 3: Bulk INSERT one row per channel ───────────────────
            # If this INSERT fails (DB down, etc.) we do NOT commit the offset —
            # Kafka will replay this message on next restart.
            inserted = await alert_db.bulk_insert_alerts(
                session, user_id, article_id, topic_id, relevance_score, channels
            )
            # inserted = [(alert_id, channel), ...]

            # ── Step 4: Route each channel independently ──────────────────
            for alert_id, channel in inserted:
                try:
                    if channel == "websocket":
                        await _handle_websocket(
                            session, connection_manager,
                            alert_id, user_id, topic_id, relevance_score, article,
                        )
                    elif channel == "sms":
                        await _handle_sms(alert_id, user_id, session)
                    # email: intentionally left as pending — Celery Beat handles at midnight UTC

                except Exception as exc:
                    # A channel failure must not affect other channels for the same user
                    logger.error("Channel %s failed for alert %s: %s", channel, alert_id, exc)

            # ── Step 5: Commit offset ─────────────────────────────────────
            # Commit AFTER all channels are routed (not after delivery is confirmed).
            # "Routed" = WS push attempted, SMS task enqueued, email intentionally left.
            await consumer.commit()

        except Exception as exc:
            # Bulk INSERT or article fetch failed — do NOT commit offset.
            # Kafka replays this message on next consumer restart.
            logger.error("Alert processing failed, offset NOT committed: %s", exc)


async def _handle_websocket(
    session: AsyncSession,
    connection_manager: ConnectionManager,
    alert_id: str,
    user_id: str,
    topic_id: str,
    relevance_score: float,
    article,
) -> None:
    """
    Push alert to the user's active WebSocket connection.
    If offline (no connection) or disconnected mid-push: leave alert as 'pending'.
    The frontend fetches all alerts (including pending) via GET /alerts on reconnect.
    """
    ws = connection_manager.get(user_id)
    if ws is None:
        # User is not connected right now — alert stays pending in DB
        return

    try:
        await connection_manager.push(user_id, {
            "event": "new_alert",
            "data": {
                "id": alert_id,
                "topic_id": topic_id,
                "headline": article.headline,
                "summary": article.summary,
                "url": article.url,
                "source_name": article.source_name,
                "relevance_score": relevance_score,
            },
        })
        await alert_db.mark_alert_sent(session, alert_id)

    except WebSocketDisconnect:
        # Connection existed but closed between get() and push() — leave as pending
        connection_manager.disconnect(user_id)


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
