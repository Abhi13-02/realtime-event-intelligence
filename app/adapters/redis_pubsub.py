"""Redis Pub/Sub backplane for real-time alert delivery.

WHY THIS EXISTS
---------------
In v1 the Kafka alert consumers ran as asyncio tasks inside the FastAPI
process, so they could call ConnectionManager.push() directly — the socket and
the consumer were in the same memory. That is why delivery was a function call
and needed no IPC at all.

It also meant the backend could never run more than one replica. A second
replica would consume from the same Kafka group, so an alert for a user
connected to replica A could just as easily be handed to replica B, which does
not hold that socket. The alert would silently go nowhere.

The consumer now runs in its own container and publishes here instead. Every
gateway replica subscribes, and the one holding that user's socket delivers it.
The rest drop the message.

DELIVERY GUARANTEE
------------------
Redis Pub/Sub is fire-and-forget: there is no persistence, no replay and no
acknowledgement. If a gateway is mid-restart when a message is published, that
message is gone from the WebSocket path.

That is acceptable here because the WebSocket is not the source of truth. The
alert row is already committed to Postgres with status='pending' before
anything is published, and the frontend reconciles by calling GET /v1/alerts
on reconnect. The socket is a latency optimisation over the database, not the
record of what happened.

If that stops being true — if an alert ever exists only as a published
message — this needs to become a Redis Stream with consumer groups, which does
persist and replay. It is deliberately not that today, because durability is
already handled one layer down.

FAN-OUT
-------
One channel, and every gateway receives every alert and discards the ones it
has no socket for. At the target of 10k users across ~5 replicas that is a 5x
message amplification on a few hundred messages a second, which Redis does not
notice. Per-user channels would avoid the waste but add a SUBSCRIBE and
UNSUBSCRIBE on every socket open and close. Not worth it at this size.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from app.adapters.redis_client import get_redis_ws
from app.core.logging import get_trace_id

logger = logging.getLogger(__name__)

# One channel for both alert streams. The payload carries its own "event" so a
# gateway does not need a channel per message type.
ALERT_CHANNEL = "alerts:broadcast"

async def publish_alert(payload: dict) -> None:
    """
    Broadcast one delivery instruction to every gateway replica.

    Failure here is logged and swallowed. The alert row is already committed,
    so a Redis blip costs the user a live toast, not the alert itself — and
    raising would stop the queue message being acked and redeliver a message
    whose database work is already done.
    """
    payload = {**payload, "trace_id": get_trace_id()}
    try:
        await get_redis_ws().publish(ALERT_CHANNEL, json.dumps(payload))
    except Exception as exc:
        logger.error(
            "Failed to publish alert to Redis (user=%s, alert=%s): %s",
            payload.get("user_id"), payload.get("alert_id"), exc,
        )


async def subscribe_alerts() -> AsyncIterator[dict]:
    """
    Yield every alert published to the backplane, forever.

    Used by the FastAPI gateway. Reconnection is the caller's job — see
    app/alert/websocket.py, which wraps this in a retry loop so a Redis restart
    does not permanently deafen the replica.
    """
    pubsub = get_redis_ws().pubsub()
    await pubsub.subscribe(ALERT_CHANNEL)
    logger.info("Subscribed to Redis channel %s", ALERT_CHANNEL)

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                # Subscribe confirmations and pings.
                continue
            try:
                yield json.loads(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                # A malformed payload must not kill the subscription for
                # everyone else on this replica.
                logger.error("Malformed alert payload on backplane: %s", exc)
    finally:
        await pubsub.unsubscribe(ALERT_CHANNEL)
        await pubsub.aclose()
        logger.info("Unsubscribed from Redis channel %s", ALERT_CHANNEL)
