import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from typing import List, Dict, Any

from app.constants import REDDIT_SOURCE_ID, get_sync_db_url
from app.tasks.ingestion.rss_scrapper import crawl_rss_feed
from app.tasks.ingestion.reddit import crawl_reddit
from app.tasks.ingestion.api_scrapers import crawl_newsapi, crawl_newsdata
from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Register UUID adapter so psycopg2 returns uuid.UUID objects
psycopg2.extras.register_uuid()

def get_sync_conn():
    conn = psycopg2.connect(get_sync_db_url())
    return conn

@celery_app.task(name="app.tasks.ingestion.dispatch_source")
def dispatch_source(source_id: str):
    """
    Heartbeat task for a specific RSS source.
    Loads active feeds from DB and spawns crawl tasks.
    """
    conn = get_sync_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # 1. Load source config
        cur.execute("SELECT id, name, is_active, poll_interval, last_crawled_at, articles_per_crawl FROM sources WHERE id = %s", (source_id,))
        source = cur.fetchone()
        
        if not source:
            logger.error(f"Source {source_id} not found in database.")
            return

        # 2. Safety check: Is the source active?
        if not source["is_active"]:
            logger.info(f"Source {source['name']} is disabled. Skipping.")
            return

        # 3. Throttle: Has enough time passed since last crawl?
        now = datetime.now(timezone.utc)
        if source["last_crawled_at"]:
            elapsed = (now - source["last_crawled_at"]).total_seconds()
            if elapsed < source["poll_interval"]:
                logger.debug(f"Source {source['name']} throttled (elapsed: {int(elapsed)}s < {source['poll_interval']}s).")
                return

        # 4. Load all active feeds for this source
        cur.execute(
            "SELECT feed_url, articles_per_crawl FROM rss_feed_configs WHERE source_id = %s AND is_active = TRUE",
            (source_id,)
        )
        feeds = cur.fetchall()
        
        if not feeds:
            logger.warning(f"Source {source['name']} has no active feeds configured.")
            return

        # 5. Dispatch individual crawl tasks
        logger.info(f"Dispatching {len(feeds)} feeds for source {source['name']}")
        for feed in feeds:
            # Feed-level limit takes precedence over source-level limit
            max_articles = feed["articles_per_crawl"] or source["articles_per_crawl"]
            crawl_rss_feed.delay(feed["feed_url"], source_id, max_articles)

        # 6. Update last_crawled_at to current time
        cur.execute(
            "UPDATE sources SET last_crawled_at = %s WHERE id = %s",
            (now, source_id)
        )
        conn.commit()
        
    except Exception as e:
        logger.error(f"Error in dispatch_source for {source_id}: {e}", exc_info=True)
    finally:
        conn.close()

@celery_app.task(name="app.tasks.ingestion.dispatch_reddit")
def dispatch_reddit():
    """
    Heartbeat task for Reddit.
    Loads active subreddits from DB and spawns one crawl_reddit task.
    """
    conn = get_sync_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT id, name, is_active, poll_interval, last_crawled_at FROM sources WHERE id = %s", (REDDIT_SOURCE_ID,))
        source = cur.fetchone()
        
        if not source or not source["is_active"]:
            return

        now = datetime.now(timezone.utc)
        if source["last_crawled_at"]:
            if (now - source["last_crawled_at"]).total_seconds() < source["poll_interval"]:
                return

        # Load active subreddits from the new table
        cur.execute("SELECT name, limit_per_crawl as limit, sort FROM reddit_subreddits WHERE is_active = TRUE")
        subreddits = cur.fetchall()
        
        if subreddits:
            logger.info(f"Dispatching Reddit crawl for {len(subreddits)} subreddits")
            crawl_reddit.delay(subreddits=subreddits)

            cur.execute(
                "UPDATE sources SET last_crawled_at = %s WHERE id = %s",
                (now, REDDIT_SOURCE_ID)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error in dispatch_reddit: {e}", exc_info=True)
    finally:
        conn.close()

@celery_app.task(name="app.tasks.ingestion.dispatch_api")
def dispatch_api(source_id: str):
    """
    Heartbeat task for API sources (NewsAPI, NewsData).
    """
    conn = get_sync_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT id, name, is_active, poll_interval, last_crawled_at, articles_per_crawl FROM sources WHERE id = %s", (source_id,))
        source = cur.fetchone()
        
        if not source or not source["is_active"]:
            return

        now = datetime.now(timezone.utc)
        if source["last_crawled_at"]:
            if (now - source["last_crawled_at"]).total_seconds() < source["poll_interval"]:
                return

        max_articles = source["articles_per_crawl"]
        source_name_lower = source["name"].lower()
        
        if "newsapi" in source_name_lower:
            logger.info(f"Dispatching NewsAPI crawl for source {source['name']}")
            crawl_newsapi.delay(source_id, max_articles)
        elif "newsdata" in source_name_lower:
            logger.info(f"Dispatching NewsData crawl for source {source['name']}")
            crawl_newsdata.delay(source_id, max_articles)
        
        cur.execute(
            "UPDATE sources SET last_crawled_at = %s WHERE id = %s",
            (now, source_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error in dispatch_api for {source_id}: {e}", exc_info=True)
    finally:
        conn.close()
