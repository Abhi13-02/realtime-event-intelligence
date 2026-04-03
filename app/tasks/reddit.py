import logging
import requests
import datetime
import time

from app.celery_app import celery_app
from app.config import get_settings
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"
SUBREDDITS = ["technology", "worldnews", "science", "MachineLearning"]
RETRY_BACKOFFS = [0, 30, 60, 120]

settings = get_settings()

session = requests.Session()
# Reddit's Official Free Read-Only API requires a highly specific custom user-agent.
# Without this exact format, they throttle connections.
session.headers.update({
    "User-Agent": "python:chooglenews:v1.0.0 (by /u/choogle_admin)"
})

def fetch_top_comments(permalink: str, limit: int = 3) -> str:
    url = f"https://www.reddit.com{permalink}.json"
    
    # CRITICAL FIX: The Official Free Read-Only API has a strict rate limit.
    # We must sleep for 1.5 seconds between comment fetches to avoid 429 Client Errors.
    time.sleep(1.5)
    
    response = session.get(url, timeout=10)
    
    # If a 429 slips through, we catch it silently and back off instead of flooding the terminal
    if response.status_code == 429:
        time.sleep(5)
        return ""
        
    response.raise_for_status()
    data = response.json()
    
    if len(data) < 2:
        return ""
        
    comments_data = data[1].get("data", {}).get("children", [])
    comments = []
    for c in comments_data[:limit]:
        if c.get("kind") == "t1": 
            body = c.get("data", {}).get("body")
            if body:
                comments.append(body.strip())
                
    return "Top Comments:\n" + "\n---\n".join(comments) if comments else ""

@celery_app.task(bind=True, max_retries=3, name="app.tasks.reddit.crawl_reddit")
def crawl_reddit(self) -> None:
    published = 0
    skipped = 0

    try:
        for subreddit in SUBREDDITS:
            # We fetch 15 posts per subreddit. 
            # 15 posts * 4 subreddits = 60 requests. 
            # This perfectly fits the free unauthenticated rate limit while providing plenty of data.
            url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=15"
            time.sleep(2)
            
            response = session.get(url, timeout=10)
            response.raise_for_status()
            posts = response.json().get("data", {}).get("children", [])

            for post in posts:
                data = post.get("data", {})
                permalink = data.get("permalink")
                title = data.get("title")
                
                if not permalink or not title:
                    skipped += 1
                    continue
                
                absolute_url = f"https://www.reddit.com{permalink}"
                selftext = data.get("selftext", "").strip()
                
                # Fetch comments
                top_comments = fetch_top_comments(permalink, limit=3)

                content_parts = []
                if selftext:
                    content_parts.append(selftext)
                if top_comments:
                    content_parts.append(top_comments)
                    
                content = "\n\n".join(content_parts)
                if not content:
                    external_url = data.get("url")
                    if external_url and external_url != absolute_url:
                        content = f"Link post to: {external_url}"
                
                created_utc = data.get("created_utc")
                published_at = datetime.datetime.fromtimestamp(created_utc, tz=datetime.timezone.utc).isoformat() if created_utc else None

                publish_article({
                    "url": absolute_url,
                    "headline": title,
                    "content": content,
                    "source_id": REDDIT_SOURCE_ID,
                    "published_at": published_at,
                })
                published += 1

        logger.info(f"crawl_reddit complete — published: {published}, skipped: {skipped}")

    except Exception as exc:
        countdown = RETRY_BACKOFFS[self.request.retries]
        logger.warning(f"crawl_reddit failed: {exc} — retrying in {countdown}s")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=countdown)
