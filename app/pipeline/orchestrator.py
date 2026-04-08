import logging
import time
from typing import Dict, List
from uuid import UUID

from app.pipeline.models import RawArticle, Topic, ProcessedArticle, ScoredMatch
from app.pipeline.interfaces import DatabaseInterface, EmbeddingInterface, LLMInterface, EventBusInterface
from app.pipeline.exceptions import DuplicateArticleError, NoTopicMatchError, PipelineError
from app.pipeline import stages

# Reddit posts are stored and topic-matched (Stages 0-4) so the discovery job
# can find them via article_topic_matches, but they are never summarised or
# published to matched-articles — no article alert should fire for a Reddit post.
REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"

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
        logger.info(f"Topic cache refreshed. Loaded {len(self.topic_cache)} active topics.")

    def resume_article(self, processed_article: ProcessedArticle, scored_matches: List[ScoredMatch]) -> None:
        """
        Resume processing for an article that completed Stages 0-4 but whose
        summarisation (Stage 5) failed permanently before the process was killed.

        Jumps straight to Stage 5 → Stage 6, skipping embed/dedup/match/store.
        Called on consumer startup for all articles with pipeline_status='passed_dedup'
        and summary=NULL.
        """
        logger.info(f"Resuming article {processed_article.id} from Stage 5...")

        # Stage 5: Summarisation — DISABLED (descriptions are already short enough;
        # full-article scraping needed to make summarisation worthwhile).
        # Use the clean description text directly as the summary.
        # Re-enable once URL scraping is added.
        # ── disabled ──────────────────────────────────────────────────────────
        # summary_success = False
        # for attempt in range(self.max_retries + 1):
        #     try:
        #         stages.stage_5_summarisation(processed_article, self.llm, self.db)
        #         summary_success = True
        #         break
        #     except Exception as e:
        #         delay = 2 ** attempt
        #         if attempt < self.max_retries:
        #             logger.warning(f"Summarisation failed (attempt {attempt+1}). Retrying in {delay}s. Error: {str(e)}")
        #             time.sleep(delay)
        #         else:
        #             logger.error(f"Summarisation permanently failed for article {processed_article.id} after {self.max_retries} retries.")
        # if not summary_success:
        #     raise PipelineError(f"Stage 5 permanent failure during resume for article {processed_article.id}")
        # ── end disabled ───────────────────────────────────────────────────────
        stages.stage_5_summarisation(processed_article, self.llm, self.db, use_description=True)

        # Stage 6: Publish to matched-articles Kafka topic
        # Reconstruct matched_topics from scored_matches + topic cache.
        try:
            matched_topics = [
                {
                    "topic_id": m.topic_id,
                    "similarity": m.relevance_score,
                    "user_id": self.topic_cache[m.topic_id].user_id,
                }
                for m in scored_matches
                if m.topic_id in self.topic_cache
            ]
            stages.stage_6_publish(processed_article, matched_topics, self.bus)
            logger.info(f"Successfully resumed and routed article {processed_article.id}")
        except Exception as e:
            logger.error(f"Stage 6 failed during resume for article {processed_article.id}: {str(e)}")
            raise PipelineError(f"Stage 6 failure during resume: {str(e)}") from e

    def process_article(self, raw_article: RawArticle) -> None:
        """
        Executes the 6-stage fail-fast NLP pipeline for a single article.
        Designed to be called by a Kafka consumer (or any event loop).
        """
        try:
            # Stage 0: Preprocessing
            article = stages.stage_0_preprocess(raw_article, self.embedder)

            # Stage 1: Deduplication
            stages.stage_1_deduplicate(article, self.db)

            # Stage 2: Topic Matching — uses per-topic sensitivity thresholds
            matched_topics = stages.stage_2_topic_matching(article, self.topic_cache, self.thresholds)

            # Stage 3: Relevance Scoring
            scored_matches = stages.stage_3_relevance_scoring(matched_topics, article, self.db)

            # Stage 4: Store Article
            stages.stage_4_store_article(article, scored_matches, self.db)

            # Reddit early exit — stored and topic-matched, but no summarisation
            # or alert. The sub-theme discovery job picks them up from the DB.
            if str(raw_article.source_id) == REDDIT_SOURCE_ID:
                logger.info("Reddit post stored — skipping Stage 5+6: %s", raw_article.url)
                return

        except (DuplicateArticleError, NoTopicMatchError) as e:
            # Expected early exits
            logger.info(f"Article dropped: {str(e)}")
            return
        except Exception as e:
            # Unexpected error in stages 0-4
            logger.error(f"Error processing article {raw_article.url} in stages 0-4: {str(e)}")
            raise PipelineError(f"Pipeline crashed early: {str(e)}") from e


        # Stage 5: Summarisation — DISABLED (descriptions are already short enough;
        # full-article scraping needed to make summarisation worthwhile).
        # Use the clean description text directly as the summary.
        # Re-enable once URL scraping is added.
        # ── disabled ──────────────────────────────────────────────────────────
        # summary_success = False
        # for attempt in range(self.max_retries + 1):
        #     try:
        #         stages.stage_5_summarisation(article, self.llm, self.db)
        #         summary_success = True
        #         break
        #     except Exception as e:
        #         delay = 2 ** attempt
        #         if attempt < self.max_retries:
        #             logger.warning(f"Summarisation failed (attempt {attempt+1}). Retrying in {delay}s. Error: {str(e)}")
        #             time.sleep(delay)
        #         else:
        #             logger.error(f"Summarisation permanently failed for article {article.id} after {self.max_retries} retries.")
        # if not summary_success:
        #     raise PipelineError(f"Stage 5 permanent failure for article {article.id}")
        # ── end disabled ───────────────────────────────────────────────────────
        stages.stage_5_summarisation(article, self.llm, self.db, use_description=True)


        # Stage 6: Publish to matched-articles Kafka topic
        try:
            stages.stage_6_publish(article, matched_topics, self.bus)
            logger.info(f"Successfully processed and routed article {article.id}")
        except Exception as e:
            logger.error(f"Stage 6 failed for article {article.id}: {str(e)}")
            raise PipelineError(f"Stage 6 failure: {str(e)}") from e
