"""
Celery task: delete expired 'dropped' articles.

Dropped articles exist for one reason — so stage_0_url_deduplicate recognises
a URL the pipeline has already embedded and skips the expensive work. That
value expires once the article falls out of every publisher's feed, after
which the row is dead weight.

Retention is deliberately generous. Measured on the live feeds, 35% of
articles seen two hours earlier were still being served, so a short window
would let articles start getting re-embedded again. Seven days of dropped
articles costs roughly 500 MB, against 149 GB free.

Only 'dropped' rows are touched. 'passed_dedup' and 'processed' articles are
user-facing history and are never deleted here.
"""
import logging

import psycopg2

from app.celery_app import celery_app
from app.constants import get_sync_db_url

logger = logging.getLogger(__name__)

# How long a dropped article stays useful as a "seen" marker.
DROPPED_ARTICLE_RETENTION_DAYS = 7

# Cap per run so a backlog can never hold a long lock on the articles table.
# Beat runs this hourly, so the ceiling is ~240k rows/day — far above intake.
DELETE_BATCH_LIMIT = 10_000


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
