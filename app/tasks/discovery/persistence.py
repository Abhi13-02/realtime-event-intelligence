import logging
from datetime import datetime
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
    run_at: datetime,
) -> None:
    """
    Step 6: Write sub_themes (UPSERT), sub_theme_memberships (append) and
    sub_theme_snapshots (INSERT) to PostgreSQL.

    run_at identifies this discovery run and is stamped on every row written
    here. It is passed in rather than defaulted to NOW() per statement: a "run"
    is the set of rows sharing this timestamp, and the timeline, the history
    endpoint and the membership lookups all depend on that grouping being exact.
    It previously worked only because NOW() is transaction-start time in
    Postgres and everything happened to share one transaction — load-bearing
    behaviour that was never written down.
    """
    for st in sub_theme_data:
        # Skip clusters that were merged into other clusters during labeling
        if st.sub_theme_id == "__merged__":
            continue

        centroid_vec = _to_pgvector(st.centroid)
        # Members were already pruned by the similarity guard in step 4, so these
        # are the final counts — the same ones evolution classified status from.
        article_count = len(st.members)
        current_volume = st.volume

        if st.is_new:
            cur.execute("""
                INSERT INTO sub_themes
                    (topic_id, label, description, keywords, centroid,
                     representative_article_id, status,
                     label_generated_at, volume_at_last_label)
                VALUES (%s, %s, %s, %s, %s::vector, %s, %s,
                        CASE WHEN %s IS NOT NULL THEN NOW() ELSE NULL END,
                        %s)
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
                current_volume if st.label_text else 0,
            ))
            st.sub_theme_id = str(cur.fetchone()["id"])
        else:
            # FROZEN CENTROID: We do NOT update the 'centroid' column for existing themes.
            # This prevents semantic drift over time.
            cur.execute("""
                UPDATE sub_themes SET
                    last_seen_at = NOW(),
                    status      = %s,
                    representative_article_id = %s,
                    keywords    = %s,
                    label       = COALESCE(%s, label),
                    description = COALESCE(%s, description),
                    label_generated_at = CASE
                        WHEN %s IS NOT NULL THEN NOW()
                        ELSE label_generated_at
                    END,
                    volume_at_last_label = CASE
                        WHEN %s IS NOT NULL THEN %s
                        ELSE volume_at_last_label
                    END
                WHERE id = %s
            """, (
                st.status,
                st.representative_article_id,
                st.keywords,
                st.label_text if st.should_relabel else None,
                st.description_text if st.should_relabel else None,
                st.label_text if st.should_relabel else None,
                st.label_text if st.should_relabel else None,
                current_volume,
                st.sub_theme_id,
            ))

        # APPEND-ONLY: memberships used to be deleted and rewritten every run,
        # which destroyed the history. Each run now writes its own generation,
        # stamped with the same run_at the snapshot carries, so "which articles
        # were in this cluster at that point on the graph" is answerable — and a
        # sunsetted cluster keeps the evidence it had when it died.
        if st.members:
            # No filtering here — the similarity guard already ran in step 4.
            # We only recompute the score so it can be stored for relevance ranking.
            news_values = [
                (
                    st.sub_theme_id,
                    article.id,
                    "news",
                    float(_cosine_similarity(article.embedding, st.centroid)),
                    run_at,
                )
                for article in st.members
            ]

            psycopg2.extras.execute_values(cur, """
                INSERT INTO sub_theme_memberships
                    (sub_theme_id, article_id, membership_type,
                     similarity_to_centroid, run_at)
                VALUES %s
                ON CONFLICT (sub_theme_id, article_id, run_at) DO NOTHING
            """, news_values)

        if st.reddit_post_ids:
            reddit_values = [
                (st.sub_theme_id, post_id, "reddit", None, run_at)
                for post_id in st.reddit_post_ids
            ]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO sub_theme_memberships
                    (sub_theme_id, article_id, membership_type,
                     similarity_to_centroid, run_at)
                VALUES %s
                ON CONFLICT (sub_theme_id, article_id, run_at) DO NOTHING
            """, reddit_values)

        # The snapshot is written to be self-describing: prev_volume and
        # growth_pct come straight from the classification in step 5, so the API
        # reads them rather than recomputing growth at request time and risking a
        # different answer. representative_article_id and keywords are recorded
        # here too, so replaying an old run shows that run's headline and terms
        # instead of today's.
        cur.execute("""
            INSERT INTO sub_theme_snapshots
                (sub_theme_id, topic_id, article_count, reddit_post_count,
                 total_volume, sentiment_score, status, label, description,
                 prev_volume, growth_pct, representative_article_id, keywords,
                 snapshot_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            st.prev_volume,
            st.growth_pct,
            st.representative_article_id,
            st.keywords,
            run_at,
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
