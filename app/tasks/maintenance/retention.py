"""
Celery tasks: age out articles, membership history and queue messages.

Dropped articles exist for one reason — so stage_0_url_deduplicate recognises
a URL the pipeline has already embedded and skips the expensive work. That
value expires once the article falls out of every publisher's feed, after
which the row is dead weight.

Retention is deliberately generous. Measured on the live feeds, 35% of
articles seen two hours earlier were still being served, so a short window
would let articles start getting re-embedded again. Seven days of dropped
articles costs roughly 500 MB, against 149 GB free.

'processed' and 'passed_dedup' articles are user-facing history, but not
forever: purge_old_articles removes every article older than
ARTICLE_RETENTION_DAYS. The delete cascades to its topic matches, alerts,
reddit comments and sub-theme memberships; sub-themes and snapshots that used
it as their representative article keep their row with the link set to NULL.
"""
import logging

import psycopg2

from app.celery_app import celery_app
from app.core.constants import get_sync_db_url

logger = logging.getLogger(__name__)

# How long a dropped article stays useful as a "seen" marker.
DROPPED_ARTICLE_RETENTION_DAYS = 7

# Cap per run so a backlog can never hold a long lock on the articles table.
# Beat runs this hourly, so the ceiling is ~240k rows/day — far above intake.
DELETE_BATCH_LIMIT = 10_000

# How long any article — processed or not — is kept before it is deleted.
ARTICLE_RETENTION_DAYS = 90

# Each article delete cascades into four child tables, so these batches are
# kept smaller than the plain row deletes above.
ARTICLE_DELETE_BATCH_LIMIT = 1_000

# Upper bound on batches per run for the looping purges. Each batch is its own
# short statement (autocommit), so a run can clear a backlog without any single
# DELETE holding a long lock.
MAX_BATCHES_PER_RUN = 50


def _delete_in_batches(cur, sql: str, params: tuple, batch_limit: int) -> int:
    """
    Run a bounded DELETE repeatedly until it comes back short or the per-run
    batch cap is reached. `sql` must take its LIMIT as the last parameter.
    """
    total = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        cur.execute(sql, params + (batch_limit,))
        total += cur.rowcount
        if cur.rowcount < batch_limit:
            break
    return total


@celery_app.task(name="app.tasks.retention.purge_dropped_articles")
def purge_dropped_articles() -> dict:
    """Delete dropped articles older than the retention window."""
    conn = psycopg2.connect(get_sync_db_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # ctid subselect keeps the delete bounded and index-driven via
            # idx_articles_status_crawled_at.
            cur.execute(
                """
                DELETE FROM articles
                WHERE ctid IN (
                    SELECT ctid FROM articles
                    WHERE pipeline_status = 'dropped'
                      AND crawled_at < NOW() - make_interval(days => %s)
                    LIMIT %s
                )
                """,
                (DROPPED_ARTICLE_RETENTION_DAYS, DELETE_BATCH_LIMIT),
            )
            deleted = cur.rowcount

            cur.execute("SELECT COUNT(*) FROM articles WHERE pipeline_status = 'dropped'")
            remaining = cur.fetchone()[0]

        logger.info(
            "Retention: deleted %d dropped article(s) older than %d days — %d remaining",
            deleted,
            DROPPED_ARTICLE_RETENTION_DAYS,
            remaining,
        )
        return {"deleted": deleted, "remaining_dropped": remaining}

    except Exception as exc:
        logger.error("Retention purge failed: %s", exc)
        raise
    finally:
        conn.close()


@celery_app.task(name="app.tasks.retention.purge_old_articles")
def purge_old_articles() -> dict:
    """Delete every article older than ARTICLE_RETENTION_DAYS, whatever its status."""
    conn = psycopg2.connect(get_sync_db_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Index-driven via idx_articles_crawled_at. Child rows go with each
            # batch through ON DELETE CASCADE.
            deleted = _delete_in_batches(
                cur,
                """
                DELETE FROM articles
                WHERE ctid IN (
                    SELECT ctid FROM articles
                    WHERE crawled_at < NOW() - make_interval(days => %s)
                    LIMIT %s
                )
                """,
                (ARTICLE_RETENTION_DAYS,),
                ARTICLE_DELETE_BATCH_LIMIT,
            )

            cur.execute("SELECT COUNT(*) FROM articles")
            remaining = cur.fetchone()[0]

        logger.info(
            "Retention: deleted %d article(s) older than %d days — %d remaining",
            deleted,
            ARTICLE_RETENTION_DAYS,
            remaining,
        )
        return {"deleted": deleted, "remaining_articles": remaining}

    except Exception as exc:
        logger.error("Article retention purge failed: %s", exc)
        raise
    finally:
        conn.close()


# How many discovery runs of membership history to keep per sub-theme.
# Memberships became append-only so the deep-dive page can show which articles
# were in a narrative at any point on its graph. That makes the table grow every
# run and it needs a ceiling.
#
# The timeline chart requests at most 100 snapshots, so keeping 50 runs of
# evidence covers every point a user can actually click. Older snapshots still
# render — the chart reads sub_theme_snapshots, which is never pruned here —
# they just no longer carry a clickable article list.
MEMBERSHIP_RETENTION_RUNS = 50


@celery_app.task(name="app.tasks.retention.purge_old_memberships")
def purge_old_memberships() -> dict:
    """Keep only the most recent N runs of membership history per sub-theme."""
    conn = psycopg2.connect(get_sync_db_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Rank each sub-theme's distinct run timestamps, then delete rows
            # belonging to runs past the cutoff. Ranking runs rather than rows
            # means a sub-theme with many articles per run is not penalised.
            cur.execute(
                """
                DELETE FROM sub_theme_memberships m
                USING (
                    SELECT sub_theme_id, run_at
                    FROM (
                        SELECT sub_theme_id, run_at,
                               ROW_NUMBER() OVER (
                                   PARTITION BY sub_theme_id
                                   ORDER BY run_at DESC
                               ) AS rn
                        FROM (
                            SELECT DISTINCT sub_theme_id, run_at
                            FROM sub_theme_memberships
                        ) runs
                    ) ranked
                    WHERE rn > %s
                ) stale
                WHERE m.sub_theme_id = stale.sub_theme_id
                  AND m.run_at = stale.run_at
                """,
                (MEMBERSHIP_RETENTION_RUNS,),
            )
            deleted = cur.rowcount

            cur.execute("SELECT COUNT(*) FROM sub_theme_memberships")
            remaining = cur.fetchone()[0]

        logger.info(
            "Retention: deleted %d membership row(s) beyond %d runs per sub-theme — %d remaining",
            deleted,
            MEMBERSHIP_RETENTION_RUNS,
            remaining,
        )
        return {"deleted": deleted, "remaining_memberships": remaining}

    except Exception as exc:
        logger.error("Membership retention purge failed: %s", exc)
        raise
    finally:
        conn.close()


# ── Queue retention ───────────────────────────────────────────────────────
# Kafka expired messages on its own with retention.ms. queue_messages needs
# this task instead — the DELETE is what stops a work queue from becoming an
# unbounded log.

# Matches the old raw-articles retention.ms of 7 days. Nothing replays a
# processed message, so this is only about how far back the audit trail goes.
QUEUE_DONE_RETENTION_DAYS = 7


@celery_app.task(name="app.tasks.retention.purge_queue_messages")
def purge_queue_messages() -> dict:
    """
    Delete completed queue messages older than the retention window.

    'failed' rows are deliberately left alone. They are the dead-letter queue —
    every one is a message that exhausted its retries, which is something a
    human should see. Ageing them out on a timer would quietly delete the
    evidence of a bug. There should be almost none; if there are many, that is
    the signal, not the storage cost.
    """
    conn = psycopg2.connect(get_sync_db_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # ctid subselect keeps each delete bounded, the same way the dropped
            # article purge above does. Intake is ~300k messages/day, above what
            # one 10k batch an hour can clear, so this loops over batches.
            deleted = _delete_in_batches(
                cur,
                """
                DELETE FROM queue_messages
                WHERE ctid IN (
                    SELECT ctid FROM queue_messages
                    WHERE status = 'done'
                      AND updated_at < NOW() - make_interval(days => %s)
                    LIMIT %s
                )
                """,
                (QUEUE_DONE_RETENTION_DAYS,),
                DELETE_BATCH_LIMIT,
            )

            cur.execute(
                "SELECT status, COUNT(*) FROM queue_messages GROUP BY status"
            )
            by_status = {row[0]: row[1] for row in cur.fetchall()}

        logger.info(
            "Retention: deleted %d done queue message(s) older than %d days — remaining %s",
            deleted,
            QUEUE_DONE_RETENTION_DAYS,
            by_status,
        )
        if by_status.get("failed"):
            logger.warning(
                "%d queue message(s) are parked in 'failed' and need attention.",
                by_status["failed"],
            )
        return {"deleted": deleted, "remaining": by_status}

    except Exception as exc:
        logger.error("Queue retention purge failed: %s", exc)
        raise
    finally:
        conn.close()
