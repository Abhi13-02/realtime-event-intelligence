"""
Celery task: match a newly created (or reactivated) topic against stored articles.

Why this exists
---------------
Before dropped articles were persisted, the pipeline re-embedded everything on
every crawl. A side effect was that a new topic eventually picked up older
articles — as long as they were still sitting in a publisher's feed. That was
never designed, cost 7.4x in redundant compute, and silently missed anything
that had already rotated out of the feed.

Now that every embedding is stored, the same job is one vector search instead.
It is also strictly better: it reaches articles that left the feed days ago.

Delivery
--------
This writes to the database directly and never publishes to Kafka. Nothing is
pushed over WebSocket and no Twilio task is enqueued. Alert rows are inserted
with status='sent' so the midnight email digest — which selects only
status='pending' — leaves them alone. The result is history the user can see
in the UI, with no burst of notifications for articles they never asked to be
interrupted about.
"""
import json
import logging

import psycopg2
import psycopg2.extras

from app.celery_app import celery_app
from app.constants import get_sync_db_url

logger = logging.getLogger(__name__)

# Match the retention window: backfilling further back than we keep dropped
# articles would find nothing.
BACKFILL_WINDOW_DAYS = 7

# Nearest neighbours pulled per topic vector before threshold filtering.
CANDIDATES_PER_VECTOR = 500

# HNSW candidate list size. Raised above the default 40 because the crawled_at
# filter is applied after the index scan — a wider search protects recall.
HNSW_EF_SEARCH = 200

DEFAULT_THRESHOLDS = {"broad": 0.3, "balanced": 0.35, "high": 0.4}


def _vec(embedding: list) -> str:
    return f"[{','.join(str(f) for f in embedding)}]"


@celery_app.task(name="app.tasks.backfill.backfill_topic", bind=True, max_retries=2)
def backfill_topic(self, topic_id: str) -> dict:
    """Find stored articles matching this topic and record them as seen history."""
    conn = psycopg2.connect(get_sync_db_url())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # ── Load the topic ────────────────────────────────────────────
            cur.execute(
                """
                SELECT t.user_id, t.name, t.sensitivity, t.embedding
                FROM topics t
                WHERE t.id = %s AND t.is_active = TRUE AND t.embedding IS NOT NULL
                """,
                (topic_id,),
            )
            row = cur.fetchone()
            if row is None:
                logger.info("Backfill skipped — topic %s inactive or has no embedding", topic_id)
                return {"matched": 0, "reason": "topic_not_eligible"}

            user_id, topic_name, sensitivity, parent_embedding = row

            cur.execute(
                "SELECT embedding FROM topic_subtopics WHERE topic_id = %s", (topic_id,)
            )
            vectors = [json.loads(parent_embedding)]
            vectors.extend(json.loads(r[0]) for r in cur.fetchall() if r[0])

            # ── Threshold, same source the pipeline uses ──────────────────
            cur.execute("SELECT key, value FROM system_settings")
            settings = {k: v for k, v in cur.fetchall()}
            threshold = settings.get(
                f"threshold_{sensitivity}", DEFAULT_THRESHOLDS.get(sensitivity, 0.4)
            )

            # ── Nearest-neighbour search per vector ───────────────────────
            cur.execute("SET LOCAL hnsw.ef_search = %s", (HNSW_EF_SEARCH,))

            best: dict = {}  # article_id -> highest similarity across vectors
            for vector in vectors:
                vec_str = _vec(vector)
                cur.execute(
                    """
                    SELECT id, 1 - (embedding <=> %s::vector) AS similarity
                    FROM articles
                    WHERE embedding IS NOT NULL
                      AND crawled_at >= NOW() - make_interval(days => %s)
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vec_str, BACKFILL_WINDOW_DAYS, vec_str, CANDIDATES_PER_VECTOR),
                )
                for article_id, similarity in cur.fetchall():
                    if similarity > best.get(article_id, -1.0):
                        best[article_id] = similarity

            matches = [(aid, sim) for aid, sim in best.items() if sim >= threshold]
            if not matches:
                conn.commit()
                logger.info(
                    "Backfill for '%s' (%s): no articles above threshold %.2f",
                    topic_name, topic_id, threshold,
                )
                return {"matched": 0, "threshold": threshold}

            # ── Record the topic match ────────────────────────────────────
            # topic_id travels inside each tuple: execute_values allows exactly
            # one %s placeholder (the VALUES list), so it cannot be bound
            # separately alongside it.
            match_rows = [(aid, topic_id, sim) for aid, sim in matches]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO article_topic_matches
                    (article_id, topic_id, relevance_score, credibility_score)
                SELECT v.article_id, v.topic_id, v.score,
                       COALESCE((SELECT s.credibility_score
                                 FROM sources s
                                 JOIN articles a ON a.source_id = s.id
                                 WHERE a.id = v.article_id), 0.5)
                FROM (VALUES %s) AS v(article_id, topic_id, score)
                ON CONFLICT (article_id, topic_id) DO NOTHING
                """,
                match_rows,
                template="(%s::uuid, %s::uuid, %s::float)",
                page_size=500,
            )

            article_ids = [aid for aid, _ in matches]

            # A dropped article has no summary — Stage 6 never ran on it. Give
            # it the same treatment the live path uses (use_description=True)
            # so the UI has something to render.
            cur.execute(
                """
                UPDATE articles
                SET pipeline_status = 'processed',
                    summary = COALESCE(summary, content)
                WHERE id = ANY(%s::uuid[]) AND pipeline_status = 'dropped'
                """,
                (article_ids,),
            )
            promoted = cur.rowcount

            # ── Alert rows: visible history, already marked delivered ─────
            cur.execute("SELECT channel FROM topic_channels WHERE topic_id = %s", (topic_id,))
            channels = [r[0] for r in cur.fetchall()] or ["websocket"]

            alert_rows = [
                (str(user_id), aid, topic_id, sim, channel)
                for aid, sim in matches
                for channel in channels
            ]
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO alerts
                    (user_id, article_id, topic_id, relevance_score, channel, status, sent_at)
                VALUES %s
                ON CONFLICT (user_id, article_id, topic_id, channel) DO NOTHING
                """,
                alert_rows,
                template="(%s::uuid, %s::uuid, %s::uuid, %s::float, %s, 'sent', NOW())",
                page_size=500,
            )

        conn.commit()
        # execute_values reports rowcount for its final page only, so the alert
        # figure below is rows attempted rather than rows inserted; conflicts
        # are skipped silently.
        logger.info(
            "Backfill for '%s' (%s): %d article(s) matched at threshold %.2f, "
            "%d promoted from dropped, %d alert row(s) attempted (no notifications sent)",
            topic_name, topic_id, len(matches), threshold, promoted, len(alert_rows),
        )
        return {
            "matched": len(matches),
            "promoted": promoted,
            "alert_rows": len(alert_rows),
            "threshold": threshold,
        }

    except Exception as exc:
        conn.rollback()
        logger.error("Backfill failed for topic %s: %s", topic_id, exc)
        raise self.retry(exc=exc, countdown=60)
    finally:
        conn.close()
