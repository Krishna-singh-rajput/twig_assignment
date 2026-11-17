"""Scraper for Hacker News 'Who is hiring?' Monthly Thread (Source C)."""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from pipeline.models import RawJobPosting
from pipeline.scrapers.base import BaseScraper

logger = logging.getLogger("pipeline.scraper.hackernews")


class HackerNewsScraper(BaseScraper):
    """Scrapes Hacker News 'Who is hiring?' threads by parsing raw HTML."""

    BASE_URL = "https://news.ycombinator.com/"
    SUBMITTED_URL = "https://news.ycombinator.com/submitted?id=whoishiring"

    def find_latest_hiring_thread(self) -> Optional[Tuple[str, str]]:
        """Find the item ID and title of the latest 'Ask HN: Who is hiring?' thread."""
        logger.info(f"Looking up latest 'Who is hiring?' thread from {self.SUBMITTED_URL}")
        response = self.fetch_url(self.SUBMITTED_URL)
        if not response or response.status_code != 200:
            logger.error("Failed to fetch whoishiring submissions page")
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        for a_tag in soup.find_all("a"):
            title = a_tag.get_text(strip=True)
            if "Ask HN: Who is hiring?" in title:
                href = a_tag.get("href", "")
                match = re.search(r"id=(\d+)", href)
                if match:
                    item_id = match.group(1)
                    logger.info(f"Identified current hiring thread: '{title}' (item {item_id})")
                    return item_id, title

        logger.warning("Could not identify an 'Ask HN: Who is hiring?' thread in submissions.")
        return None

    def scrape_thread(self, item_id: str, max_pages: int = 5) -> List[RawJobPosting]:
        """Scrape all top-level comments from an HN hiring thread, traversing pagination."""
        raw_postings: List[RawJobPosting] = []
        page_url = f"{self.BASE_URL}item?id={item_id}"
        current_page = 1

        while page_url and current_page <= max_pages:
            logger.info(f"Fetching HN hiring page {current_page}: {page_url}")
            response = self.fetch_url(page_url)
            if not response or response.status_code != 200:
                logger.warning(f"Could not load HN thread page {page_url}")
                break

            soup = BeautifulSoup(response.text, "html.parser")
            comtrs = soup.find_all("tr", class_="athing comtr")
            logger.info(f"Page {current_page} has {len(comtrs)} comment rows")

            for tr in comtrs:
                # Top level comments have an indent img with width="0" or no indent
                ind = tr.find("td", class_="ind")
                is_top_level = False
                if ind:
                    img = ind.find("img")
                    if img and img.get("width") == "0":
                        is_top_level = True
                else:
                    is_top_level = True

                if not is_top_level:
                    continue

                comment_id = tr.get("id", "")
                commtext = tr.find("div", class_="commtext")
                if not commtext:
                    continue

                full_comment_text = commtext.get_text(separator="\n").strip()
                if not full_comment_text:
                    continue

                # Header line typically contains: Company | Role | Location | Remote/Onsite | Salary
                lines = [line.strip() for line in full_comment_text.splitlines() if line.strip()]
                header_line = lines[0] if lines else ""

                company_hint, title_hint, location_hint = self._parse_header_hints(header_line)

                item_url = f"{self.BASE_URL}item?id={comment_id}"

                raw_postings.append(
                    RawJobPosting(
                        source_name="hackernews",
                        source_id=f"hn_{comment_id}",
                        source_url=item_url,
                        company_raw=company_hint or "Unknown Company",
                        title_raw=title_hint or header_line[:60],
                        location_raw=location_hint,
                        body_raw=full_comment_text,
                        published_raw=None,
                    )
                )

            # Check for 'More' pagination link
            morelink = soup.find("a", class_="morelink")
            if morelink and morelink.get("href"):
                next_href = morelink.get("href")
                page_url = urljoin(self.BASE_URL, next_href)
                current_page += 1
            else:
                break

        logger.info(f"Total top-level postings scraped from HN: {len(raw_postings)}")
        return raw_postings

    @staticmethod
    def _parse_header_hints(header: str) -> Tuple[str, str, Optional[str]]:
        """Extract preliminary company, title, and location hints from HN comment header line,
        robustly handling arbitrary pipe ordering (Company | Location | Role vs Company | Role | Location).
        """
        # Split on pipes or spaced em/en-dashes, avoiding word-hyphens like in-house
        parts = [p.strip() for p in re.split(r"\s*\|\s*|\s+[–—]\s+", header) if p.strip()]
        if not parts:
            return "", "", None

        company = re.sub(r"https?://\S+", "", parts[0]).strip()
        title = ""
        location = ""

        # Identify location and role parts dynamically
        for p in parts[1:]:
            p_low = p.lower()
            if any(k in p_low for k in ["remote", "hybrid", "onsite", "in-office", "san francisco", "nyc", "new york", "seattle", "boston", "austin", "chicago", "ca", "il", "ny", "wa", "tx", "us", "usa", "europe", "uk"]):
                if not location and not any(r in p_low for r in ["engineer", "developer", "lead"]):
                    location = p
                    continue
            if any(k in p_low for k in ["engineer", "developer", "architect", "scientist", "analyst", "manager", "lead", "intern", "roles", "head of"]):
                if not title:
                    title = p
                    continue
            if not location:
                location = p
            elif not title:
                title = p

        return company, title or (parts[1] if len(parts) > 1 else ""), location or None

    def scrape_latest(self) -> List[RawJobPosting]:
        """Convenience method to locate and scrape the latest hiring thread."""
        thread_info = self.find_latest_hiring_thread()
        if not thread_info:
            return []
        item_id, _ = thread_info
        return self.scrape_thread(item_id)
