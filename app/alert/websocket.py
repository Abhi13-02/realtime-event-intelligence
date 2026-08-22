"""
WebSocket connection manager, endpoints, and the Redis backplane subscriber.

Endpoints:
  POST /ws/ticket  — issues a one-time ticket stored in Redis (30s TTL).
                     Client calls this with a normal Bearer token, then
                     immediately opens the WebSocket using the returned ticket.
  WS   /ws         — authenticates via ticket query param, then holds the
                     connection open until the client disconnects.

Why tickets?
  WebSocket connections cannot carry HTTP headers. Tickets let the client
  authenticate over a normal HTTP request first, get a short-lived token,
  and then use it in the WS URL query string — which is safe because the
  ticket expires in 30 seconds and is single-use.

Why a subscriber?
  The Kafka alert consumers used to live in this process and could push
  straight into _connections. They now run in their own container and
  broadcast over Redis instead, so every gateway replica runs
  run_backplane_subscriber() and delivers only to sockets it actually holds.
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.adapters.redis_client import get_redis_ws
from app.adapters.redis_pubsub import subscribe_alerts
from app.alert import db as alert_db
from app.alert import intelligence_db
from app.core.dependencies import get_current_user
from app.core.logging import set_trace_id
from app.db.models import User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

class ConnectionManager:
    """
    In-memory store of the WebSocket connections held by THIS replica.

    One connection per user — if a user reconnects, the new connection replaces
    the old one. With multiple gateway replicas each holds a different subset;
    the Redis backplane is what lets an alert reach whichever one has the user.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    def connect(self, user_id: str, websocket: WebSocket) -> None:
        self._connections[user_id] = websocket

    def disconnect(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    def get(self, user_id: str) -> WebSocket | None:
        return self._connections.get(user_id)

    async def push(self, user_id: str, payload: dict) -> None:
        """Send a JSON message to the user's active WebSocket connection."""
        ws = self._connections.get(user_id)
        if ws:
            await ws.send_text(json.dumps(payload))


# Module-level singleton — shared by the WS endpoint and the backplane subscriber.
connection_manager = ConnectionManager()


# ── Redis backplane subscriber ───────────────────────────────────────────────

async def _deliver(message: dict) -> None:
    """
    Deliver one broadcast alert, if this replica holds that user's socket.

    Marking the row 'sent' happens here rather than in the consumer. The
    consumer publishes blind — it has no way to know whether anyone was
    connected — so this is the only place where "delivered" is actually known.
    """
    set_trace_id(message.get("trace_id"))

    user_id = message.get("user_id")
    if not user_id or connection_manager.get(user_id) is None:
        # Not our user. Every replica sees every message; most drop them.
        return

    try:
        await connection_manager.push(user_id, {
            "event": message["event"],
            "data": message["data"],
        })
    except WebSocketDisconnect:
        # Socket closed between the get() and the push() — leave the row
        # 'pending' so the client picks it up over REST on reconnect.
        connection_manager.disconnect(user_id)
        return
    except KeyError as exc:
        logger.error("Backplane message missing field %s — dropping", exc)
        return

    alert_id = message.get("alert_id")
    if not alert_id:
        return

    async with AsyncSessionLocal() as session:
        try:
            if message.get("kind") == "intelligence":
                await intelligence_db.mark_intelligence_alert_sent(session, alert_id)
            else:
                await alert_db.mark_alert_sent(session, alert_id)
        except Exception as exc:
            # The user has the alert on screen; failing to record that is worth
            # a log line, not a lost delivery.
            logger.error("Failed to mark alert %s sent: %s", alert_id, exc)


async def run_backplane_subscriber() -> None:
    """
    Consume the Redis alert channel forever, reconnecting on failure.

    Started by the FastAPI lifespan. The retry loop matters because Redis
    restarting would otherwise leave this replica permanently deaf while
    still accepting WebSocket connections — the worst possible failure mode,
    since it looks healthy and delivers nothing.
    """
    backoff = 1
    while True:
        try:
            async for message in subscribe_alerts():
                backoff = 1  # A delivered message proves the connection is good.
                await _deliver(message)
        except asyncio.CancelledError:
            logger.info("Backplane subscriber cancelled.")
            raise
        except Exception as exc:
            logger.error(
                "Backplane subscription dropped (%s) — reconnecting in %ds", exc, backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ── HTTP / WebSocket endpoints ───────────────────────────────────────────────

@router.post("/ws/ticket")
async def create_ws_ticket(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Issues a one-time WebSocket auth ticket.

    Flow:
      1. Client sends POST /ws/ticket with Authorization: Bearer <token>
      2. Server stores  ticket → user_id  in Redis with 30s TTL
      3. Server returns {"ticket": "<uuid>"}
      4. Client immediately opens WS /ws?ticket=<uuid>
    """
    ticket = str(uuid.uuid4())
    redis = get_redis_ws()
    await redis.setex(f"ws_ticket:{ticket}", 30, str(current_user.id))
    return {"ticket": ticket}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str) -> None:
    """
    WebSocket endpoint. Authenticated via one-time ticket from POST /ws/ticket.

    On connect: validates ticket in Redis, consumes it (single-use), registers connection.
    While open: listens for client messages (we only use this to detect disconnects).
    On disconnect: deregisters connection.
    """
    redis = get_redis_ws()
    key = f"ws_ticket:{ticket}"
    user_id = await redis.get(key)

    if not user_id:
        # Invalid or expired ticket — reject without accepting the connection
        await websocket.close(code=4001)
        return

    # Consume the ticket — it is single-use
    await redis.delete(key)

    await websocket.accept()
    connection_manager.connect(user_id, websocket)
    logger.info("WebSocket connected: user %s", user_id)

    try:
        # Block here to keep the connection alive.
        # We receive (but ignore) any client messages — they're only used to detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(user_id)
        logger.info("WebSocket disconnected: user %s", user_id)
