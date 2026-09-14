"""queue_messages — the durable work queue that replaces Kafka

Kafka carried three streams between four processes: raw-articles (ingestion →
pipeline), matched-articles (pipeline → alert) and sub-theme-events (discovery
→ alert). At the measured volume — roughly 0.15 messages/second, with an
LLM-bound consumer that cannot exceed ~1 article/second per worker — a broker
built for 10^5-10^6 msg/sec was five orders of magnitude oversized, and every
message it carried was already destined for this database anyway.

One table replaces all three topics. `queue` is the topic name, so the three
streams stay logically separate while sharing one implementation, one set of
indexes and one reaper.

WHY THIS IS SAFE
----------------
SELECT ... FOR UPDATE SKIP LOCKED is what makes competing consumers work.
FOR UPDATE takes a row-level lock inside the claiming transaction; SKIP LOCKED
tells a second worker not to wait on a locked row but to step over it and take
the next one. Two workers physically cannot claim the same row — the same
guarantee a Kafka consumer group gives, in one statement.

THE INDEXES ARE PARTIAL ON PURPOSE
----------------------------------
Both indexes carry a WHERE clause, so they only contain rows in the state the
query actually looks for. A queue that has processed ten million messages but
holds forty pending ones has a forty-row index — the claim query stays the
same speed forever, regardless of how much history the table has accumulated.
This is what keeps a table-as-queue from degrading as it grows.

RETENTION
---------
Kafka expired messages with retention.ms. Here that is a DELETE, run by the
purge_queue_messages Celery Beat task — see app/tasks/maintenance/retention.py.

Revision ID: 015_queue_messages
Revises: 014_hist_memberships
Create Date: 2026-09-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_queue_messages"
down_revision: Union[str, None] = "014_hist_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE queue_messages (
            id          BIGSERIAL PRIMARY KEY,
            queue       TEXT        NOT NULL,
            payload     JSONB       NOT NULL,
            status      TEXT        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'processing', 'done', 'failed')),
            attempts    INTEGER     NOT NULL DEFAULT 0,
            last_error  TEXT,
            locked_at   TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # The claim query: WHERE queue = ? AND status = 'pending' ORDER BY id.
    # id is BIGSERIAL, so ordering by it is insertion order — the same
    # first-in-first-out delivery a Kafka partition gives.
    op.execute(
        """
        CREATE INDEX idx_queue_messages_claim
            ON queue_messages (queue, id)
            WHERE status = 'pending'
        """
    )

    # The reaper query: rows stuck in 'processing' because the worker holding
    # them died. Partial for the same reason as above — in a healthy system
    # this index is nearly empty.
    op.execute(
        """
        CREATE INDEX idx_queue_messages_reap
            ON queue_messages (queue, locked_at)
            WHERE status = 'processing'
        """
    )

    # The pruner query: old terminal rows, deleted on a schedule.
    op.execute(
        """
        CREATE INDEX idx_queue_messages_prune
            ON queue_messages (updated_at)
            WHERE status IN ('done', 'failed')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS queue_messages")
