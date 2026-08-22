"""Discovery job orchestration — triggering runs and reporting their progress.

Extracted from app/api/topics.py, where both routes were doing Redis reads and
writes, Celery result inspection and rate limiting inline. That is the same
mixing of HTTP handling and business rules that was pulled out of the
intelligence and admin routers.

Kept separate from app/services/topics.py rather than appended to it: this is
background-job control, not topic CRUD, and topics.py is already 400 lines.
"""

from __future__ import annotations

from uuid import UUID

from celery.result import AsyncResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.redis_client import get_redis_cache
from app.celery_app import celery_app
from app.db.models import User
from app.services.exceptions import OperationFailed, TooManyRequests
from app.services.topics import get_topic

DISCOVERY_TASK = "app.tasks.subtheme_discovery.run_subtheme_discovery_for_topic"

# How long a trigger blocks further triggers for the same topic. Discovery is a
# multi-minute UMAP/HDBSCAN run, so a spam-clicked button would otherwise queue
# several identical jobs onto a worker with concurrency 2.
DEBOUNCE_SECONDS = 300

# How long the task id is remembered so the status endpoint can find it. Longer
# than any realistic run, short enough that a stale id expires on its own.
TASK_ID_TTL_SECONDS = 3600

# Celery states that mean a run is still in flight.
_ACTIVE_STATES = ("PENDING", "STARTED", "PROGRESS")


def _task_key(topic_id: UUID) -> str:
    return f"discovery_task:{topic_id}"


def _debounce_key(topic_id: UUID) -> str:
    return f"discovery_debounce:{topic_id}"


async def trigger_discovery(db: AsyncSession, user: User, topic_id: UUID) -> dict:
    """
    Queue a discovery run for one of the user's topics and return immediately.

    Two separate guards, which is deliberate:
      - an already-running job is rejected outright (400)
      - a too-soon retrigger is rate limited (429)

    The second is not redundant. A finished job leaves no active state behind,
    so without the debounce a user could re-run an expensive clustering pass
    every few seconds.
    """
    # Ownership check — raises TopicServiceError (404) if not this user's topic.
    await get_topic(db, user=user, topic_id=topic_id)

    redis = get_redis_cache()

    existing_task_id = await redis.get(_task_key(topic_id))
    if existing_task_id:
        result = AsyncResult(existing_task_id, app=celery_app)
        if result.state in _ACTIVE_STATES:
            raise OperationFailed("Discovery is already running for this topic.")

    if await redis.get(_debounce_key(topic_id)):
        raise TooManyRequests(
            "Discovery triggered too recently. Please wait a few minutes."
        )
    await redis.setex(_debounce_key(topic_id), DEBOUNCE_SECONDS, "1")

    task = celery_app.send_task(DISCOVERY_TASK, args=[str(topic_id)])
    await redis.setex(_task_key(topic_id), TASK_ID_TTL_SECONDS, task.id)

    return {"task_id": task.id, "topic_id": str(topic_id), "status": "processing"}


async def get_discovery_status(db: AsyncSession, user: User, topic_id: UUID) -> dict:
    """
    Progress of the most recent discovery run for this topic.

    Returns 'idle' when no task id is stored — either none was ever started, or
    the id has aged out of Redis, which are indistinguishable from here and
    equally uninteresting to the caller.
    """
    await get_topic(db, user=user, topic_id=topic_id)

    task_id = await get_redis_cache().get(_task_key(topic_id))
    if not task_id:
        return {"status": "idle", "progress": 0}

    result = AsyncResult(task_id, app=celery_app)

    progress = 0
    message = "Discovering..."
    if result.state == "PROGRESS" and isinstance(result.info, dict):
        progress = result.info.get("progress", 0)
        message = result.info.get("message", "Discovering...")
    elif result.state == "SUCCESS":
        progress = 100
        # result.result is the task's return value.
        message = result.result if isinstance(result.result, str) else "Discovery Complete"

    return {"status": result.state, "progress": progress, "message": message}
