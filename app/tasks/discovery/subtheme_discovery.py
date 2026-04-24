"""
Sub-theme Discovery — Celery orchestrator.
Refactored into modular components for better maintainability.
"""
import json
import logging
from typing import Any
import numpy as np
import psycopg2
import psycopg2.extras
from kafka import KafkaProducer
from groq import Groq
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from celery import current_task

from app.celery_app import celery_app
from app.config import get_settings

# Modular components
from .models import _ArticleRow, _SubThemeData, _parse_pgvector
from .clustering import _step1_cluster, _step2_assign_reddit
from .sentiment import _step3_process_reddit_sentiment
from .labeling import _step4_label
from .evolution import _step5_evolution
from .persistence import _step6_persist, _step7_publish

logger = logging.getLogger(__name__)

# Register UUID adapter so psycopg2 returns uuid.UUID objects
psycopg2.extras.register_uuid()

def _update_progress(pct: int, message: str = "Discovering..."):
    """Update Celery task state with progress percentage and stage message."""
    if current_task and current_task.request and current_task.request.id:
        current_task.update_state(state="PROGRESS", meta={"progress": pct, "message": message})


@celery_app.task(name="app.tasks.subtheme_discovery.run_subtheme_discovery")
def run_subtheme_discovery() -> None:
    """
    Celery periodic task triggered by Celery Beat every SUBTHEME_DISCOVERY_INTERVAL_HOURS.
    Processes ALL active topics — a failure on one topic does not block others.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name FROM topics WHERE is_active = TRUE")
        topics = cur.fetchall()

        logger.info("Sub-theme discovery: fanning out to %d active topics.", len(topics))

        for topic_row in topics:
            topic_id = str(topic_row["id"])
            run_subtheme_discovery_for_topic.delay(topic_id)

        # ── Cleanup: delete Reddit posts outside the rolling window ──────────
        try:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM articles
                WHERE source_id = (
                    SELECT id FROM sources WHERE type = 'reddit' LIMIT 1
                )
                AND crawled_at < NOW() - INTERVAL '%s days'
            """, (settings.subtheme_window_days,))
            deleted = cur.rowcount
            conn.commit()
            logger.info("Cleanup: deleted %d Reddit post(s) outside the %d-day window.",
                        deleted, settings.subtheme_window_days)
        except Exception as exc:
            conn.rollback()
            logger.error("Cleanup failed — Reddit posts not deleted: %s", exc)

        logger.info("Sub-theme discovery fan-out complete.")

    finally:
        conn.close()


@celery_app.task(name="app.tasks.subtheme_discovery.run_subtheme_discovery_for_topic")
def run_subtheme_discovery_for_topic(topic_id: str) -> None:
    """
    Run sub-theme discovery for a single topic.
    Called on-demand via POST /v1/topics/{topic_id}/discover.
    """
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    groq_client = Groq(api_key=settings.groq_api_key)
    vader = SentimentIntensityAnalyzer()

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, name FROM topics WHERE id = %s AND is_active = TRUE",
            (topic_id,),
        )
        topic_row = cur.fetchone()

        if topic_row is None:
            logger.warning("run_subtheme_discovery_for_topic: topic %s not found or inactive.", topic_id)
            return

        try:
            _process_topic(
                conn=conn,
                producer=producer,
                groq_client=groq_client,
                vader=vader,
                topic_id=str(topic_row["id"]),
                topic_name=topic_row["name"],
                settings=settings,
            )
        except Exception as exc:
            conn.rollback()
            logger.error("Topic %s (%s) failed: %s", topic_id, topic_row["name"], exc, exc_info=True)
            raise

        logger.info("Sub-theme discovery complete for topic %s.", topic_id)

    finally:
        try:
            producer.flush()
            producer.close()
        except Exception:
            pass
        conn.close()


def _process_topic(
    conn: Any,
    producer: KafkaProducer,
    groq_client: Groq,
    vader: SentimentIntensityAnalyzer,
    topic_id: str,
    topic_name: str,
    settings: Any,
) -> None:
    """Run the full discovery pipeline for a single topic."""
    _update_progress(5, "FETCHING ARTICLES...")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── Guard: Advisory Lock ──────────────────────────────────────────────────
    cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (f"subtheme:{topic_id}",))
    locked = cur.fetchone()["pg_try_advisory_xact_lock"]
    if not locked:
        logger.warning("Topic %s is already being processed (advisory lock failed) — skipping.", topic_id)
        return

    # ── Guard: minimum article count ──────────────────────────────────────────
    cur.execute("""
        SELECT a.id, a.embedding::text, a.headline
        FROM article_topic_matches atm
        JOIN articles a ON atm.article_id = a.id
        JOIN sources  s ON a.source_id    = s.id
        WHERE atm.topic_id  = %s
          AND s.type        != 'reddit'
          AND a.crawled_at  >= NOW() - INTERVAL '%s days'
          AND a.embedding IS NOT NULL
    """, (topic_id, settings.subtheme_window_days))
    rows = cur.fetchall()

    if len(rows) < settings.subtheme_min_articles:
        logger.info("Topic %s: skipping discovery (only %d news articles found, need %d).",
                    topic_id, len(rows), settings.subtheme_min_articles)
        return

    articles = []
    for r in rows:
        articles.append(_ArticleRow(
            id=str(r["id"]),
            embedding=np.array(_parse_pgvector(r["embedding"])),
            headline=r["headline"] or ""
        ))

    # ── Step 1: Clustering ────────────────────────────────────────────────────
    _update_progress(15, "CLUSTERING NARRATIVES...")
    sub_theme_data = _step1_cluster(articles, settings)
    if not sub_theme_data:
        logger.info("Topic %s: no clusters found by HDBSCAN.", topic_id)
        return

    logger.info("Topic %s: found %d sub-theme cluster(s).", topic_id, len(sub_theme_data))

    # ── Step 2: Reddit assignment ─────────────────────────────────────────────
    _update_progress(40, "MAPPING SOCIAL SIGNAL...")
    _step2_assign_reddit(cur, conn, topic_id, sub_theme_data, settings)

    # ── Step 3: Reddit Sentiment ──────────────────────────────────────────────
    _update_progress(65, "ANALYZING COMMUNITY RESPONSE...")
    _step3_process_reddit_sentiment(cur, sub_theme_data, vader)

    # ── Step 4: LLM labeling ──────────────────────────────────────────────────
    _update_progress(85, "GENERATING LABELS...")
    _step4_label(cur, topic_id, topic_name, sub_theme_data, groq_client, settings)

    # ── Step 5: Evolution detection ───────────────────────────────────────────
    _step5_evolution(cur, sub_theme_data, settings)

    # ── Step 6: Persist ───────────────────────────────────────────────────────
    _update_progress(100, "PERSISTING INTELLIGENCE...")
    _step6_persist(cur, conn, topic_id, sub_theme_data)

    # ── Step 7: Publish to Kafka ──────────────────────────────────────────────
    _step7_publish(cur, producer, topic_id, sub_theme_data)

    conn.commit()
    logger.info("Topic %s: discovery committed successfully.", topic_id)
