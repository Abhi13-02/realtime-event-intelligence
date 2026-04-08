import datetime
import logging
from typing import Any, Dict, List

import requests

from app.celery_app import celery_app
from app.config import get_settings
from app.tasks.kafka_producer import publish_article

logger = logging.getLogger(__name__)

REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"

# Default subreddits to monitor if not configured
DEFAULT_SUBREDDITS = [
    {"name": "MachineLearning", "limit": 25, "sort": "new"},
]

settings = get_settings()

class RedditWorker:
    """Enhanced Reddit client with proper rate limiting and error handling."""

    def __init__(self):
        # Reddit blocks default "python-requests" user agents.
        # We must spoof a standard web browser to use the public endpoints.
        self.headers = {
            'User-Agent': settings.reddit_user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.timeout = 10
        self.rate_limit_delay = 2  # seconds between requests to avoid IP ban

    def fetch_subreddit_posts(self, subreddit: str, limit: int = 25, sort: str = "new") -> List[Dict[str, Any]]:
        """
        Fetches latest posts from a subreddit using the JSON endpoint.

        Args:
            subreddit: Subreddit name (e.g., "MachineLearning", "Python")
            limit: Number of posts to fetch (max 100, default 25)
            sort: Sort order - "new", "hot", "top", "rising"

        Returns:
            List of post dictionaries ready to be published
        """
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
        posts = []

        try:
            logger.info(f"🔄 [REDDIT] Fetching latest {limit} posts from r/{subreddit}...")
            logger.info(f"   URL: {url}")

            response = requests.get(url, headers=self.headers, timeout=self.timeout)

            # Check for rate limiting
            if response.status_code == 429:
                logger.error(f"⚠️  Rate limited by Reddit (429). Waiting before retry...")
                time.sleep(60)  # Wait 60 seconds before retrying
                return []

            if response.status_code != 200:
                logger.error(f"❌ Failed to fetch subreddit. Status: {response.status_code}")
                logger.error(f"   Response: {response.text[:200]}")
                return []

            # Parse Reddit JSON response
            data = response.json()
            post_list = data.get('data', {}).get('children', [])

            logger.info(f"✅ Retrieved {len(post_list)} posts from r/{subreddit}")

            for post in post_list:
                post_data = post['data']

                # Extract essential post information
                post_dict = {
                    "post_id": post_data.get('id'),
                    "post_title": post_data.get('title'),
                    "post_body": post_data.get('selftext', '')[:500],  # Truncate body to 500 chars
                    "subreddit": post_data.get('subreddit'),
                    "permalink": post_data.get('permalink'),
                    "post_url": f"https://reddit.com{post_data.get('permalink')}",
                    "author": post_data.get('author'),
                    "score": post_data.get('score', 0),
                    "num_comments": post_data.get('num_comments', 0),
                    "created_utc": post_data.get('created_utc'),
                    "is_self": post_data.get('is_self'),
                }

                # Validate required fields
                if post_dict['post_id'] and post_dict['post_title']:
                    posts.append(post_dict)
                    logger.debug(f"   ✓ Processed: {post_dict['post_title'][:60]}...")

            logger.info(f"📤 [REDDIT] Successfully processed {len(posts)} posts from r/{subreddit}")
            return posts

        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout fetching r/{subreddit}")
            return []
        except requests.exceptions.ConnectionError:
            logger.error(f"❌ Connection error fetching r/{subreddit}")
            return []
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching r/{subreddit}: {e}")
            return []



# Global worker instance
_reddit_worker = None

def get_reddit_worker() -> RedditWorker:
    """Get or create the global RedditWorker instance."""
    global _reddit_worker
    if _reddit_worker is None:
        _reddit_worker = RedditWorker()
    return _reddit_worker


@celery_app.task(bind=True, max_retries=3, name="app.tasks.reddit.crawl_reddit")
def crawl_reddit(self) -> None:
    """
    Enhanced Reddit crawler that monitors multiple subreddits with configurable settings.
    Integrates the improved ingestion logic from the Reddit prototype.
    """
    published = 0
    skipped = 0

    try:
        worker = get_reddit_worker()

        # Use configured subreddits or fall back to defaults
        subreddits_config = getattr(settings, 'reddit_subreddits', None)
        if not subreddits_config:
            # Fall back to default configuration
            subreddits_config = DEFAULT_SUBREDDITS

        logger.info(f"🔄 [REDDIT] Starting crawl of {len(subreddits_config)} subreddits")

        for subreddit_config in subreddits_config:
            subreddit_name = subreddit_config['name']
            limit = subreddit_config.get('limit', 25)
            sort = subreddit_config.get('sort', 'new')

            # Fetch posts from this subreddit
            posts = worker.fetch_subreddit_posts(
                subreddit=subreddit_name,
                limit=limit,
                sort=sort
            )

            if not posts:
                logger.warning(f"⚠️  No posts fetched from r/{subreddit_name}")
                continue

            # Process each post — posts only, no comments.
            # Comments are fetched by the sub-theme discovery job (run_subtheme_discovery)
            # after Reddit posts have been assigned to cluster centroids. Fetching here
            # would give immature comment threads (post may be seconds old at crawl time).
            for post in posts:
                try:
                    title = post['post_title']
                    absolute_url = post['post_url']
                    selftext = post['post_body']

                    # content is post body only — no comments
                    content = selftext if selftext else f"Link post: {absolute_url}"

                    # Convert timestamp
                    created_utc = post.get('created_utc')
                    published_at = None
                    if created_utc:
                        published_at = datetime.datetime.fromtimestamp(
                            created_utc, tz=datetime.timezone.utc
                        ).isoformat()

                    publish_article({
                        "url": absolute_url,
                        "headline": title,
                        "content": content,
                        "source_id": REDDIT_SOURCE_ID,
                        "published_at": published_at,
                        "metadata": {
                            "subreddit": post['subreddit'],
                            "author": post['author'],
                            "score": post['score'],
                            "num_comments": post['num_comments'],
                        }
                    })
                    published += 1

                except Exception as post_exc:
                    logger.error(f"❌ Error processing post {post.get('post_id', 'unknown')}: {post_exc}")
                    skipped += 1
                    continue

        logger.info(f"✅ crawl_reddit complete — published: {published}, skipped: {skipped}")

    except Exception as exc:
        countdown = [0, 30, 60, 120][self.request.retries]
        logger.warning(f"crawl_reddit failed: {exc} — retrying in {countdown}s")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=countdown)
