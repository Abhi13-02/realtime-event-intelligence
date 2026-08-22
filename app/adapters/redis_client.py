"""Shared async Redis clients — the only place from_url() is called.

There were three copies of the same lazy-singleton boilerplate: one in
app/api/topics.py, one in app/alert/websocket.py, one in the pub/sub module.
Two of them pointed at the same URL, so the backend process built two separate
pools to db 1 for no reason.

Note this is about duplication and layering, not resources. redis-py pools are
lazy — from_url() allocates a Python object and opens zero sockets until the
first command runs — so the old version was not leaking connections. The reason
to fix it is that a route file had no business calling from_url() at all.

Sharing one client between the ticket store and the Pub/Sub subscriber is safe:
redis-py hands PubSub its own dedicated connection out of the pool and keeps it
for the life of the subscription, while ordinary GET/SETEX commands take other
connections. That is the documented pattern, and it is the assumption this
whole consolidation rests on.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import get_settings

_cache: aioredis.Redis | None = None
_ws: aioredis.Redis | None = None


def get_redis_cache() -> aioredis.Redis:
    """
    Client for db 0 — shared with the Celery broker.

    Used for discovery task state and the trigger debounce. Kept separate from
    db 1 so a `FLUSHDB` on either cannot take out the other.
    """
    global _cache
    if _cache is None:
        _cache = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _cache


def get_redis_ws() -> aioredis.Redis:
    """
    Client for db 1 — WebSocket tickets and the alert Pub/Sub backplane.

    The db index is cosmetic for Pub/Sub: PUBLISH and SUBSCRIBE ignore the
    selected database and are global to the server. What keeps the backplane
    traffic separate is the channel name, not this URL.
    """
    global _ws
    if _ws is None:
        _ws = aioredis.from_url(
            get_settings().websocket_redis_url, decode_responses=True
        )
    return _ws
