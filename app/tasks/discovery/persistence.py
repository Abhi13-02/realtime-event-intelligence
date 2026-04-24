import logging
import json
from typing import Any
import psycopg2.extras
from kafka import KafkaProducer
from .models import _SubThemeData, _to_pgvector, _cosine_similarity

logger = logging.getLogger(__name__)

def _step6_persist(
    cur: Any,
    conn: Any,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
) -> None:
    """
    Step 6: Write sub_themes (UPSERT), sub_theme_memberships (DELETE+INSERT), and
    sub_theme_snapshots (INSERT) to PostgreSQL.
    """
    for st in sub_theme_data:
        centroid_vec = _to_pgvector(st.centroid)
        article_count = len(st.members)
        current_volume = article_count + st.reddit_post_count

        if st.is_new:
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
                st.label_text,
            ))
            st.sub_theme_id = str(cur.fetchone()["id"])
        else:
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
                st.label_text if st.should_relabel else None,
                st.sub_theme_id,
            ))

        cur.execute(
            "DELETE FROM sub_theme_memberships WHERE sub_theme_id = %s",
            (st.sub_theme_id,),
        )

        if st.members:
            news_values = []
            for article in st.members:
                centroid_arr = st.centroid
                sim = _cosine_similarity(article.embedding, centroid_arr)
                news_values.append((st.sub_theme_id, article.id, "news", float(sim)))

            psycopg2.extras.execute_values(cur, """
                INSERT INTO sub_theme_memberships
                    (sub_theme_id, article_id, membership_type, similarity_to_centroid)
                VALUES %s
                ON CONFLICT (sub_theme_id, article_id) DO NOTHING
            """, news_values)

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

        cur.execute("""
            INSERT INTO sub_theme_snapshots
                (sub_theme_id, topic_id, article_count, reddit_post_count,
                 total_volume, sentiment_score, status, label, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            st.sub_theme_id,
            topic_id,
            article_count,
            st.reddit_post_count,
            current_volume,
            st.sentiment_score,
            st.status,
            st.label_text,
            st.description_text,
        ))
        st.snapshot_id = str(cur.fetchone()["id"])

def _step7_publish(
    cur: Any,
    producer: KafkaProducer,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
) -> None:
    """
    Step 7: Publish evolution events to Kafka.
    """
    cur.execute(
        "SELECT user_id FROM topics WHERE id = %s::uuid AND is_active = TRUE",
        (topic_id,),
    )
    user_rows = cur.fetchall()
    if not user_rows:
        return

    for st in sub_theme_data:
        if not st.events:
            continue

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
