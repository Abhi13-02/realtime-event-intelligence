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
from app.constants import get_sync_db_url

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


def _get_dynamic_setting(cur: Any, key: str, default: Any, description: str = None) -> Any:
    """Fetch a setting from the system_settings table, falling back to default."""
    try:
        cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        if row and row["value"] is not None:
            # Psycopg2 RealDictCursor returns the JSONB as a Python object
            return row["value"]
        else:
            # Self-healing: if the setting is missing, seed it with the default
            logger.info("Seeding missing dynamic setting: %s = %s", key, default)
            cur.execute(
                "INSERT INTO system_settings (key, value, description) VALUES (%s, %s, %s) ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(default), description or f"Dynamic override for {key}")
            )
            # Commit the seed immediately
            if hasattr(cur.connection, 'commit'):
                cur.connection.commit()
    except Exception as e:
        logger.warning("Failed to fetch dynamic setting %s: %s", key, e)
    return default


@celery_app.task(name="app.tasks.subtheme_discovery.run_subtheme_discovery")
def run_subtheme_discovery() -> None:
    """
    Celery periodic task triggered by Celery Beat every SUBTHEME_DISCOVERY_INTERVAL_HOURS.
    Processes ALL active topics — a failure on one topic does not block others.
    """
    settings = get_settings()
    db_url = get_sync_db_url()

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch dynamic overrides
        settings.subtheme_window_days = _get_dynamic_setting(cur, "subtheme_window_days", settings.subtheme_window_days, "Rolling window size (days) for discovery.")
        settings.subtheme_min_cluster_size = _get_dynamic_setting(cur, "subtheme_min_cluster_size", settings.subtheme_min_cluster_size, "Min articles required to form a sub-theme.")
        settings.subtheme_min_samples = _get_dynamic_setting(cur, "subtheme_min_samples", settings.subtheme_min_samples, "Noise control. Lower = more granular, but more noise.")
        settings.subtheme_cluster_selection_method = _get_dynamic_setting(cur, "subtheme_cluster_selection_method", settings.subtheme_cluster_selection_method, "Strategy: 'eom' (broad) or 'leaf' (specific).")
        settings.subtheme_reddit_assign_threshold = _get_dynamic_setting(cur, "subtheme_reddit_assign_threshold", settings.subtheme_reddit_assign_threshold, "Similarity threshold for Reddit -> News mapping (0.0 to 1.0).")
        
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
def run_subtheme_discovery_for_topic(topic_id: str) -> str:
    """
    Run sub-theme discovery for a single topic.
    Called on-demand via POST /v1/topics/{topic_id}/discover.
    Returns a status message.
    """
    settings = get_settings()
    db_url = get_sync_db_url()

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    # Fetch dynamic overrides
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        settings.subtheme_window_days = _get_dynamic_setting(cur, "subtheme_window_days", settings.subtheme_window_days, "Rolling window size (days) for discovery.")
        settings.subtheme_min_cluster_size = _get_dynamic_setting(cur, "subtheme_min_cluster_size", settings.subtheme_min_cluster_size, "Min articles required to form a sub-theme.")
        settings.subtheme_min_samples = _get_dynamic_setting(cur, "subtheme_min_samples", settings.subtheme_min_samples, "Noise control. Lower = more granular, but more noise.")
        settings.subtheme_cluster_selection_method = _get_dynamic_setting(cur, "subtheme_cluster_selection_method", settings.subtheme_cluster_selection_method, "Strategy: 'eom' (broad) or 'leaf' (specific).")
        settings.subtheme_reddit_assign_threshold = _get_dynamic_setting(cur, "subtheme_reddit_assign_threshold", settings.subtheme_reddit_assign_threshold, "Similarity threshold for Reddit -> News mapping (0.0 to 1.0).")

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
            msg = f"Topic {topic_id} not found or inactive."
            logger.warning("run_subtheme_discovery_for_topic: %s", msg)
            return msg

        try:
            return _process_topic(
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
) -> str:
    """Run the full discovery pipeline for a single topic. Returns a summary message."""
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
        msg = f"Skipped: Only {len(rows)} articles found (min {settings.subtheme_min_articles} required)."
        _update_progress(100, msg)
        logger.info("Topic %s: %s", topic_id, msg)
        return msg

    articles = []
    for r in rows:
        articles.append(_ArticleRow(
            id=str(r["id"]),
            embedding=np.array(_parse_pgvector(r["embedding"])),
            headline=r["headline"] or ""
        ))

    logger.info("  → Loaded %d news articles for clustering.", len(articles))

    # ── Step 1: Clustering ────────────────────────────────────────────────────
    _update_progress(15, "CLUSTERING NARRATIVES...")
    sub_theme_data = _step1_cluster(articles, settings)
    if not sub_theme_data:
        msg = "Skipped: No clusters detected in current article set."
        _update_progress(100, msg)
        logger.info("Topic %s: %s", topic_id, msg)
        return msg

    logger.info("  → HDBSCAN produced %d raw cluster(s).", len(sub_theme_data))

    # ── Step 2: Reddit assignment ─────────────────────────────────────────────
    _update_progress(40, "MAPPING SOCIAL SIGNAL...")
    _step2_assign_reddit(cur, conn, topic_id, sub_theme_data, settings)

    # ── Step 3: Reddit Sentiment ──────────────────────────────────────────────
    _update_progress(65, "ANALYZING COMMUNITY RESPONSE...")
    _step3_process_reddit_sentiment(cur, sub_theme_data, vader)

    # ── Step 4: LLM labeling ──────────────────────────────────────────────────
    _update_progress(85, "GENERATING LABELS...")
    _step4_label(cur, topic_id, topic_name, sub_theme_data, groq_client, settings)

    # ── Step 4.5: The Sunsetter (Zombie Cleanup) ──────────────────────────────
    matched_ids = [st.sub_theme_id for st in sub_theme_data if not st.is_new and st.sub_theme_id]
    
    cur.execute("""
        SELECT id, label, description, keywords, centroid, representative_article_id
        FROM sub_themes
        WHERE topic_id = %s AND status != 'inactive'
    """, (topic_id,))
    existing_active = cur.fetchall()
    
    for row in existing_active:
        st_id = str(row["id"])
        if st_id not in matched_ids:
            orphaned_st = _SubThemeData(
                label=-1,
                members=[],
                centroid=np.array(_parse_pgvector(row["centroid"])),
                representative_article_id=row["representative_article_id"],
                keywords=row["keywords"],
                reddit_post_ids=[],
                reddit_post_count=0,
                sentiment_score=None,
                sub_theme_id=st_id,
                is_new=False,
                should_relabel=False,
                label_text=row["label"],
                description_text=row["description"],
                status="inactive",
                events=[]
            )
            sub_theme_data.append(orphaned_st)

    # ── Step 5: Evolution detection ───────────────────────────────────────────
    _step5_evolution(cur, sub_theme_data, settings)

    # ── Step 6: Persist ───────────────────────────────────────────────────────
    _step6_persist(cur, conn, topic_id, sub_theme_data)
    _update_progress(100, "INTELLIGENCE PERSISTED.")

    # ── Step 7: Publish to Kafka ──────────────────────────────────────────────
    _step7_publish(cur, producer, topic_id, sub_theme_data)

    conn.commit()

    # ── Final: Rich Summary Log ───────────────────────────────────────────────
    _log_discovery_summary(topic_name, topic_id, sub_theme_data, settings)

    msg = f"Narrative discovery complete. Identified {len(sub_theme_data)} clusters."
    return msg


def _log_discovery_summary(
    topic_name: str,
    topic_id: str,
    sub_theme_data: list,
    settings: Any,
) -> None:
    """Print a structured, human-readable summary of the discovery run."""
    sep  = "═" * 70
    thin = "─" * 70

    new_clusters      = [st for st in sub_theme_data if st.is_new]
    existing_clusters = [st for st in sub_theme_data if not st.is_new]
    gone_clusters     = [st for st in sub_theme_data if st.status == "inactive"]
    growing_clusters  = [st for st in sub_theme_data if "sub_theme_growing" in (st.events or [])]
    declining_clusters= [st for st in sub_theme_data if st.status == "declining"]

    reddit_clusters   = [st for st in sub_theme_data if st.reddit_post_count > 0]
    total_reddit_posts= sum(st.reddit_post_count for st in sub_theme_data)
    sentiment_clusters= [st for st in sub_theme_data if st.sentiment_score is not None]

    logger.info("")
    logger.info(sep)
    logger.info("  DISCOVERY COMPLETE  ·  Topic: \"%s\"", topic_name)
    logger.info("  Topic ID: %s", topic_id)
    logger.info(sep)

    # ── High-Level Stats ─────────────────────────────────────────────────────
    logger.info("")
    logger.info("  OVERVIEW")
    logger.info(thin)
    logger.info("  Total clusters identified : %d", len(sub_theme_data))
    logger.info("  ┌─ NEW clusters           : %d", len(new_clusters))
    logger.info("  ├─ EXISTING (matched)     : %d", len(existing_clusters))
    logger.info("  ├─ GROWING  (≥%.0f%% vol↑)  : %d", settings.subtheme_growing_threshold * 100, len(growing_clusters))
    logger.info("  ├─ DECLINING              : %d", len(declining_clusters))
    logger.info("  └─ GONE (inactive)        : %d", len(gone_clusters))
    logger.info("")

    # ── New Clusters ─────────────────────────────────────────────────────────
    if new_clusters:
        logger.info("  NEW CLUSTERS  (+%d)", len(new_clusters))
        logger.info(thin)
        for st in new_clusters:
            vol = len(st.members) + st.reddit_post_count
            label = (st.label_text or "[unlabeled]")[:60]
            sent  = f"{st.sentiment_score:+.3f}" if st.sentiment_score is not None else "N/A"
            logger.info("  [NEW]  %-60s", label)
            logger.info("         Articles: %-4d  Reddit: %-3d  Volume: %-4d  Sentiment: %s",
                        len(st.members), st.reddit_post_count, vol, sent)
        logger.info("")

    # ── Existing Clusters: Growth / Drop ─────────────────────────────────────
    if existing_clusters:
        logger.info("  EXISTING CLUSTERS (%d)", len(existing_clusters))
        logger.info(thin)
        for st in existing_clusters:
            vol = len(st.members) + st.reddit_post_count
            label = (st.label_text or "[unlabeled]")[:55]
            sent  = f"{st.sentiment_score:+.3f}" if st.sentiment_score is not None else "  N/A"
            events_str = ", ".join(st.events) if st.events else "—"

            # Determine trend indicator
            if "sub_theme_growing" in (st.events or []):
                trend = "▲ GROWING"
            elif st.status == "declining":
                trend = "▼ DECLINING"
            elif st.status == "inactive":
                trend = "✕ GONE"
            else:
                trend = "● STABLE"

            logger.info("  [%s]  %-55s", trend, label)
            logger.info("         Articles: %-4d  Reddit: %-3d  Volume: %-4d  Sentiment: %s",
                        len(st.members), st.reddit_post_count, vol, sent)
            if st.events:
                logger.info("         Events   : %s", events_str)
        logger.info("")

    # ── Reddit & Sentiment Section ────────────────────────────────────────────
    logger.info("  REDDIT & SENTIMENT SIGNAL")
    logger.info(thin)
    logger.info("  Reddit posts matched to clusters : %d  (across %d cluster(s))",
                total_reddit_posts, len(reddit_clusters))
    logger.info("  Clusters with sentiment data     : %d / %d",
                len(sentiment_clusters), len(sub_theme_data))

    if sentiment_clusters:
        logger.info("")
        logger.info("  Per-cluster sentiment breakdown:")
        sorted_by_sent = sorted(sentiment_clusters, key=lambda x: x.sentiment_score or 0, reverse=True)
        for st in sorted_by_sent:
            bar_val = int((st.sentiment_score + 1.0) / 2.0 * 20)  # map [-1,1] -> [0,20]
            bar = "█" * bar_val + "░" * (20 - bar_val)
            label = (st.label_text or "[unlabeled]")[:45]
            logger.info("  %+.3f  [%s]  %s  (%d posts)",
                        st.sentiment_score, bar, label, st.reddit_post_count)
    logger.info("")
    logger.info(sep)
    logger.info("")
