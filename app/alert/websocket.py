"""
WebSocket connection manager and endpoints.

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
"""
import json
import logging
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.dependencies import get_current_user
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Redis client for ticket storage (db=1 — WebSocket ticket store, separate from Celery broker)
_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(settings.websocket_redis_url, decode_responses=True)
    return _redis


class ConnectionManager:
    """
    In-memory store of active WebSocket connections.
    One connection per user — if a user reconnects, the new connection replaces the old one.
    Shared between the WS endpoint (which registers connections) and the alert consumer
    (which pushes messages). Both run in the same FastAPI process.
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


# Module-level singleton — imported by both this module's WS endpoint and consumer.py
connection_manager = ConnectionManager()


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
    redis = _get_redis()
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
    redis = _get_redis()
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
