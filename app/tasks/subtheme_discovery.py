"""
Sub-theme Discovery — Celery periodic task.

Runs every SUBTHEME_DISCOVERY_INTERVAL_HOURS hours (default: 6).
Reads from PostgreSQL directly — no Kafka consumption.

For each active topic:
  [GUARD]  Skip if fewer than SUBTHEME_MIN_ARTICLES GDELT articles in window
  [STEP 1] HDBSCAN clustering of GDELT article embeddings
  [STEP 2] Assign Reddit posts to nearest sub-theme centroid (pgvector ANN)
  [STEP 3] VADER sentiment over pre-stored Reddit comments (stored by teammates)
  [STEP 4] LLM labeling via LangChain + Cohere (only when new or significantly changed)
  [STEP 5] Evolution detection — emerging / growing / disappearing / sentiment shift
  [STEP 6] Persist to sub_themes, sub_theme_memberships, sub_theme_snapshots
  [STEP 7] Publish events to Kafka: sub-theme-events

Uses psycopg2 (sync) — same pattern as tasks/email.py and tasks/sms.py.
All thresholds are configurable via environment variables (see config.py).
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import hdbscan
import numpy as np
import psycopg2
import psycopg2.extras
from kafka import KafkaProducer
from langchain_cohere import ChatCohere
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.celery_app import celery_app
from app.config import get_settings

logger = logging.getLogger(__name__)

# Register UUID adapter so psycopg2 returns uuid.UUID objects
psycopg2.extras.register_uuid()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_pgvector(vec_str: str) -> list[float]:
    """Convert pgvector string '[0.1,0.2,...]' to List[float]."""
    return json.loads(vec_str)


def _to_pgvector(embedding: np.ndarray | list[float]) -> str:
    """Convert a numpy array or list to pgvector literal '[f1,f2,...]'."""
    if isinstance(embedding, np.ndarray):
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D numpy arrays."""
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _extract_keywords(headlines: list[str], top_n: int = 10) -> list[str]:
    """
    Extract the top N most-frequent non-stopword tokens from a list of headlines.
    Pure Python — no NLP library required. Good enough for keyword extraction
    from a small set of structured news headlines.
    """
    STOP_WORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "is", "was", "are", "were", "be", "been",
        "has", "have", "had", "it", "its", "as", "by", "from", "that",
        "this", "they", "their", "will", "says", "say", "said", "after",
        "new", "over", "up", "out", "into", "than", "more", "about",
    }
    word_counts: dict[str, int] = {}
    for headline in headlines:
        for word in headline.lower().split():
            token = word.strip(".,!?;:\"'()-")
            if token and token not in STOP_WORDS and len(token) > 2:
                word_counts[token] = word_counts.get(token, 0) + 1

    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]


@dataclass
class _ArticleRow:
    id: str
    embedding: np.ndarray
    headline: str


@dataclass
class _SubThemeData:
    label: int                            # HDBSCAN cluster label (0..N)
    members: list[_ArticleRow] = field(default_factory=list)
    centroid: np.ndarray | None = None
    representative_article_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    reddit_post_ids: list[str] = field(default_factory=list)
    reddit_post_count: int = 0
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    # Set during Step 4
    sub_theme_id: str | None = None
    is_new: bool = True
    should_relabel: bool = True
    label_text: str | None = None
    description_text: str | None = None
    status: str = "emerging"
    events: list[str] = field(default_factory=list)
    snapshot_id: str | None = None


# ── Cohere LLM labeling ───────────────────────────────────────────────────────

def _call_cohere_label(
    cohere_client: ChatCohere,
    topic_name: str,
    keywords: list[str],
    sample_headlines: list[str],
    gdelt_count: int,
    reddit_count: int,
    sentiment_label: str | None,
    sentiment_score: float | None,
) -> tuple[str | None, str | None]:
    """
    Call LangChain + Cohere to generate a sub-theme label + description.
    Returns (label, description). Returns (None, None) on failure — the
    sub-theme row is stored without a label; next run retries automatically.
    """
    prompt = f"""You are an analyst identifying emerging themes in news coverage.

Topic: {topic_name}
Sub-theme keywords: {", ".join(keywords)}
Sample headlines:
{chr(10).join(f"- {h}" for h in sample_headlines[:5])}

Article volume: {gdelt_count} news articles, {reddit_count} Reddit posts
Sentiment: {sentiment_label or "unknown"} (score: {sentiment_score if sentiment_score is not None else "N/A"})

Task:
1. Write a short label (3-6 words) for this sub-theme
2. Write a 1-2 sentence description explaining what this sub-theme is about

Return a JSON object with keys "label" and "description".
Return only the JSON. No preamble, no explanation."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = cohere_client.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            result = json.loads(content.strip())
            return result.get("label"), result.get("description")
        except Exception as exc:
            logger.warning("Cohere labeling attempt %d/%d failed: %s", attempt + 1, max_retries, exc)
            if attempt == max_retries - 1:
                logger.error("Cohere labeling permanently failed for topic %s — storing without label", topic_name)
                return None, None
    return None, None


# ── Main Celery task ──────────────────────────────────────────────────────────

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

    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    cohere_client = ChatCohere(
        model="command-r-08-2024",
        cohere_api_key=settings.cohere_api_key,
    )

    vader = SentimentIntensityAnalyzer()

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name FROM topics WHERE is_active = TRUE")
        topics = cur.fetchall()

        logger.info("Sub-theme discovery: processing %d active topics.", len(topics))

        for topic_row in topics:
            topic_id = str(topic_row["id"])
            topic_name = topic_row["name"]
            try:
                _process_topic(
                    conn=conn,
                    producer=producer,
                    cohere_client=cohere_client,
                    vader=vader,
                    topic_id=topic_id,
                    topic_name=topic_name,
                    settings=settings,
                )
            except Exception as exc:
                conn.rollback()
                logger.error("Topic %s (%s) failed — skipping: %s", topic_id, topic_name, exc)

        logger.info("Sub-theme discovery complete.")

    finally:
        try:
            producer.flush()
            producer.close()
        except Exception:
            pass
        conn.close()


# ── Per-topic logic ───────────────────────────────────────────────────────────

def _process_topic(
    conn: Any,
    producer: KafkaProducer,
    cohere_client: ChatCohere,
    vader: SentimentIntensityAnalyzer,
    topic_id: str,
    topic_name: str,
    settings: Any,
) -> None:
    """Run the full discovery pipeline for a single topic."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── Guard: minimum GDELT article count ────────────────────────────────────
    cur.execute("""
        SELECT a.id, a.embedding::text, a.headline
        FROM article_topic_matches atm
        JOIN articles a ON atm.article_id = a.id
        JOIN sources  s ON a.source_id    = s.id
        WHERE atm.topic_id  = %s
          AND s.type        = 'gdelt'
          AND a.crawled_at  >= NOW() - INTERVAL '%s days'
          AND a.embedding IS NOT NULL
    """, (topic_id, settings.subtheme_window_days))
    gdelt_rows = cur.fetchall()

    if len(gdelt_rows) < settings.subtheme_min_articles:
        logger.info(
            "Topic %s: only %d GDELT articles in window — skipping (min: %d).",
            topic_id, len(gdelt_rows), settings.subtheme_min_articles,
        )
        return

    # Parse article data
    gdelt_articles = [
        _ArticleRow(
            id=str(row["id"]),
            embedding=np.array(_parse_pgvector(row["embedding"])),
            headline=row["headline"],
        )
        for row in gdelt_rows
    ]

    # ── Step 1: HDBSCAN clustering ────────────────────────────────────────────
    sub_theme_data = _step1_cluster(gdelt_articles, settings)
    if not sub_theme_data:
        logger.info("Topic %s: no valid clusters found — skipping.", topic_id)
        return

    logger.info("Topic %s: found %d sub-theme cluster(s).", topic_id, len(sub_theme_data))

    # ── Step 2: Reddit assignment ─────────────────────────────────────────────
    _step2_assign_reddit(cur, conn, topic_id, sub_theme_data, settings)

    # ── Step 3: VADER sentiment from pre-stored comments ─────────────────────
    _step3_sentiment(cur, sub_theme_data, vader)

    # ── Step 4: LLM labeling ─────────────────────────────────────────────────
    _step4_label(cur, topic_id, topic_name, sub_theme_data, cohere_client, settings)

    # ── Step 5: Evolution detection ───────────────────────────────────────────
    _step5_evolution(cur, sub_theme_data, settings)

    # ── Step 6: Persist ───────────────────────────────────────────────────────
    _step6_persist(cur, conn, topic_id, sub_theme_data)

    # ── Step 7: Publish to Kafka ──────────────────────────────────────────────
    _step7_publish(cur, producer, topic_id, sub_theme_data)

    conn.commit()
    logger.info("Topic %s: discovery committed successfully.", topic_id)


def _step1_cluster(
    gdelt_articles: list[_ArticleRow],
    settings: Any,
) -> list[_SubThemeData]:
    """
    HDBSCAN clustering of GDELT article embeddings.
    Returns one _SubThemeData per valid cluster (noise label -1 is discarded).
    """
    embeddings = np.array([a.embedding for a in gdelt_articles])

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=settings.subtheme_min_cluster_size,
        min_samples=settings.subtheme_min_samples,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(embeddings)

    # Group articles by cluster label
    raw_clusters: dict[int, list[_ArticleRow]] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue  # noise — not assigned to any sub-theme
        raw_clusters.setdefault(label, []).append(gdelt_articles[i])

    result: list[_SubThemeData] = []

    for label, members in raw_clusters.items():
        member_embeddings = np.array([a.embedding for a in members])
        centroid = member_embeddings.mean(axis=0)

        # Representative article: closest to centroid
        sims = [_cosine_similarity(a.embedding, centroid) for a in members]
        representative = members[int(np.argmax(sims))]

        keywords = _extract_keywords([a.headline for a in members], top_n=10)

        sub_theme = _SubThemeData(label=label)
        sub_theme.members = members
        sub_theme.centroid = centroid
        sub_theme.representative_article_id = representative.id
        sub_theme.keywords = keywords
        result.append(sub_theme)

    return result


def _step2_assign_reddit(
    cur: Any,
    conn: Any,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
    settings: Any,
) -> None:
    """
    Assign Reddit posts to their nearest existing sub-theme centroid using
    pgvector ANN. Only posts with similarity >= SUBTHEME_REDDIT_ASSIGN_THRESHOLD
    are assigned.

    Note: Uses centroids computed in Step 1 (in memory, not yet in DB).
    We do an in-Python centroid search since sub_themes haven't been persisted yet.
    """
    cur.execute("""
        SELECT a.id, a.embedding::text
        FROM article_topic_matches atm
        JOIN articles a ON atm.article_id = a.id
        JOIN sources  s ON a.source_id    = s.id
        WHERE atm.topic_id  = %s
          AND s.type        = 'reddit'
          AND a.crawled_at  >= NOW() - INTERVAL '%s days'
          AND a.embedding IS NOT NULL
    """, (topic_id, settings.subtheme_window_days))
    reddit_rows = cur.fetchall()

    if not reddit_rows:
        return

    threshold = settings.subtheme_reddit_assign_threshold

    for reddit_row in reddit_rows:
        post_id = str(reddit_row["id"])
        post_embedding = np.array(_parse_pgvector(reddit_row["embedding"]))

        # Find nearest cluster centroid (in-memory, since Step 6 hasn't persisted yet)
        best_sim = -1.0
        best_idx = -1
        for idx, st in enumerate(sub_theme_data):
            if st.centroid is None:
                continue
            sim = _cosine_similarity(post_embedding, st.centroid)
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_idx >= 0 and best_sim >= threshold:
            sub_theme_data[best_idx].reddit_post_ids.append(post_id)
            sub_theme_data[best_idx].reddit_post_count += 1


def _step3_sentiment(
    cur: Any,
    sub_theme_data: list[_SubThemeData],
    vader: SentimentIntensityAnalyzer,
) -> None:
    """
    VADER sentiment analysis over pre-stored Reddit comments.
    Comments are already in the reddit_comments table (stored by teammates).
    Weighted by comment upvote score — higher-scored comments carry more weight.
    """
    for st in sub_theme_data:
        if not st.reddit_post_ids:
            st.sentiment_score = None
            st.sentiment_label = None
            continue

        cur.execute("""
            SELECT body, score FROM reddit_comments
            WHERE article_id = ANY(%s)
        """, (st.reddit_post_ids,))
        comments = cur.fetchall()

        if not comments:
            st.sentiment_score = None
            st.sentiment_label = None
            continue

        total_weight = 0.0
        weighted_sum = 0.0
        for comment_row in comments:
            compound = vader.polarity_scores(comment_row["body"])["compound"]
            weight = max(comment_row["score"], 1)
            weighted_sum += compound * weight
            total_weight += weight

        score = weighted_sum / total_weight if total_weight > 0 else None

        if score is None:
            st.sentiment_score = None
            st.sentiment_label = None
        elif score >= 0.05:
            st.sentiment_score = round(score, 4)
            st.sentiment_label = "positive"
        elif score <= -0.05:
            st.sentiment_score = round(score, 4)
            st.sentiment_label = "negative"
        else:
            st.sentiment_score = round(score, 4)
            st.sentiment_label = "neutral"


def _step4_label(
    cur: Any,
    topic_id: str,
    topic_name: str,
    sub_theme_data: list[_SubThemeData],
    cohere_client: ChatCohere,
    settings: Any,
) -> None:
    """
    For each discovered cluster:
    - Match to an existing sub_themes row via centroid similarity (pgvector)
    - If new: INSERT later (Step 6) and call LLM for label
    - If existing: UPDATE; call LLM only if volume changed significantly

    Sets sub_theme.is_new, sub_theme_id, should_relabel, label_text, description_text.
    """
    relabel_threshold = settings.subtheme_relabel_volume_change_threshold

    for st in sub_theme_data:
        centroid_vec = _to_pgvector(st.centroid)
        gdelt_count = len(st.members)
        current_volume = gdelt_count + st.reddit_post_count

        # Look for a close existing sub_theme via pgvector
        cur.execute("""
            SELECT st.id,
                   st.label,
                   st.description,
                   st.label_generated_at,
                   (SELECT total_volume FROM sub_theme_snapshots
                    WHERE sub_theme_id = st.id
                    ORDER BY snapshot_at DESC LIMIT 1) AS last_volume
            FROM sub_themes st
            WHERE st.topic_id = %s
              AND st.status  != 'inactive'
              AND 1 - (st.centroid <=> %s::vector) >= %s
            ORDER BY st.centroid <=> %s::vector
            LIMIT 1
        """, (topic_id, centroid_vec, settings.subtheme_centroid_match_threshold, centroid_vec))
        existing = cur.fetchone()

        if existing is None:
            # Brand new sub-theme
            st.is_new = True
            st.sub_theme_id = None
            st.should_relabel = True
        else:
            st.is_new = False
            st.sub_theme_id = str(existing["id"])
            last_volume = existing["last_volume"] or 0
            volume_change = abs(current_volume - last_volume) / max(last_volume, 1)
            st.should_relabel = (
                existing["label_generated_at"] is None
                or volume_change >= relabel_threshold
            )
            # Keep existing label/description as fallback
            st.label_text = existing["label"]
            st.description_text = existing["description"]

        if st.should_relabel:
            new_label, new_desc = _call_cohere_label(
                cohere_client=cohere_client,
                topic_name=topic_name,
                keywords=st.keywords,
                sample_headlines=[a.headline for a in st.members],
                gdelt_count=gdelt_count,
                reddit_count=st.reddit_post_count,
                sentiment_label=st.sentiment_label,
                sentiment_score=st.sentiment_score,
            )
            st.label_text = new_label
            st.description_text = new_desc


def _step5_evolution(
    cur: Any,
    sub_theme_data: list[_SubThemeData],
    settings: Any,
) -> None:
    """
    Compare each sub-theme's current state to its previous snapshot.
    Populates st.events and st.status.
    """
    for st in sub_theme_data:
        current_volume = len(st.members) + st.reddit_post_count
        events: list[str] = []

        if st.is_new or st.sub_theme_id is None:
            # No previous snapshot — this is brand new
            events.append("sub_theme_emerging")
            st.status = "emerging"
            st.events = events
            continue

        # Fetch previous snapshot
        cur.execute("""
            SELECT total_volume, sentiment_score
            FROM sub_theme_snapshots
            WHERE sub_theme_id = %s
            ORDER BY snapshot_at DESC LIMIT 1
        """, (st.sub_theme_id,))
        prev = cur.fetchone()

        if prev is None:
            events.append("sub_theme_emerging")
            st.status = "emerging"
            st.events = events
            continue

        prev_volume = prev["total_volume"] or 0
        volume_delta = (current_volume - prev_volume) / max(prev_volume, 1)

        # Growing?
        if volume_delta >= settings.subtheme_growing_threshold:
            events.append("sub_theme_growing")

        # Disappearing? Compare against peak historical volume
        cur.execute(
            "SELECT MAX(total_volume) FROM sub_theme_snapshots WHERE sub_theme_id = %s",
            (st.sub_theme_id,),
        )
        peak_row = cur.fetchone()
        peak_volume = (peak_row[0] if peak_row and peak_row[0] else 0) or current_volume

        if peak_volume > 0 and current_volume / max(peak_volume, 1) <= settings.subtheme_disappearing_threshold:
            events.append("sub_theme_disappearing")

        # Sentiment shift?
        if st.sentiment_score is not None:
            cur.execute("""
                SELECT AVG(sentiment_score) FROM sub_theme_snapshots
                WHERE sub_theme_id = %s
                  AND sentiment_score IS NOT NULL
                  AND snapshot_at >= NOW() - INTERVAL '%s days'
            """, (st.sub_theme_id, settings.subtheme_baseline_days))
            baseline_row = cur.fetchone()
            baseline = baseline_row[0] if baseline_row and baseline_row[0] is not None else None

            if (baseline is not None
                    and abs(st.sentiment_score - baseline) >= settings.subtheme_sentiment_shift_threshold):
                events.append("sub_theme_sentiment_shift")

        # Determine status
        if "sub_theme_disappearing" in events:
            st.status = "inactive"
        elif "sub_theme_growing" in events:
            st.status = "active"
        elif volume_delta < 0:
            st.status = "declining"
        else:
            st.status = "active"

        st.events = events


def _step6_persist(
    cur: Any,
    conn: Any,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
) -> None:
    """
    Write sub_themes (UPSERT), sub_theme_memberships (DELETE+INSERT), and
    sub_theme_snapshots (INSERT) to PostgreSQL.
    Materialises sub_theme_id and snapshot_id on each _SubThemeData object.
    """
    for st in sub_theme_data:
        centroid_vec = _to_pgvector(st.centroid)
        gdelt_count = len(st.members)
        current_volume = gdelt_count + st.reddit_post_count

        if st.is_new:
            # INSERT new sub_theme row
            cur.execute("""
                INSERT INTO sub_themes
                    (topic_id, label, description, keywords, centroid,
                     representative_article_id, status,
                     label_generated_at)
                VALUES (%s, %s, %s, %s, %s::vector, %s, %s,
                        CASE WHEN %s IS NOT NULL THEN NOW() ELSE NULL END)
                RETURNING id
            """, (
                topic_id,
                st.label_text,
                st.description_text,
                st.keywords,
                centroid_vec,
                st.representative_article_id,
                st.status,
                st.label_text,   # for the CASE expression
            ))
            st.sub_theme_id = str(cur.fetchone()[0])
        else:
            # UPDATE existing sub_theme row
            cur.execute("""
                UPDATE sub_themes SET
                    centroid    = %s::vector,
                    last_seen_at = NOW(),
                    status      = %s,
                    representative_article_id = %s,
                    keywords    = %s,
                    label       = COALESCE(%s, label),
                    description = COALESCE(%s, description),
                    label_generated_at = CASE
                        WHEN %s IS NOT NULL THEN NOW()
                        ELSE label_generated_at
                    END
                WHERE id = %s
            """, (
                centroid_vec,
                st.status,
                st.representative_article_id,
                st.keywords,
                st.label_text if st.should_relabel else None,
                st.description_text if st.should_relabel else None,
                st.label_text if st.should_relabel else None,  # CASE check
                st.sub_theme_id,
            ))

        # Memberships: DELETE all for this sub_theme, then re-INSERT
        cur.execute(
            "DELETE FROM sub_theme_memberships WHERE sub_theme_id = %s",
            (st.sub_theme_id,),
        )

        # GDELT members
        if st.members:
            gdelt_values = []
            for article in st.members:
                centroid_arr = st.centroid
                sim = _cosine_similarity(article.embedding, centroid_arr)
                gdelt_values.append((st.sub_theme_id, article.id, "gdelt", float(sim)))

            psycopg2.extras.execute_values(cur, """
                INSERT INTO sub_theme_memberships
                    (sub_theme_id, article_id, membership_type, similarity_to_centroid)
                VALUES %s
                ON CONFLICT (sub_theme_id, article_id) DO NOTHING
            """, gdelt_values)

        # Reddit members
        if st.reddit_post_ids:
            reddit_values = [
                (st.sub_theme_id, post_id, "reddit", None)
                for post_id in st.reddit_post_ids
            ]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO sub_theme_memberships
                    (sub_theme_id, article_id, membership_type, similarity_to_centroid)
                VALUES %s
                ON CONFLICT (sub_theme_id, article_id) DO NOTHING
            """, reddit_values)

        # Snapshot
        cur.execute("""
            INSERT INTO sub_theme_snapshots
                (sub_theme_id, topic_id, gdelt_article_count, reddit_post_count,
                 total_volume, sentiment_score, sentiment_label, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            st.sub_theme_id,
            topic_id,
            gdelt_count,
            st.reddit_post_count,
            current_volume,
            st.sentiment_score,
            st.sentiment_label,
            st.status,
        ))
        st.snapshot_id = str(cur.fetchone()[0])


def _step7_publish(
    cur: Any,
    producer: KafkaProducer,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
) -> None:
    """
    Publish one Kafka message to sub-theme-events per (event, user).
    Only publishes when evolution events were detected.
    """
    # Fetch all users who own this topic
    cur.execute(
        "SELECT user_id FROM topics WHERE id = %s AND is_active = TRUE",
        (topic_id,),
    )
    user_rows = cur.fetchall()
    if not user_rows:
        return

    for st in sub_theme_data:
        if not st.events:
            continue  # no state change — no alert

        for event_type in st.events:
            for user_row in user_rows:
                user_id = str(user_row["user_id"])
                producer.send("sub-theme-events", {
                    "event_type": event_type,
                    "sub_theme_id": st.sub_theme_id,
                    "sub_theme_snapshot_id": st.snapshot_id,
                    "topic_id": topic_id,
                    "user_id": user_id,
                })

    logger.info(
        "Topic %s: published %d event(s) to sub-theme-events.",
        topic_id,
        sum(len(st.events) for st in sub_theme_data),
    )
