import json
import psycopg2
import psycopg2.extras  # For UUID support
from typing import List
from uuid import UUID

from app.pipeline.interfaces import DatabaseInterface
from app.pipeline.models import ProcessedArticle, RawArticle, ScoredMatch, Topic
from app.pipeline.exceptions import DatabaseConnectionError

# Register UUID type adapter so psycopg2 returns uuid.UUID objects properly
psycopg2.extras.register_uuid()


class PostgresAdapter(DatabaseInterface):
    """
    Concrete PostgreSQL adapter that implements all DatabaseInterface methods.
    Uses pgvector for ANN (approximate nearest neighbor) search.
    """

    def __init__(self, connection_string: str):
        try:
            self.conn = psycopg2.connect(connection_string)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to connect to PostgreSQL: {e}")

    def check_url_exists(self, url: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM articles WHERE url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None

    def vector_search_duplicate(self, embedding: List[float], threshold: float = 0.95) -> bool:
        """
        pgvector cosine distance (<=>): distance = 1 - similarity.
        Duplicate if similarity >= threshold (i.e., distance <= 1 - threshold).
        """
        with self.conn.cursor() as cur:
            vec_str = f"[{','.join(str(f) for f in embedding)}]"
            cur.execute("""
                SELECT 1 FROM articles
                WHERE embedding <=> %s::vector <= %s
                LIMIT 1
            """, (vec_str, 1.0 - threshold))
            return cur.fetchone() is not None

    def get_source_credibility(self, source_id: UUID) -> float:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT credibility_score FROM sources WHERE id = %s",
                (str(source_id),)
            )
            res = cur.fetchone()
            return float(res[0]) if res else 0.5

    def store_article_and_matches(self, article: ProcessedArticle, matches: List[ScoredMatch]) -> UUID:
        vec_str = f"[{','.join(str(f) for f in article.embedding)}]" if article.embedding else None
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO articles
                        (source_id, url, headline, content, embedding, pipeline_status, published_at)
                    VALUES (%s, %s, %s, %s, %s::vector, 'passed_dedup', %s)
                    RETURNING id
                """, (
                    str(article.raw.source_id),
                    str(article.raw.url),
                    article.raw.headline,
                    article.clean_text,
                    vec_str,
                    article.raw.published_at,
                ))
                new_id = cur.fetchone()[0]   # psycopg2 returns uuid.UUID if register_uuid() called

                if matches:
                    values_template = ",".join(["(%s, %s, %s, %s)"] * len(matches))
                    args = []
                    for m in matches:
                        args.extend([str(new_id), str(m.topic_id), m.relevance_score, m.credibility_score])
                    cur.execute(f"""
                        INSERT INTO article_topic_matches
                            (article_id, topic_id, relevance_score, credibility_score)
                        VALUES {values_template}
                    """, args)

                self.conn.commit()
                return UUID(str(new_id))   # Ensure we always return uuid.UUID

        except Exception as e:
            self.conn.rollback()
            raise DatabaseConnectionError(f"Failed to store article: {e}")

    def update_article_summary(self, article_id: UUID, summary: str) -> None:
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE articles
                    SET summary = %s, pipeline_status = 'processed'
                    WHERE id = %s
                """, (summary, str(article_id)))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise DatabaseConnectionError(f"Failed to update summary: {e}")

    def get_users_meeting_threshold(self, topic_id: UUID, relevance_score: float) -> List[UUID]:
        """
        Returns user IDs who own this topic AND the topic threshold is <= relevance_score.
        Schema: topics.user_id, topics.threshold, topics.is_active
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT user_id FROM topics
                WHERE id = %s
                  AND is_active = TRUE
                  AND threshold <= %s
            """, (str(topic_id), relevance_score))
            rows = cur.fetchall()
            return [UUID(str(r[0])) for r in rows]

    def get_pending_summary_articles(self) -> List[dict]:
        """
        Fetch all articles stuck at pipeline_status='passed_dedup' with summary=NULL.
        These are articles that passed dedup + topic matching (Stages 0-4) but whose
        summarisation (Stage 5) failed permanently before the process was killed.

        Returns a list of dicts, each containing:
          - processed_article: ProcessedArticle reconstructed from DB
          - scored_matches: List[ScoredMatch] from article_topic_matches

        Grouped by article so each article appears once with all its matches.
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.source_id, a.url, a.headline, a.content,
                       a.embedding, a.published_at,
                       atm.topic_id, atm.relevance_score, atm.credibility_score
                FROM articles a
                JOIN article_topic_matches atm ON atm.article_id = a.id
                WHERE a.pipeline_status = 'passed_dedup'
                  AND a.summary IS NULL
                ORDER BY a.id
            """)
            rows = cur.fetchall()

        # Group rows by article_id — each article can have multiple topic matches
        articles: dict = {}
        for row in rows:
            article_id = row[0]
            if article_id not in articles:
                raw = RawArticle(
                    url=str(row[2]),
                    headline=row[3],
                    content=row[4] or "",
                    source_id=row[1],
                    published_at=row[6],
                )
                processed = ProcessedArticle(
                    raw=raw,
                    clean_text=row[4] or "",
                    # embedding stored as string in pgvector — parse back to List[float]
                    embedding=json.loads(row[5]) if row[5] else None,
                    id=article_id,
                )
                articles[article_id] = {
                    "processed_article": processed,
                    "scored_matches": [],
                }
            articles[article_id]["scored_matches"].append(
                ScoredMatch(
                    topic_id=row[7],
                    relevance_score=row[8],
                    credibility_score=row[9],
                )
            )

        return list(articles.values())

    def get_active_topics(self) -> List[Topic]:
        """
        Load all active topics with embeddings from the DB.
        Called by the consumer on startup and every 5 minutes to refresh
        the pipeline's in-memory topic cache.
        pgvector returns embeddings as a string e.g. "[0.1,0.2,...]" —
        json.loads() converts it to List[float].
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, name, sensitivity, embedding
                FROM topics
                WHERE is_active = TRUE AND embedding IS NOT NULL
            """)
            rows = cur.fetchall()
        return [
            Topic(
                id=row[0],
                user_id=row[1],
                name=row[2],
                sensitivity=row[3],
                embedding=json.loads(row[4]),
            )
            for row in rows
        ]

    def close(self):
        self.conn.close()
