import asyncio
import logging
import httpx
from typing import Any
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from .models import _SubThemeData

logger = logging.getLogger(__name__)

_REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; subtheme-discovery/1.0)"
}

async def _fetch_post_comments_async(
    client: httpx.AsyncClient,
    post_id: str,
    post_url: str,
    semaphore: asyncio.Semaphore,
) -> list[tuple[str, int]]:
    """Fetch comments for a single Reddit post asynchronously."""
    json_url = post_url.rstrip("/") + ".json?limit=25"
    async with semaphore:
        try:
            response = await client.get(json_url, timeout=10.0)
            if response.status_code != 200:
                return []
            
            data = response.json()
            if not isinstance(data, list) or len(data) < 2:
                return []

            comments_raw = data[1].get("data", {}).get("children", [])
            comments = []
            for child in comments_raw:
                if child.get("kind") != "t1":
                    continue
                body = child.get("data", {}).get("body", "").strip()
                score = child.get("data", {}).get("score", 0)
                if body and body not in ["[deleted]", "[removed]"]:
                    comments.append((body, max(score, 0)))
            return comments
        except Exception as exc:
            logger.warning("Async fetch failed for post %s: %s", post_id, exc)
            return []

async def _fetch_and_score_all_async(
    post_urls: dict[str, str],
    sub_theme_data: list[_SubThemeData],
    vader: SentimentIntensityAnalyzer,
) -> None:
    """Fetch all comments concurrently and calculate sentiment scores in-memory."""
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(headers=_REDDIT_HEADERS) as client:
        tasks = [
            _fetch_post_comments_async(client, pid, url, semaphore)
            for pid, url in post_urls.items()
        ]
        results = await asyncio.gather(*tasks)
        
        comments_by_post = dict(zip(post_urls.keys(), results))

        for st in sub_theme_data:
            if not st.reddit_post_ids:
                st.sentiment_score = None
                continue

            total_weight = 0.0
            weighted_sum = 0.0
            comment_count = 0

            for pid in st.reddit_post_ids:
                comments = comments_by_post.get(pid, [])
                for body, score in comments:
                    compound = vader.polarity_scores(body)["compound"]
                    weight = max(score, 1)
                    weighted_sum += compound * weight
                    total_weight += weight
                    comment_count += 1
            
            if total_weight > 0:
                st.sentiment_score = round(weighted_sum / total_weight, 4)
                logger.info("[SENTIMENT] sub-theme='%s' posts=%d comments=%d -> score=%s",
                            st.label, len(st.reddit_post_ids), comment_count, st.sentiment_score)
            else:
                st.sentiment_score = None

def _step3_process_reddit_sentiment(
    cur: Any,
    sub_theme_data: list[_SubThemeData],
    vader: SentimentIntensityAnalyzer,
) -> None:
    """Orchestrate the async fetching and sentiment scoring of Reddit comments."""
    all_reddit_ids = []
    for st in sub_theme_data:
        all_reddit_ids.extend(st.reddit_post_ids)
    
    if not all_reddit_ids:
        return

    cur.execute("SELECT id, url FROM articles WHERE id = ANY(%s::uuid[])", (all_reddit_ids,))
    post_urls = {str(r["id"]): r["url"] for r in cur.fetchall() if r["url"]}

    if not post_urls:
        return

    asyncio.run(_fetch_and_score_all_async(post_urls, sub_theme_data, vader))
