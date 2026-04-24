import json
import logging
import functools
import psycopg2
import psycopg2.extras  # For UUID support
from typing import List
from uuid import UUID

from app.pipeline.interfaces import DatabaseInterface
from app.pipeline.models import ProcessedArticle, RawArticle, ScoredMatch, Topic
from app.pipeline.exceptions import DatabaseConnectionError

# Register UUID type adapter so psycopg2 returns uuid.UUID objects properly
psycopg2.extras.register_uuid()

logger = logging.getLogger(__name__)


def _with_reconnect(method):
    """On OperationalError (dead connection), reconnect once and retry."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except psycopg2.OperationalError:
            logger.warning("DB connection lost — reconnecting and retrying %s", method.__name__)
            self._reconnect()
            return method(self, *args, **kwargs)
    return wrapper


class PostgresAdapter(DatabaseInterface):
    """
    Concrete PostgreSQL adapter that implements all DatabaseInterface methods.
    Uses pgvector for ANN (approximate nearest neighbor) search.
    """

    def __init__(self, connection_string: str):
        self._connection_string = connection_string
        try:
            self.conn = psycopg2.connect(connection_string)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to connect to PostgreSQL: {e}")

    def _reconnect(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = psycopg2.connect(self._connection_string)

    @_with_reconnect
    def check_url_exists(self, url: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM articles WHERE url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None

    @_with_reconnect
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

    @_with_reconnect
    def get_source_credibility(self, source_id: UUID) -> float:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT credibility_score FROM sources WHERE id = %s",
                (str(source_id),)
            )
            res = cur.fetchone()
            return float(res[0]) if res else 0.5

    @_with_reconnect
    def store_article_and_matches(self, article: ProcessedArticle, matches: List[ScoredMatch]) -> UUID:
        vec_str = f"[{','.join(str(f) for f in article.embedding)}]" if article.embedding else None
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO articles
                        (source_id, url, headline, content, embedding, pipeline_status, published_at, image_url)
                    VALUES (%s, %s, %s, %s, %s::vector, 'passed_dedup', %s, %s)
                    RETURNING id
                """, (
                    str(article.raw.source_id),
                    str(article.raw.url),
                    article.raw.headline,
                    article.clean_text,
                    vec_str,
                    article.raw.published_at,
                    article.raw.image_url,
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

        except psycopg2.OperationalError:
            self.conn.rollback()
            raise  # propagate to decorator for reconnect
        except Exception as e:
            self.conn.rollback()
            raise DatabaseConnectionError(f"Failed to store article: {e}")

    @_with_reconnect
    def update_article_summary(self, article_id: UUID, summary: str) -> None:
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE articles
                    SET summary = %s, pipeline_status = 'processed'
                    WHERE id = %s
                """, (summary, str(article_id)))
            self.conn.commit()
        except psycopg2.OperationalError:
            self.conn.rollback()
            raise  # propagate to decorator for reconnect
        except Exception as e:
            self.conn.rollback()
            raise DatabaseConnectionError(f"Failed to update summary: {e}")

    @_with_reconnect
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
                  AND a.source_id != 'a1b2c3d4-0006-0006-0006-000000000006'
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

    @_with_reconnect
    def get_active_topics(self) -> List[Topic]:
        """
        Load all active topics with their parent and subtopic embeddings from the DB.
        Called by the consumer on startup and every 5 minutes to refresh the cache.

        LEFT JOIN topic_subtopics: a topic with no subtopic rows (created before the
        upgrade and not yet recreated) still appears — subtopic_embeddings will be []
        and Stage 2 falls back to the parent embedding alone.

        pgvector returns embeddings as strings e.g. "[0.1,0.2,...]";
        json.loads() converts each to List[float].
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.user_id, t.name, t.sensitivity,
                       t.embedding          AS parent_embedding,
                       ts.embedding         AS sub_embedding
                FROM topics t
                LEFT JOIN topic_subtopics ts ON ts.topic_id = t.id
                WHERE t.is_active = TRUE AND t.embedding IS NOT NULL
                ORDER BY t.id
            """)
            rows = cur.fetchall()

        # Group rows by topic_id — one row per subtopic, so each topic appears N times.
        topics_map: dict = {}
        for row in rows:
            topic_id = row[0]
            if topic_id not in topics_map:
                topics_map[topic_id] = {
                    "id":               row[0],
                    "user_id":          row[1],
                    "name":             row[2],
                    "sensitivity":      row[3],
                    "parent_embedding": json.loads(row[4]),
                    "subtopic_embeddings": [],
                }
            if row[5] is not None:
                topics_map[topic_id]["subtopic_embeddings"].append(json.loads(row[5]))

        return [
            Topic(
                id=d["id"],
                user_id=d["user_id"],
                name=d["name"],
                sensitivity=d["sensitivity"],
                parent_embedding=d["parent_embedding"],
                subtopic_embeddings=d["subtopic_embeddings"],
            )
            for d in topics_map.values()
        ]

    def close(self):
        self.conn.close()
