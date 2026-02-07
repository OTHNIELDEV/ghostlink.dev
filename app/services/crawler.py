import httpx
import trafilatura
from bs4 import BeautifulSoup
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

class CrawlerService:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        }

    async def fetch_page(self, url: str, retries: int = 3) -> Optional[str]:
        """
        Fetches the HTML content of a page with retries and robust error handling.
        Returns the raw HTML string or None if failed.
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            for attempt in range(retries):
                try:
                    response = await client.get(url, headers=self.headers)
                    response.raise_for_status()
                    return response.text
                except httpx.HTTPStatusError as e:
                    logger.error(f"HTTP Error fetching {url}: {e.response.status_code}")
                    if e.response.status_code in [403, 404, 500]:
                        # Don't retry on fatal client errors or specific server errors immediately if logic dictates
                        # But for now, we only retry connection issues mostly, or 5xx.
                        if e.response.status_code == 404:
                            return None # Not found, no retry
                except httpx.RequestError as e:
                    logger.warning(f"Connection error fetching {url} (Attempt {attempt + 1}/{retries}): {e}")
                
                # Exponential backoff
                await asyncio.sleep(2 ** attempt)
            
            logger.error(f"Failed to fetch {url} after {retries} attempts.")
            return None

    def extract_content(self, html: str) -> str:
        """
        Clean and extract main text content using Trafilatura and BeautifulSoup fallback.
        """
        if not html:
            return ""

        # 1. Trafilatura Extraction (Best mostly)
        text = trafilatura.extract(html, include_tables=False, include_comments=False)
        
        # 2. Fallback to BeautifulSoup if Trafilatura fails to get meaningful text
        if not text or len(text) < 100:
            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts and styles
            for script in soup(["script", "style", "nav", "footer", "aside", "noscript", "iframe"]):
                script.decompose()
            text = soup.get_text(separator="\n", strip=True)
            
        return text

    async def crawl_and_extract(self, url: str) -> dict:
        """
        Orchestrates fetching and extraction.
        Returns a dict with 'content', 'html', or raises Exception on total failure.
        """
        html = await self.fetch_page(url)
        if not html:
            raise Exception(f"Failed to retrieve content from {url}")
            
        content = self.extract_content(html)
        if not content:
            raise Exception(f"Failed to extract meaningful text from {url}")
            
        return {
            "html": html,
            "content": content
        }

crawler_service = CrawlerService()
