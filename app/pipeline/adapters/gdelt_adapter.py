import logging
import requests
import time
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from app.pipeline.models import RawArticle

logger = logging.getLogger(__name__)

# The DOC v2 API is the standard for article search
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

class GDELTAdapter:
    """
    Adapter for the GDELT DOC API (v2).
    """
    
    def __init__(self, source_id: str):
        self.source_id = UUID(source_id)

    def search_articles(
        self, 
        themes: List[str], 
        max_records: int = 50,
        country: Optional[str] = "IN",
        lang: str = "english"
    ) -> List[RawArticle]:
        """
        Queries GDELT DOC API for articles matching a list of themes using OR logic.
        Includes a 429-retry loop to handle GDELT's strict rate limits.
        """
        if not themes:
            return []

        # Build theme query: theme:(THEME1 OR THEME2 ...)
        theme_query = f"theme:({' OR '.join(themes)})" if len(themes) > 1 else f"theme:{themes[0]}"
        
        query_parts = [theme_query]
        if country:
            query_parts.append(f"sourcecountry:{country}")
        if lang:
            query_parts.append(f"sourcelang:{lang}")
            
        params = {
            "query": " ".join(query_parts),
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "timespan": "24h", # Wider window for reliability
        }

        # 429 Retry Loop (3 attempts)
        for attempt in range(4):
            try:
                logger.info(f"[GDELTAdapter] Querying GDELT: {params['query']} (Attempt {attempt+1})")
                resp = requests.get(GDELT_DOC_API_URL, params=params, timeout=20)
                
                if resp.status_code == 429:
                    wait_time = 15 * (attempt + 1)
                    logger.warning(f"[GDELTAdapter] 429 Rate Limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                resp.raise_for_status()
                
                data = resp.json()
                articles_data = data.get("articles", [])
                logger.info(f"[GDELTAdapter] Found {len(articles_data)} article(s).")
                
                return self._parse_results(articles_data)
                
            except Exception as e:
                logger.error(f"[GDELTAdapter] Request failed: {e}")
                if attempt < 3:
                    time.sleep(5)
                else:
                    return []
        
        return []

    def _parse_results(self, json_data: List[dict]) -> List[RawArticle]:
        raw_articles = []
        for item in json_data:
            if not item.get("url"):
                continue
            
            # GGK/DOC API keys: url, title, seodescription, seendate
            raw_articles.append(RawArticle(
                url=item["url"],
                headline=item.get("title", ""),
                # Use seodescription as content snippet if available
                content=item.get("seodescription") or item.get("title", ""),
                source_id=self.source_id,
                published_at=self._parse_gdelt_date(item.get("seendate"))
            ))
        return raw_articles

    def _parse_gdelt_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        # DOC API format example: 20260404T081500Z
        try:
            return datetime.strptime(date_str, "%Y%m%dT%H%M%SZ")
        except:
            return None
