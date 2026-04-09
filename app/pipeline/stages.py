import math
import re
import logging
from typing import List, Dict
from uuid import UUID

from app.pipeline.models import ProcessedArticle, RawArticle, Topic, ScoredMatch
from app.pipeline.interfaces import DatabaseInterface, EmbeddingInterface, LLMInterface, EventBusInterface
from app.pipeline.exceptions import DuplicateArticleError, NoTopicMatchError

logger = logging.getLogger(__name__)

def strip_html(text: str) -> str:
    """A basic HTML stripper. In production, BeautifulSoup is preferred."""
    return re.sub(r'<[^>]*>', '', text)

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


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
    truncated_content = clean_content[:2000]
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
    own sensitivity threshold. An article only passes if at least one user's
    topic actually wants it — no point storing or summarising otherwise.

    thresholds: dict mapping sensitivity label to float, e.g.
        {"broad": 0.55, "balanced": 0.65, "high": 0.75}
        Passed in from config so they can be changed without code changes.
    """
    matched_topics = []

    logger.info(f"  [Stage 3] Comparing embedding against {len(topic_cache)} active topics...")
    for topic_id, topic in topic_cache.items():
        # Score against every subtopic embedding, then include the parent as a
        # safety net (Option B). Taking the max means any focused angle that
        # matches is sufficient — the article doesn't need to match the broad
        # parent description to get through.
        scores = [cosine_similarity(article.embedding, sub_emb) for sub_emb in topic.subtopic_embeddings]
        scores.append(cosine_similarity(article.embedding, topic.parent_embedding))
        similarity = max(scores)

        user_threshold = thresholds.get(topic.sensitivity, 0.65)

        if similarity >= user_threshold:
            logger.info(f"    -> [MATCH] Topic '{topic.name}' (score: {similarity:.4f} >= {user_threshold} for '{topic.sensitivity}')")
            matched_topics.append({
                "topic_id": topic_id,
                "similarity": similarity,
                "user_id": topic.user_id,
            })
        else:
            logger.info(f"    -> [DROP] Topic '{topic.name}' (score: {similarity:.4f} < {user_threshold} for '{topic.sensitivity}')")

    if not matched_topics:
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


# Backward-compatible aliases for older tests/scripts that still import the
# pre-split stage names directly.
def stage_0_preprocess(raw: RawArticle, embedder: EmbeddingInterface) -> ProcessedArticle:
    return stage_1_preprocess(raw, embedder)


def stage_1_deduplicate(article: ProcessedArticle, db: DatabaseInterface) -> None:
    stage_2_vector_deduplicate(article, db)


def stage_2_topic_matching(
    article: ProcessedArticle,
    topic_cache: Dict[UUID, Topic],
    thresholds: Dict[str, float],
) -> List[dict]:
    return stage_3_topic_matching(article, topic_cache, thresholds)


def stage_3_relevance_scoring(matched_topics: List[dict], article: ProcessedArticle, db: DatabaseInterface) -> List[ScoredMatch]:
    return stage_4_relevance_scoring(matched_topics, article, db)


def stage_4_store_article(article: ProcessedArticle, scored_matches: List[ScoredMatch], db: DatabaseInterface) -> UUID:
    return stage_5_store_article(article, scored_matches, db)


def stage_5_summarisation(
    article: ProcessedArticle,
    llm: LLMInterface,
    db: DatabaseInterface,
    use_description: bool = False,
) -> None:
    stage_6_summarisation(article, llm, db, use_description=use_description)


def stage_6_publish(
    article: ProcessedArticle,
    matched_topics: List[dict],
    bus: EventBusInterface,
) -> None:
    stage_7_publish(article, matched_topics, bus)

