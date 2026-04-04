import re
import requests
import logging
import concurrent.futures
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class SimpleScraper:
    """
    A lightweight parallel scraper that extracts the main text content 
    from news article URLs without heavy dependencies.
    """
    
    def __init__(self, timeout: int = 10, max_chars: int = 3000):
        self.timeout = timeout
        self.max_chars = max_chars
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def scrape_url(self, url: str) -> str:
        """
        Fetches the URL and extracts all text inside <p> tags.
        Returns a cleaned, truncated string.
        """
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            
            # Simple but effective extraction for news sites:
            # 1. Find all content inside <p>...</p> tags
            body = resp.text
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', body, re.DOTALL | re.IGNORECASE)
            
            clean_paragraphs = []
            for p in paragraphs:
                # Basic HTML tag stripping from within the paragraph
                text = re.sub(r'<[^>]*>', '', p).strip()
                # Unescape some common HTML entities
                text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
                if len(text) > 40: # Ignore tiny snippets like "Share this" or captions
                    clean_paragraphs.append(text)
            
            full_text = "\n\n".join(clean_paragraphs)
            
            # Truncate to avoid memory bloat/LLM context limits
            return full_text[:self.max_chars]
            
        except Exception as e:
            logger.warning(f"[Scraper] Failed to scrape {url}: {e}")
            return ""

    def scrape_batch(self, urls: List[str], max_workers: int = 10) -> Dict[str, str]:
        """
        Scrapes multiple URLs in parallel using a ThreadPool.
        Returns a mapping of {url: content}.
        """
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Map of Future -> URL
            future_to_url = {executor.submit(self.scrape_url, url): url for url in urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    content = future.result()
                    results[url] = content
                except Exception as e:
                    logger.error(f"[Scraper] Thread error for {url}: {e}")
                    results[url] = ""
        return results
