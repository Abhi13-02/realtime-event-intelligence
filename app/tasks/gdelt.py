import logging
import time
from typing import Set
from app.celery_app import celery_app
from app.config import get_settings
from app.pipeline.adapters.db_adapter import PostgresAdapter
from app.pipeline.adapters.gdelt_adapter import GDELTAdapter
from app.pipeline.gdelt_resolver import GDELTThemeResolver
from app.pipeline.utils import SimpleScraper
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

# Unique source ID for GDELT articles in our DB
GDELT_SOURCE_ID = "d1e2f3a4-0005-0005-0005-000000000005"

# Use the same retry backoff logic as HackerNews/Reddit tasks
RETRY_BACKOFFS = [0, 30, 60, 120]

settings = get_settings()

@celery_app.task(bind=True, max_retries=3, name="app.tasks.gdelt.crawl_gdelt")
def crawl_gdelt(self) -> None:
    """
    Celery task: 
    1. Grabs all active user topics from DB.
    2. Resolves top GDELT themes for each topic.
    3. Fetches latest articles for those themes from GDELT.
    4. Scrapes full article content from URLs in parallel.
    5. Publishes to Kafka raw-articles topic.
    """
    try:
        db = PostgresAdapter(settings.database_url)
        resolver = GDELTThemeResolver(index_dir="scripts/gdelt_theme_index")
        adapter = GDELTAdapter(GDELT_SOURCE_ID)
        scraper = SimpleScraper(max_chars=3000)

        # 1. Get active topics
        topics = db.get_active_topics()
        logger.info(f"[GDELTTask] Found {len(topics)} active topics.")

        # 2. Extract and/or Resolve themes for each topic
        all_unique_themes: Set[str] = set()
        for topic in topics:
            if not topic.gdelt_theme_ids and topic.expanded_description:
                logger.info(f"  -> Resolving themes for topic: {topic.name}")
                matches = resolver.get_query_themes(topic.expanded_description, score_threshold=0.5)
                topic.gdelt_theme_ids = matches
                db.update_topic_gdelt_themes(topic.id, matches)
            
            if topic.gdelt_theme_ids:
                all_unique_themes.update(topic.gdelt_theme_ids)
        
        logger.info(f"[GDELTTask] Unique themes to query: {len(all_unique_themes)}")
        if not all_unique_themes:
            db.close()
            return

        # 3. Query GDELT for batches of themes (to avoid 5s rate limits)
        # We process 10 themes per query
        theme_list = list(all_unique_themes)
        batch_size = 10
        total_published = 0
        
        for i in range(0, len(theme_list), batch_size):
            batch_themes = theme_list[i : i + batch_size]
            
            for country in ["US", "IN"]:
                logger.info(f"  [Query] Batch {i//batch_size + 1} for {country}: {batch_themes}")
                
                # Fetch article metadata from GDELT
                articles = adapter.search_articles(themes=batch_themes, country=country, max_records=50)
                
                if articles:
                    # Parallel Scrape the actual content for this batch
                    urls = [art.url for art in articles if art.url]
                    scraped_content = scraper.scrape_batch(urls, max_workers=10)

                    for art in articles:
                        # Update content with scraped text if found
                        body = scraped_content.get(str(art.url))
                        if body:
                            art.content = body
                        
                        publish_article(art.model_dump())
                        total_published += 1
                
                # GDELT rate limit spacing
                time.sleep(7)

        logger.info(f"[GDELTTask] Finished. Total articles ingested: {total_published}")
        db.close()

    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.error(f"[GDELTTask] Failed (attempt {self.request.retries + 1}): {exc}")
        raise self.retry(exc=exc, countdown=countdown)
