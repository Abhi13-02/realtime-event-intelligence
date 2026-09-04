"""Postgres-backed work queue — the transport that replaced Kafka.

Two classes, not one, for exactly the reason the Kafka consumer factories
needed two builders: the pipeline runs a synchronous loop around CPU-bound NLP
work and has no event loop to await on, while the alert consumers are asyncio
tasks and must not block one. PgQueue speaks psycopg2, AsyncPgQueue speaks
SQLAlchemy's async session. They implement the same protocol and cannot be
collapsed.

THE CLAIM
---------
    SELECT id, payload FROM queue_messages
    WHERE queue = %s AND status = 'pending'
    ORDER BY id
    FOR UPDATE SKIP LOCKED
    LIMIT %s

FOR UPDATE locks the selected rows for the life of the transaction. SKIP LOCKED
makes a concurrent worker step over rows another worker already holds instead
of blocking on them. Two workers therefore cannot claim the same message, and
neither one waits — which is the whole of what a Kafka consumer group provided
here.

The claim commits immediately, flipping the rows to 'processing'. Work happens
outside that transaction. The alternative — holding the transaction open for
the whole job — gives free crash recovery via rollback, but a Groq call takes
seconds and that would pin a database connection for the duration. Short
transactions plus an explicit reaper is the trade this makes.

CRASH RECOVERY
--------------
Because the claim commits, a worker that dies mid-article leaves its row in
'processing' with nobody holding it. reap_stalled() returns any row whose
locked_at is older than the visibility timeout to 'pending'. That is the
counterpart of an uncommitted Kafka offset being redelivered on restart —
except it happens on a timer rather than requiring a restart.

DELIVERY GUARANTEE
------------------
At-least-once, the same as the Kafka setup. A message whose worker crashes
after the work but before ack() is reaped and redelivered, so consumers must
tolerate seeing a message twice. They already do: articles.url is UNIQUE and
the inserts downstream are ON CONFLICT DO NOTHING.

RETRIES
-------
Better than what it replaces. Under Kafka, "do not commit the offset" meant the
message sat until the container was restarted, blocking its partition in the
meantime. retry() puts a row straight back to 'pending' with attempts + 1, and
after max_attempts it is parked in 'failed' — a dead-letter state that is one
SQL query away from being inspected, fixed and requeued.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Sequence

import psycopg2
import psycopg2.extras
from sqlalchemy import text

logger = logging.getLogger(__name__)

# How long a row may sit in 'processing' before the reaper assumes its worker
# died and returns it to 'pending'. Must exceed the slowest realistic job: the
# pipeline's worst case is an embedding call plus a Groq summarisation, which
# is seconds, not minutes. Five minutes is deliberately generous — reaping a
# message that is actually still being worked on causes duplicate processing.
DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 300

# After this many attempts a message is parked in 'failed' rather than retried
# forever. Kafka had no equivalent; a poison message there blocked its
# partition until a human noticed.
DEFAULT_MAX_ATTEMPTS = 5

# What a dead connection actually raises. Two different exceptions, because
# psycopg2 distinguishes how the connection died, and both mean "reconnect":
#
#   OperationalError — the server went away mid-statement (restart, network
#                      drop, an idle-timeout kill). This is the common one.
#   InterfaceError   — the connection object is already closed, so the driver
#                      never even tried. A pooler dropping us, or a shutdown
#                      path that closed it, looks like this.
#
# Catching only the first leaves a long-lived consumer dead in the second case,
# which is the one it cannot log its way out of.
_DEAD_CONNECTION = (psycopg2.OperationalError, psycopg2.InterfaceError)


@dataclass(frozen=True)
class QueueMessage:
    """One claimed message. `payload` is the dict the producer published."""

    id: int
    payload: dict
    attempts: int


# ── SQL ───────────────────────────────────────────────────────────────────
# Written once and shared by both implementations so the sync and async paths
# cannot drift apart in their semantics. The placeholder style differs between
# psycopg2 (%s) and SQLAlchemy (:name), so each class formats these itself.

_CLAIM_CTE = """
    WITH claimed AS (
        SELECT id
        FROM queue_messages
        WHERE queue = {q} AND status = 'pending'
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT {limit}
    )
    UPDATE queue_messages m
    SET status = 'processing',
        locked_at = NOW(),
        updated_at = NOW(),
        attempts = m.attempts + 1
    FROM claimed c
    WHERE m.id = c.id
    RETURNING m.id, m.payload, m.attempts
"""

_ACK = """
    UPDATE queue_messages
    SET status = 'done', locked_at = NULL, updated_at = NOW()
    WHERE id = {id}
"""

_RETRY = """
    UPDATE queue_messages
    SET status = CASE WHEN attempts >= {max_attempts} THEN 'failed' ELSE 'pending' END,
        locked_at = NULL,
        last_error = {err},
        updated_at = NOW()
    WHERE id = {id}
    RETURNING status
"""

_FAIL = """
    UPDATE queue_messages
    SET status = 'failed', locked_at = NULL, last_error = {err}, updated_at = NOW()
    WHERE id = {id}
"""

_REAP = """
    UPDATE queue_messages
    SET status = 'pending',
        locked_at = NULL,
        updated_at = NOW(),
        last_error = 'reaped: worker did not finish within the visibility timeout'
    WHERE queue = {q}
      AND status = 'processing'
      AND locked_at < NOW() - make_interval(secs => {timeout})
    RETURNING id
"""

_DEPTH = """
    SELECT count(*) FROM queue_messages
    WHERE queue = {q} AND status = 'pending'
"""

_INSERT = "INSERT INTO queue_messages (queue, payload) VALUES %s"
_INSERT_TEMPLATE = "(%s, %s::jsonb)"


class PgQueue:
    """
    Synchronous queue client (psycopg2).

    Used by the pipeline consumer to consume, and by every producer — the
    ingestion Celery tasks, the pipeline's own event bus and the discovery
    task — since all of those run in synchronous contexts.

    Owns its connection and runs it in autocommit: every method here is a
    single self-contained statement, and autocommit keeps the claim
    transaction as short as it can possibly be.
    """

    def __init__(
        self,
        connection_string: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        visibility_timeout: int = DEFAULT_VISIBILITY_TIMEOUT_SECONDS,
    ) -> None:
        self._connection_string = connection_string
        self.max_attempts = max_attempts
        self.visibility_timeout = visibility_timeout
        self.conn = psycopg2.connect(connection_string)
        self.conn.autocommit = True

    def _reconnect(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = psycopg2.connect(self._connection_string)
        self.conn.autocommit = True

    def _execute(self, sql: str, args: Sequence[Any] = ()):
        """Run one statement, reconnecting once if the connection has died."""
        try:
            cur = self.conn.cursor()
            cur.execute(sql, args)
            return cur
        except _DEAD_CONNECTION:
            logger.warning("Queue DB connection lost — reconnecting and retrying.")
            self._reconnect()
            cur = self.conn.cursor()
            cur.execute(sql, args)
            return cur

    # ── Producing ─────────────────────────────────────────────────────────

    def publish(self, queue: str, payload: dict) -> None:
        """Append one message. Committed on return (autocommit)."""
        self.publish_many(queue, [payload])

    def publish_many(self, queue: str, payloads: Sequence[dict]) -> None:
        """
        Append several messages in one round trip.

        This is the batched INSERT that makes a poll-cycle burst cheap: a crawl
        producing 450 articles is one statement, not 450.
        """
        if not payloads:
            return

        rows = [(queue, json.dumps(p)) for p in payloads]
        try:
            with self.conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur, _INSERT, rows, template=_INSERT_TEMPLATE
                )
        except _DEAD_CONNECTION:
            logger.warning("Queue DB connection lost on publish — reconnecting.")
            self._reconnect()
            with self.conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur, _INSERT, rows, template=_INSERT_TEMPLATE
                )

    # ── Consuming ─────────────────────────────────────────────────────────

    def claim(self, queue: str, limit: int = 10) -> list[QueueMessage]:
        """
        Take up to `limit` pending messages for this worker alone.

        Returns [] when the queue is empty — the caller sleeps and asks again.
        """
        cur = self._execute(_CLAIM_CTE.format(q="%s", limit="%s"), (queue, limit))
        rows = cur.fetchall()
        cur.close()
        return [QueueMessage(id=r[0], payload=r[1], attempts=r[2]) for r in rows]

    def ack(self, message_id: int) -> None:
        """Mark the message done. The queue is finished with it."""
        self._execute(_ACK.format(id="%s"), (message_id,)).close()

    def retry(self, message_id: int, error: str) -> None:
        """
        Return the message to 'pending' so the next poll picks it up again.

        Once attempts reaches max_attempts the row is parked in 'failed'
        instead, so a message that can never succeed stops consuming workers.
        """
        cur = self._execute(
            _RETRY.format(max_attempts="%s", err="%s", id="%s"),
            (self.max_attempts, error[:2000], message_id),
        )
        row = cur.fetchone()
        cur.close()
        if row and row[0] == "failed":
            logger.error(
                "Message %s exhausted %d attempts — parked in 'failed': %s",
                message_id, self.max_attempts, error,
            )

    def fail(self, message_id: int, error: str) -> None:
        """Park the message in 'failed' now, without further retries."""
        self._execute(_FAIL.format(err="%s", id="%s"), (error[:2000], message_id)).close()

    def reap_stalled(self, queue: str) -> int:
        """
        Return rows abandoned by a dead worker to 'pending'. Returns how many.

        Called at the top of the consumer loop rather than by a separate
        process: the consumer is already running, already connected, and is
        the thing that cares.
        """
        cur = self._execute(
            _REAP.format(q="%s", timeout="%s"), (queue, self.visibility_timeout)
        )
        reaped = cur.rowcount
        cur.close()
        if reaped:
            logger.warning("Reaped %d stalled message(s) on queue '%s'.", reaped, queue)
        return reaped

    def depth(self, queue: str) -> int:
        """Pending message count — the backlog, one query away."""
        cur = self._execute(_DEPTH.format(q="%s"), (queue,))
        n = cur.fetchone()[0]
        cur.close()
        return n

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


class AsyncPgQueue:
    """
    Asyncio queue client, for the two alert consumers.

    Unlike PgQueue this owns no connection: it borrows an AsyncSession from the
    app's existing session factory per call, so the alert container keeps using
    one pool for both its queue traffic and its ordinary reads.
    """

    def __init__(
        self,
        session_factory,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        visibility_timeout: int = DEFAULT_VISIBILITY_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self.max_attempts = max_attempts
        self.visibility_timeout = visibility_timeout

    async def publish(self, queue: str, payload: dict) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO queue_messages (queue, payload) "
                    "VALUES (:q, CAST(:p AS jsonb))"
                ),
                {"q": queue, "p": json.dumps(payload)},
            )
            await session.commit()

    async def claim(self, queue: str, limit: int = 10) -> list[QueueMessage]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(_CLAIM_CTE.format(q=":q", limit=":lim")),
                {"q": queue, "lim": limit},
            )
            rows = result.fetchall()
            await session.commit()
        return [QueueMessage(id=r[0], payload=r[1], attempts=r[2]) for r in rows]

    async def ack(self, message_id: int) -> None:
        async with self._session_factory() as session:
            await session.execute(text(_ACK.format(id=":id")), {"id": message_id})
            await session.commit()

    async def retry(self, message_id: int, error: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(_RETRY.format(max_attempts=":maxa", err=":err", id=":id")),
                {"maxa": self.max_attempts, "err": error[:2000], "id": message_id},
            )
            row = result.fetchone()
            await session.commit()
        if row and row[0] == "failed":
            logger.error(
                "Message %s exhausted %d attempts — parked in 'failed': %s",
                message_id, self.max_attempts, error,
            )

    async def fail(self, message_id: int, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(_FAIL.format(err=":err", id=":id")),
                {"err": error[:2000], "id": message_id},
            )
            await session.commit()

    async def reap_stalled(self, queue: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                text(_REAP.format(q=":q", timeout=":t")),
                {"q": queue, "t": self.visibility_timeout},
            )
            reaped = len(result.fetchall())
            await session.commit()
        if reaped:
            logger.warning("Reaped %d stalled message(s) on queue '%s'.", reaped, queue)
        return reaped

    async def depth(self, queue: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                text(_DEPTH.format(q=":q")), {"q": queue}
            )
            return result.scalar_one()
