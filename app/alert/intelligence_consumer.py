"""
Intelligence Alert Consumer — reads sub-theme-events from Kafka and routes each
intelligence alert to the user's configured delivery channels.

Stream B — runs as an asyncio background task inside FastAPI (started via
lifespan in main.py), co-located with Stream A (alert/consumer.py).

Delivery per channel:
  websocket → ConnectionManager.push()        (instant, in-process, async)
  sms       → dispatch_intelligence_sms_task.delay()  (Celery, async)
  email     → pass (intentionally)            (row stays 'pending'; swept at midnight)

Offset commit strategy (same as Stream A):
  - Channel lookup / sub-theme fetch fails → do NOT commit → Kafka replays
  - Bulk INSERT fails                       → do NOT commit → Kafka replays
  - Routing failure (WS disconnect, etc.)   → still commit → row exists as fallback
  - Malformed message                       → commit + skip → must not block partition
"""
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.alert import db as alert_db                       # reuse get_channels
from app.alert import intelligence_db
from app.alert.websocket import ConnectionManager
from app.tasks.notifications.intelligence_sms import dispatch_intelligence_sms_task

logger = logging.getLogger(__name__)


async def run_intelligence_consumer(connection_manager: ConnectionManager) -> None:
    """
    Main consumer loop for sub-theme-events. Runs forever as an asyncio task.
    Started by FastAPI lifespan on startup; cancelled cleanly on shutdown.
    """
    settings = get_settings()

    consumer = AIOKafkaConsumer(
        "sub-theme-events",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="alert-subtheme-consumer-group",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

    await consumer.start()
    logger.info("Intelligence consumer started — polling sub-theme-events...")

    try:
        async for message in consumer:
            await _process_message(consumer, message, connection_manager)
    finally:
        await consumer.stop()
        logger.info("Intelligence consumer stopped.")


async def _process_message(
    consumer: AIOKafkaConsumer,
    message,
    connection_manager: ConnectionManager,
) -> None:
    data = message.value

    # ── Validate message shape ────────────────────────────────────────────
    try:
        event_type            = data["event_type"]
        sub_theme_id          = data["sub_theme_id"]
        sub_theme_snapshot_id = data["sub_theme_snapshot_id"]
        topic_id              = data["topic_id"]
        user_id               = data["user_id"]
    except KeyError as exc:
        logger.error("Malformed sub-theme-events message, skipping: missing field %s", exc)
        await consumer.commit()
        return

    async with AsyncSessionLocal() as session:
        try:
            # ── Step 1: Channel lookup ────────────────────────────────────
            channels = await alert_db.get_channels(session, user_id, topic_id)
            if not channels:
                logger.debug(
                    "No active channels for user %s topic %s — skipping intelligence alert",
                    user_id, topic_id,
                )
                await consumer.commit()
                return

            # ── Step 2: Fetch sub-theme state ─────────────────────────────
            sub_theme = await intelligence_db.get_sub_theme(session, sub_theme_id)
            if not sub_theme:
                logger.error("Sub-theme %s not found — skipping intelligence alert", sub_theme_id)
                await consumer.commit()
                return

            # ── Step 3: Fetch snapshot ────────────────────────────────────
            snapshot = await intelligence_db.get_snapshot(session, sub_theme_snapshot_id)
            if not snapshot:
                logger.error(
                    "Snapshot %s not found — skipping intelligence alert", sub_theme_snapshot_id
                )
                await consumer.commit()
                return

            # ── Step 4: Fetch topic name ──────────────────────────────────
            topic_name = await intelligence_db.get_topic_name(session, topic_id)

            # ── Step 5: Build payload JSONB ───────────────────────────────
            # Stored as a point-in-time snapshot so the alert renders
            # correctly even if the sub-theme continues to evolve.
            payload = {
                "event_type": event_type,
                "sub_theme_label": sub_theme.label,
                "sub_theme_description": sub_theme.description,
                "keywords": sub_theme.keywords,
                "article_count": snapshot.article_count,
                "reddit_post_count": snapshot.reddit_post_count,
                "total_volume": snapshot.total_volume,
                "sentiment_score": snapshot.sentiment_score,
                "sentiment_label": snapshot.sentiment_label,
                "status": sub_theme.status,
                "topic_id": topic_id,
                "topic_name": topic_name,
                "snapshot_at": snapshot.snapshot_at.isoformat(),
            }

            # ── Step 6: Bulk INSERT one row per channel ───────────────────
            # If this INSERT fails we do NOT commit — Kafka replays on restart.
            inserted = await intelligence_db.bulk_insert_intelligence_alerts(
                session=session,
                user_id=user_id,
                sub_theme_id=sub_theme_id,
                sub_theme_snapshot_id=sub_theme_snapshot_id,
                topic_id=topic_id,
                alert_type=event_type,
                payload=payload,
                channels=channels,
            )

            # ── Step 7: Route each channel independently ──────────────────
            created_at = datetime.now(timezone.utc).isoformat()

            for alert_id, channel in inserted:
                try:
                    if channel == "websocket":
                        await _handle_websocket(
                            session=session,
                            connection_manager=connection_manager,
                            alert_id=alert_id,
                            user_id=user_id,
                            event_type=event_type,
                            sub_theme=sub_theme,
                            snapshot=snapshot,
                            topic_id=topic_id,
                            topic_name=topic_name,
                            created_at=created_at,
                        )
                    elif channel == "sms":
                        await _handle_sms(alert_id, user_id, session)
                    # email: intentionally left as pending — swept at midnight

                except Exception as exc:
                    logger.error(
                        "Intelligence channel %s failed for alert %s: %s",
                        channel, alert_id, exc,
                    )

            # ── Step 8: Commit offset ─────────────────────────────────────
            await consumer.commit()

        except Exception as exc:
            # Bulk INSERT or critical fetch failed — do NOT commit offset.
            logger.error("Intelligence alert processing failed, offset NOT committed: %s", exc)


async def _handle_websocket(
    session: AsyncSession,
    connection_manager: ConnectionManager,
    alert_id: str,
    user_id: str,
    event_type: str,
    sub_theme,
    snapshot,
    topic_id: str,
    topic_name: str | None,
    created_at: str,
) -> None:
    """
    Push sub_theme_alert event to the user's active WebSocket connection.
    If offline or disconnected mid-push: leave alert as 'pending'.
    The frontend fetches all alerts (including pending) via GET /intelligence-alerts on reconnect.
    """
    ws = connection_manager.get(user_id)
    if ws is None:
        return  # User is offline — alert stays pending in DB

    try:
        await connection_manager.push(user_id, {
            "event": "sub_theme_alert",
            "data": {
                "id": alert_id,
                "event_type": event_type,
                "sub_theme_label": sub_theme.label,
                "sub_theme_description": sub_theme.description,
                "keywords": sub_theme.keywords,
                "total_volume": snapshot.total_volume,
                "sentiment_label": snapshot.sentiment_label,
                "topic_id": topic_id,
                "topic_name": topic_name,
                "created_at": created_at,
            },
        })
        await intelligence_db.mark_intelligence_alert_sent(session, alert_id)

    except WebSocketDisconnect:
        # Connection closed between get() and push() — leave as pending
        connection_manager.disconnect(user_id)


async def _handle_sms(
    alert_id: str,
    user_id: str,
    session: AsyncSession,
) -> None:
    """
    Enqueue the intelligence SMS Celery task.
    If the handoff itself fails (Redis/Celery unavailable), mark the alert failed.
    """
    try:
        dispatch_intelligence_sms_task.delay(alert_id=alert_id, user_id=user_id)
    except Exception:
        await intelligence_db.mark_intelligence_alert_failed(session, alert_id)
        raise
