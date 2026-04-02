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


def stage_0_preprocess(raw: RawArticle, embedder: EmbeddingInterface) -> ProcessedArticle:
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


def stage_1_deduplicate(article: ProcessedArticle, db: DatabaseInterface) -> None:
    # URL fast path check
    if db.check_url_exists(str(article.raw.url)):
        raise DuplicateArticleError(f"URL already exists: {article.raw.url}")
        
    # ANN search
    if db.vector_search_duplicate(article.embedding, threshold=0.95):
        raise DuplicateArticleError("Highly similar article already exists.")


def stage_2_topic_matching(article: ProcessedArticle, topic_cache: Dict[UUID, Topic]) -> List[dict]:
    matched_topics = []
    
    logger.info(f"  [Stage 2] Comparing embedding against {len(topic_cache)} active topics...")
    for topic_id, topic in topic_cache.items():
        similarity = cosine_similarity(article.embedding, topic.embedding)
        if similarity >= 0.55:
            logger.info(f"    -> [MATCH] Topic '{topic.name}' (score: {similarity:.4f} >= 0.55)")
            matched_topics.append({
                "topic_id": topic_id,
                "similarity": similarity
            })
        else:
            logger.info(f"    -> [DROP] Topic '{topic.name}' (score: {similarity:.4f} < 0.55)")
            
    if not matched_topics:
        raise NoTopicMatchError("Article did not match any active topics.")
        
    return matched_topics


def stage_3_relevance_scoring(matched_topics: List[dict], article: ProcessedArticle, db: DatabaseInterface) -> List[ScoredMatch]:
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


def stage_4_store_article(article: ProcessedArticle, scored_matches: List[ScoredMatch], db: DatabaseInterface) -> UUID:
    article_id = db.store_article_and_matches(article, scored_matches)
    article.id = article_id
    return article_id


def stage_5_summarisation(article: ProcessedArticle, llm: LLMInterface, db: DatabaseInterface) -> None:
    summary = llm.generate_summary(article.raw.headline, article.clean_text)
    article.summary = summary
    db.update_article_summary(article.id, summary)


def stage_6_user_threshold_filter(article: ProcessedArticle, scored_matches: List[ScoredMatch], topic_cache: Dict[UUID, Topic], db: DatabaseInterface, bus: EventBusInterface) -> None:
    SENSITIVITY_THRESHOLDS = {
        "broad":    0.55,
        "balanced": 0.65,
        "high":     0.75
    }

    for match in scored_matches:
        topic_id = match.topic_id
        relevance = match.relevance_score
        
        # Look up topic from in-memory cache — zero DB round trips
        topic = topic_cache.get(topic_id)
        if not topic:
            continue
            
        # Map user's string label to strict float threshold
        user_threshold = SENSITIVITY_THRESHOLDS.get(topic.sensitivity, 0.65)
        if relevance < user_threshold:
            logger.info(f"    -> [USER FILTER DROP] Topic '{topic.name}' (score: {relevance:.4f} < {user_threshold} filter for '{topic.sensitivity}')")
            continue
        
        logger.info(f"    -> [USER FILTER PASS] Topic '{topic.name}' (score: {relevance:.4f} >= {user_threshold} filter for '{topic.sensitivity}')")
            
        # User ID is directly accessible from the topic cache definition
        # Publish exactly one event per (article, topic) match
        bus.publish_matched_article(
            article_id=article.id,
            topic_id=topic_id,
            relevance_score=relevance,
            user_id=topic.user_id
        )
