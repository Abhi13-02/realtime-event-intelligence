import psycopg2
import psycopg2.extras  # For UUID support
from typing import List
from uuid import UUID

from app.pipeline.interfaces import DatabaseInterface
from app.pipeline.models import ProcessedArticle, ScoredMatch
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

    def close(self):
        self.conn.close()
