"""Scraper for Greenhouse Job Boards (Source A)."""

from __future__ import annotations

import html
import logging
from typing import List, Optional
from bs4 import BeautifulSoup

from pipeline.models import RawJobPosting
from pipeline.scrapers.base import BaseScraper

logger = logging.getLogger("pipeline.scraper.greenhouse")


class GreenhouseScraper(BaseScraper):
    """Scrapes job postings from Greenhouse public board API."""

    def scrape_board(self, token: str) -> List[RawJobPosting]:
        """Scrape all active jobs for a specific company token on Greenhouse."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        logger.info(f"Scraping Greenhouse board: {token} from {url}")

        response = self.fetch_url(url)
        if not response or response.status_code != 200:
            logger.warning(f"Could not retrieve Greenhouse board for {token} (status {response.status_code if response else 'None'})")
            return []

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse Greenhouse JSON for {token}: {e}")
            return []

        jobs = data.get("jobs", [])
        logger.info(f"Retrieved {len(jobs)} raw postings for Greenhouse token: {token}")

        raw_postings: List[RawJobPosting] = []
        for job in jobs:
            job_id = str(job.get("id", ""))
            title = job.get("title", "").strip()
            absolute_url = job.get("absolute_url", "")
            
            # Location
            loc_obj = job.get("location")
            loc_name = loc_obj.get("name") if isinstance(loc_obj, dict) else str(loc_obj or "")
            
            # HTML content in JSON
            content_html = job.get("content", "")
            plain_text = self._html_to_clean_text(content_html)
            updated_at = job.get("updated_at")

            raw_postings.append(
                RawJobPosting(
                    source_name="greenhouse",
                    source_id=f"greenhouse_{token}_{job_id}",
                    source_url=absolute_url,
                    company_raw=token.capitalize(),
                    title_raw=title,
                    location_raw=loc_name,
                    body_raw=plain_text,
                    published_raw=updated_at,
                )
            )

        return raw_postings

    def scrape_all(self, tokens: List[str]) -> List[RawJobPosting]:
        """Scrape all configured Greenhouse tokens."""
        all_postings: List[RawJobPosting] = []
        for token in tokens:
            try:
                board_postings = self.scrape_board(token)
                all_postings.extend(board_postings)
            except Exception as e:
                logger.error(f"Error scraping Greenhouse board {token}: {e}", exc_info=True)
        return all_postings

    @staticmethod
    def _html_to_clean_text(raw_html: str) -> str:
        """Strip HTML tags while preserving structure, headings, and lists."""
        if not raw_html:
            return ""
        # Unescape HTML entities first
        unescaped = html.unescape(raw_html)
        soup = BeautifulSoup(unescaped, "html.parser")
        
        # Replace list items with bullet text
        for li in soup.find_all("li"):
            li.insert_before("\n• ")
        for br in soup.find_all(["br", "p", "div", "h1", "h2", "h3", "h4"]):
            br.insert_before("\n")

        text = soup.get_text()
        # Collapse excessive newlines
        lines = [line.strip() for line in text.splitlines()]
        clean_lines = [line for line in lines if line]
        return "\n".join(clean_lines)
