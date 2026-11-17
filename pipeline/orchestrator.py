"""Pipeline orchestrator coordinating scraping, filtering, caching, extraction, dedup, and persistence."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

from pipeline.config import config
from pipeline.extractors.base import BaseExtractor
from pipeline.extractors.llm_extractor import LLMExtractor
from pipeline.models import JobPosting, RawJobPosting
from pipeline.scrapers.greenhouse import GreenhouseScraper
from pipeline.scrapers.hackernews import HackerNewsScraper
from pipeline.scrapers.lever import LeverScraper
from pipeline.storage.database import DatabaseManager
from pipeline.transform.deduplicator import JobDeduplicator
from pipeline.transform.filter import JobFilter

logger = logging.getLogger("pipeline.orchestrator")


class PipelineOrchestrator:
    """Coordinates the full end-to-end data engineering lifecycle."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        extractor: Optional[BaseExtractor] = None,
    ) -> None:
        self.db = db_manager or DatabaseManager(config.db_path)
        self.extractor = extractor or LLMExtractor()

    def run(
        self,
        sources: Optional[List[str]] = None,
        max_postings_per_source: Optional[int] = None,
        skip_scrape: bool = False,
    ) -> Dict[str, int]:
        """Execute the full data pipeline.
        
        Stages:
        1. Polite scraping from Greenhouse, Lever, and Hacker News
        2. Domain pre-filtering (Data/ML in US / Remote)
        3. Raw payload hashing and cache checking
        4. Structured extraction (LLM / rules) with evidence grounding
        5. Cross-source fuzzy deduplication and canonical merging
        6. Idempotent storage upsert & change history recording
        7. CSV, JSON, and DuckDB exports
        """
        sources_to_run = [s.lower() for s in (sources or ["greenhouse", "lever", "hackernews"])]
        limit = max_postings_per_source or config.max_postings_per_source

        all_raw_postings: List[RawJobPosting] = []

        # ================= STAGE 1: SCRAPING =================
        if not skip_scrape:
            logger.info("=== STAGE 1: SCRAPING SOURCES ===")
            if "greenhouse" in sources_to_run:
                try:
                    with GreenhouseScraper(user_agent=config.user_agent, request_delay=config.request_delay_seconds) as gh:
                        gh_postings = gh.scrape_all(config.greenhouse_tokens)
                        logger.info(f"Greenhouse raw postings collected: {len(gh_postings)}")
                        all_raw_postings.extend(gh_postings)
                except Exception as e:
                    logger.error(f"Error during Greenhouse scraping: {e}", exc_info=True)

            if "lever" in sources_to_run:
                try:
                    with LeverScraper(user_agent=config.user_agent, request_delay=config.request_delay_seconds) as lever:
                        # Scrape configured Lever sites (Palantir, Spotify, and gracefully test Plaid)
                        lever_sites = config.lever_sites + config.lever_fallback_sites
                        lever_postings = lever.scrape_all(lever_sites)
                        logger.info(f"Lever raw postings collected: {len(lever_postings)}")
                        all_raw_postings.extend(lever_postings)
                except Exception as e:
                    logger.error(f"Error during Lever scraping: {e}", exc_info=True)

            if "hackernews" in sources_to_run:
                try:
                    with HackerNewsScraper(user_agent=config.user_agent, request_delay=config.request_delay_seconds) as hn:
                        hn_postings = hn.scrape_latest()
                        logger.info(f"Hacker News raw postings collected: {len(hn_postings)}")
                        all_raw_postings.extend(hn_postings)
                except Exception as e:
                    logger.error(f"Error during Hacker News scraping: {e}", exc_info=True)

        logger.info(f"Total raw postings scraped across sources: {len(all_raw_postings)}")

        # ================= STAGE 2: FILTERING =================
        logger.info("=== STAGE 2: FILTERING DATA/ML ROLES IN US/REMOTE ===")
        filtered_postings: List[RawJobPosting] = []
        for p in all_raw_postings:
            if JobFilter.should_keep(p):
                filtered_postings.append(p)

        logger.info(
            f"Filtered down to {len(filtered_postings)} postings meeting domain criteria "
            f"(Data/ML engineering in US/US-Remote)."
        )

        # Enforce source limit on filtered target postings
        if limit:
            filtered_postings = filtered_postings[:limit]

        # ================= STAGE 3: CACHING & EXTRACTION =================
        logger.info("=== STAGE 3: CACHING & STRUCTURED EXTRACTION ===")
        extracted_canonical_postings: List[JobPosting] = []
        cache_hits = 0
        cache_misses = 0

        for raw_p in filtered_postings:
            # Check raw payload cache
            is_cached = self.db.cache.is_cached_and_unchanged(raw_p)

            # Extract fields
            extraction_res = self.extractor.extract(raw_p)
            extracted = extraction_res.fields

            # Update cache
            self.db.cache.put(raw_p)
            if is_cached:
                cache_hits += 1
            else:
                cache_misses += 1

            # Build preliminary JobPosting
            posting_id = JobPosting.generate_posting_id(
                extracted.company, extracted.title, extracted.city, str(extracted.remote_policy)
            )

            job_p = JobPosting(
                posting_id=posting_id,
                company=extracted.company,
                title=extracted.title,
                seniority=extracted.seniority,
                city=extracted.city,
                country=extracted.country,
                remote_policy=extracted.remote_policy,
                salary_min=extracted.salary_min,
                salary_max=extracted.salary_max,
                currency=extracted.currency,
                employment_type=extracted.employment_type,
                skills=extracted.skills,
                visa_sponsorship=extracted.visa_sponsorship,
                posted_date=extracted.posted_date,
                source_urls=[raw_p.source_url],
                evidence=extracted.evidence,
            )
            extracted_canonical_postings.append(job_p)

        logger.info(f"Extraction complete: {cache_hits} cache hits, {cache_misses} new extractions.")

        # ================= STAGE 4: DEDUPLICATION =================
        logger.info("=== STAGE 4: MULTI-SOURCE DEDUPLICATION ===")
        canonical_postings = JobDeduplicator.deduplicate(extracted_canonical_postings)

        # ================= STAGE 5: PERSISTENCE & HISTORY =================
        logger.info("=== STAGE 5: PERSISTENCE & CHANGE AUDITING ===")
        inserted_count, updated_count = self.db.upsert_postings(canonical_postings)

        # Detect closed postings
        active_source_ids = {p.source_id for p in filtered_postings}
        active_source_ids.update(p.posting_id for p in canonical_postings)
        closed_count = 0
        for src in sources_to_run:
            closed_count += self.db.detect_and_close_missing(active_source_ids, src)

        # ================= STAGE 6: EXPORTS =================
        logger.info("=== STAGE 6: EXPORTS ===")
        self.db.export_csv(config.csv_output_path)
        self.db.export_json(config.json_output_path)
        self.db.export_duckdb(config.duckdb_path)

        stats = {
            "total_scraped": len(all_raw_postings),
            "filtered_kept": len(filtered_postings),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "canonical_postings": len(canonical_postings),
            "new_inserted": inserted_count,
            "existing_updated": updated_count,
            "marked_closed": closed_count,
        }

        logger.info(f"Pipeline run finished successfully: {stats}")
        return stats
