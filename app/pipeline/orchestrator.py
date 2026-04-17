import logging
from typing import Dict, List
from uuid import UUID

from app.pipeline import stages
from app.pipeline.exceptions import DuplicateArticleError, NoTopicMatchError, PipelineError
from app.pipeline.interfaces import DatabaseInterface, EmbeddingInterface, EventBusInterface, LLMInterface
from app.pipeline.models import ProcessedArticle, RawArticle, ScoredMatch, Topic

# Reddit posts are stored and topic-matched (Stages 0-5) so the discovery job
# can find them via article_topic_matches, but they are never summarised or
# published to matched-articles. No article alert should fire for a Reddit post.
REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"
ARTICLE_SEPARATOR = "=" * 100
ARTICLE_SUB_SEPARATOR = "-" * 100

logger = logging.getLogger(__name__)


class ArticlePipeline:
    def __init__(
        self,
        db: DatabaseInterface,
        embedder: EmbeddingInterface,
        llm: LLMInterface,
        bus: EventBusInterface,
        thresholds: Dict[str, float],
        max_retries: int = 3,
    ):
        self.db = db
        self.embedder = embedder
        self.llm = llm
        self.bus = bus
        self.thresholds = thresholds  # {"broad": 0.55, "balanced": 0.65, "high": 0.75}
        self.max_retries = max_retries
        self.topic_cache: Dict[UUID, Topic] = {}

    def refresh_topic_cache(self, active_topics: List[Topic]):
        """Refresh the in-memory cache of topics. Should be called periodically."""
        self.topic_cache = {topic.id: topic for topic in active_topics}
        logger.info("Topic cache refreshed. Loaded %d active topics.", len(self.topic_cache))

    def resume_article(self, processed_article: ProcessedArticle, scored_matches: List[ScoredMatch]) -> None:
        """
        Resume processing for an article that completed Stages 0-5 but whose
        summarisation (Stage 6) failed permanently before the process was killed.

        Jumps straight to Stage 6 -> Stage 7, skipping dedup/embed/match/store.
        Called on consumer startup for all articles with pipeline_status='passed_dedup'
        and summary=NULL.
        """
        logger.info("Resuming article %s from Stage 6...", processed_article.id)

        stages.stage_6_summarisation(processed_article, self.llm, self.db, use_description=True)

        # Stage 7: publish to matched-articles Kafka topic.
        # Reconstruct matched_topics from scored_matches + topic cache.
        try:
            matched_topics = [
                {
                    "topic_id": match.topic_id,
                    "similarity": match.relevance_score,
                    "user_id": self.topic_cache[match.topic_id].user_id,
                }
                for match in scored_matches
                if match.topic_id in self.topic_cache
            ]
            stages.stage_7_publish(processed_article, matched_topics, self.bus)
            logger.info("Successfully resumed and routed article %s", processed_article.id)
        except Exception as exc:
            logger.error("Stage 7 failed during resume for article %s: %s", processed_article.id, exc)
            raise PipelineError(f"Stage 7 failure during resume: {exc}") from exc

    def process_article(self, raw_article: RawArticle) -> None:
        """
        Executes the 8-step fail-fast NLP pipeline for a single article.
        Designed to be called by a Kafka consumer (or any event loop).
        """
        is_reddit = str(raw_article.source_id) == REDDIT_SOURCE_ID
        content_preview = (raw_article.content or "")[:300]
        logger.info(
            "\n%s\n[ARTICLE] %s\n  headline : %s\n  content  : %s\n%s",
            ARTICLE_SEPARATOR,
            raw_article.url,
            raw_article.headline,
            content_preview if content_preview else "(no content)",
            ARTICLE_SUB_SEPARATOR,
        )

        try:
            # Stage 0: URL deduplication. If this hits, skip embedding entirely.
            stages.stage_0_url_deduplicate(raw_article, self.db)

            # Stage 1: preprocessing + embedding.
            article = stages.stage_1_preprocess(raw_article, self.embedder)

            # Stage 2: vector deduplication for near-identical copies.
            stages.stage_2_vector_deduplicate(article, self.db)

            # Stage 3: topic matching using per-topic sensitivity thresholds.
            matched_topics = stages.stage_3_topic_matching(article, self.topic_cache, self.thresholds)

            # Stage 4: relevance scoring.
            scored_matches = stages.stage_4_relevance_scoring(matched_topics, article, self.db)

            # Stage 5: store article + matches.
            stages.stage_5_store_article(article, scored_matches, self.db)

            # Reddit early exit: stored and topic-matched, but no summarisation
            # or alert. The sub-theme discovery job picks posts up from the DB.
            if is_reddit:
                logger.info(
                    "[ARTICLE END] Reddit post stored - skipping Stage 6+7 | url=%s\n%s",
                    raw_article.url,
                    ARTICLE_SEPARATOR,
                )
                return

        except (DuplicateArticleError, NoTopicMatchError) as exc:
            logger.info(
                "[ARTICLE END] dropped: %s | url=%s\n%s",
                exc,
                raw_article.url,
                ARTICLE_SEPARATOR,
            )
            return
        except Exception as exc:
            logger.error(
                "Error processing article %s in stages 0-5: %s\n%s",
                raw_article.url,
                exc,
                ARTICLE_SEPARATOR,
            )
            raise PipelineError(f"Pipeline crashed early: {exc}") from exc

        # Stage 6: summarisation is currently bypassed by using the clean
        # description text directly. Re-enable the LLM call once URL scraping
        # is added and the article body is richer than the feed description.
        stages.stage_6_summarisation(article, self.llm, self.db, use_description=True)

        # Stage 7: publish to matched-articles Kafka topic.
        try:
            stages.stage_7_publish(article, matched_topics, self.bus)
            logger.info(
                "[ARTICLE END] Successfully processed and routed article %s | url=%s\n%s",
                article.id,
                raw_article.url,
                ARTICLE_SEPARATOR,
            )
        except Exception as exc:
            logger.error("Stage 7 failed for article %s: %s\n%s", article.id, exc, ARTICLE_SEPARATOR)
            raise PipelineError(f"Stage 7 failure: {exc}") from exc
