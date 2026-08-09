import re
import logging
from typing import List, Dict
from uuid import UUID

import numpy as np

MAX_CONTENT_CHARS = 2000  # ~512 tokens

from app.pipeline.models import ProcessedArticle, RawArticle, Topic, ScoredMatch
from app.pipeline.interfaces import DatabaseInterface, EmbeddingInterface, LLMInterface, EventBusInterface
from app.pipeline.exceptions import DuplicateArticleError, NoTopicMatchError

logger = logging.getLogger(__name__)

def strip_html(text: str) -> str:
    """A basic HTML stripper. In production, BeautifulSoup is preferred."""
    return re.sub(r'<[^>]*>', '', text)

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.asarray(v1, dtype=np.float32)
    b = np.asarray(v2, dtype=np.float32)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def stage_0_url_deduplicate(raw: RawArticle, db: DatabaseInterface) -> None:
    """
    Cheap duplicate check before we spend CPU on embedding generation.

    If the exact source URL already exists, the article is definitely not new,
    so we can drop it immediately without running Sentence-BERT.
    """
    if db.check_url_exists(str(raw.url)):
        raise DuplicateArticleError(f"URL already exists: {raw.url}")


def stage_1_preprocess(raw: RawArticle, embedder: EmbeddingInterface) -> ProcessedArticle:
    clean_content = strip_html(raw.content)
    # Truncate content to 512 tokens approx (we'll use characters for simplicity, ~2000 chars)
    truncated_content = clean_content[:MAX_CONTENT_CHARS]
    text_to_embed = f"{raw.headline}. {truncated_content}"
    
    embedding = embedder.encode_text(text_to_embed)
    
    return ProcessedArticle(
        raw=raw,
        clean_text=clean_content,
        embedding=embedding
    )


def stage_2_vector_deduplicate(article: ProcessedArticle, db: DatabaseInterface) -> None:
    """
    Semantic duplicate check after embedding generation.

    URL dedup already removed exact replays. This catches near-identical copies
    published under different URLs.
    """
    if db.vector_search_duplicate(article.embedding, threshold=0.95):
        raise DuplicateArticleError("Highly similar article already exists.")


def stage_3_topic_matching(
    article: ProcessedArticle,
    topic_cache: Dict[UUID, Topic],
    thresholds: Dict[str, float],
) -> List[dict]:
    """
    Compare article embedding against every active topic using each topic's
    own sensitivity threshold. Similarity = max cosine similarity across the
    topic's subtopic embeddings and its parent embedding.
    """
    matched_topics = []

    # One matrix multiply per topic instead of a Python loop per vector. The
    # article's own norm is constant across every comparison, so it is computed
    # once here rather than being recomputed inside each cosine call.
    article_vec = np.asarray(article.embedding, dtype=np.float32)
    article_norm = float(np.linalg.norm(article_vec))

    best_score = 0.0
    best_topic = None

    for topic_id, topic in topic_cache.items():
        topic_matrix = np.asarray(
            list(topic.subtopic_embeddings) + [topic.parent_embedding],
            dtype=np.float32,
        )
        if article_norm == 0.0:
            similarity = 0.0
        else:
            norms = np.linalg.norm(topic_matrix, axis=1)
            norms[norms == 0.0] = 1.0  # a zero vector scores 0, not NaN
            similarity = float(np.max((topic_matrix @ article_vec) / (norms * article_norm)))

        user_threshold = thresholds.get(topic.sensitivity, 0.65)

        if similarity > best_score:
            best_score, best_topic = similarity, topic.name

        if similarity >= user_threshold:
            logger.info(
                "    -> [MATCH] Topic '%s' (score: %.4f >= %s)",
                topic.name,
                similarity,
                user_threshold,
            )
            matched_topics.append({
                "topic_id": topic_id,
                "similarity": similarity,
                "user_id": topic.user_id,
            })

    if not matched_topics:
        # One summary line rather than one line per topic. At ~99% drop rate
        # the per-topic version wrote tens of thousands of lines an hour to
        # disk for output nobody reads.
        logger.info(
            "  [Stage 3] no match across %d topics | best: '%s' %.4f",
            len(topic_cache),
            best_topic,
            best_score,
        )
        raise NoTopicMatchError("Article did not match any active topics.")

    return matched_topics


def stage_4_relevance_scoring(matched_topics: List[dict], article: ProcessedArticle, db: DatabaseInterface) -> List[ScoredMatch]:
    scored_matches = []
    credibility = db.get_source_credibility(article.raw.source_id)
    
    for match in matched_topics:
        scored_matches.append(
            ScoredMatch(
                topic_id=match["topic_id"],
                relevance_score=match["similarity"],
                credibility_score=credibility
            )
        )
    return scored_matches


def stage_5_store_article(article: ProcessedArticle, scored_matches: List[ScoredMatch], db: DatabaseInterface) -> UUID:
    article_id = db.store_article_and_matches(article, scored_matches)
    article.id = article_id
    return article_id


def stage_6_summarisation(
    article: ProcessedArticle,
    llm: LLMInterface,
    db: DatabaseInterface,
    use_description: bool = False,
) -> None:
    # use_description=True: skip LLM call, use the clean description directly.
    # Set to False and remove the flag once full-article URL scraping is added.
    if use_description:
        summary = article.clean_text
    else:
        summary = llm.generate_summary(article.raw.headline, article.clean_text)
    article.summary = summary
    db.update_article_summary(article.id, summary)


def stage_7_publish(
    article: ProcessedArticle,
    matched_topics: List[dict],
    bus: EventBusInterface,
) -> None:
    """
    Publish one Kafka message per matched topic to the matched-articles topic.
    Threshold filtering already happened in Stage 3 - every match here is
    guaranteed to meet the user's sensitivity requirement. No re-filtering needed.

    matched_topics: list of dicts from stage_3_topic_matching, each containing
        topic_id, similarity, user_id.
    """
    for match in matched_topics:
        bus.publish_matched_article(
            article_id=article.id,
            topic_id=match["topic_id"],
            relevance_score=match["similarity"],
            user_id=match["user_id"],
        )
        logger.info(
            f"    -> [PUBLISHED] topic_id={match['topic_id']} user_id={match['user_id']} score={match['similarity']:.4f}"
        )



