"""Scraper for Lever Job Boards (Source B)."""

from __future__ import annotations

import datetime
import logging
from typing import List, Optional

from pipeline.models import RawJobPosting
from pipeline.scrapers.base import BaseScraper

logger = logging.getLogger("pipeline.scraper.lever")


class LeverScraper(BaseScraper):
    """Scrapes job postings from Lever public postings API."""

    def scrape_site(self, site: str) -> List[RawJobPosting]:
        """Scrape active postings for a company on Lever."""
        url = f"https://api.lever.co/v0/postings/{site}?mode=json"
        logger.info(f"Scraping Lever site: {site} from {url}")

        response = self.fetch_url(url)
        if not response or response.status_code != 200:
            logger.warning(f"Could not retrieve Lever site {site} (status {response.status_code if response else 'None'})")
            return []

        # Specification requirement: check content-type
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" not in content_type and "json" not in content_type:
            logger.warning(f"Lever endpoint for {site} returned non-JSON content-type: {content_type}")
            return []

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse Lever JSON for {site}: {e}")
            return []

        if not isinstance(data, list):
            logger.warning(f"Unexpected response structure for Lever {site}, expected list but got {type(data)}")
            return []

        logger.info(f"Retrieved {len(data)} raw postings for Lever site: {site}")
        raw_postings: List[RawJobPosting] = []

        for item in data:
            if not isinstance(item, dict):
                continue

            posting_id = str(item.get("id", ""))
            title = item.get("text", "").strip()
            hosted_url = item.get("hostedUrl", "")
            
            # Categories: location, team, department, commitment
            categories = item.get("categories", {}) or {}
            location = categories.get("location", "")
            commitment = categories.get("commitment", "")

            # Assemble full body from descriptionPlain, lists, and additionalPlain
            body_parts: List[str] = []
            
            desc_plain = item.get("descriptionPlain", "").strip()
            if desc_plain:
                body_parts.append(desc_plain)

            lists = item.get("lists", []) or []
            for l in lists:
                list_title = l.get("text", "")
                list_content = l.get("content", "")
                if list_title:
                    body_parts.append(f"\n{list_title}:")
                if list_content:
                    body_parts.append(list_content)

            additional_plain = item.get("additionalPlain", "").strip()
            if additional_plain:
                body_parts.append(f"\nAdditional Details:\n{additional_plain}")

            full_body = "\n\n".join(body_parts)

            # Date handling (created_at in ms)
            created_at_ms = item.get("createdAt")
            published_str = None
            if created_at_ms:
                try:
                    dt = datetime.datetime.fromtimestamp(created_at_ms / 1000.0, tz=datetime.timezone.utc)
                    published_str = dt.isoformat()
                except Exception:
                    pass

            raw_postings.append(
                RawJobPosting(
                    source_name="lever",
                    source_id=f"lever_{site}_{posting_id}",
                    source_url=hosted_url,
                    company_raw=site.capitalize(),
                    title_raw=title,
                    location_raw=f"{location} ({commitment})" if commitment else location,
                    body_raw=full_body,
                    published_raw=published_str,
                )
            )

        return raw_postings

    def scrape_all(self, sites: List[str]) -> List[RawJobPosting]:
        """Scrape all configured Lever sites."""
        all_postings: List[RawJobPosting] = []
        for site in sites:
            try:
                site_postings = self.scrape_site(site)
                all_postings.extend(site_postings)
            except Exception as e:
                logger.error(f"Error scraping Lever site {site}: {e}", exc_info=True)
        return all_postings
