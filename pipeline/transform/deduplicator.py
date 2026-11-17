"""Deduplication and canonical merging across multiple job posting sources."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple

from pipeline.models import JobPosting, SeniorityLevel
from pipeline.transform.normalizer import DataNormalizer

logger = logging.getLogger("pipeline.transform.deduplicator")


class JobDeduplicator:
    """Identifies duplicate job postings across Greenhouse, Lever, and Hacker News
    and merges them into a single canonical record with preserved source links.
    """

    @staticmethod
    def _title_tokens(title: str) -> Set[str]:
        """Extract clean alphanumeric lowercase tokens from title."""
        cleaned = re.sub(r"[^\w\s]", " ", title.lower())
        tokens = set(cleaned.split())
        # Remove noisy stopwords
        stopwords = {"and", "or", "the", "for", "in", "at", "to", "of", "with", "a", "an"}
        return tokens - stopwords

    @classmethod
    def are_same_role(cls, a: JobPosting, b: JobPosting) -> bool:
        """Evaluate if two postings represent the identical role across sources."""
        # 1. Company check: Must match normalized company name
        norm_comp_a = DataNormalizer.normalize_company(a.company).lower()
        norm_comp_b = DataNormalizer.normalize_company(b.company).lower()
        if norm_comp_a != norm_comp_b:
            return False

        # 2. Guardrail check: Different core roles must NEVER be merged!
        # E.g. Data Engineer vs Machine Learning Engineer vs Analytics Engineer
        role_type_a = cls._classify_core_role(a.title)
        role_type_b = cls._classify_core_role(b.title)
        if role_type_a != role_type_b:
            return False

        # 3. Guardrail check: Explicitly different seniority tiers shouldn't merge
        # E.g. Junior Data Engineer should not merge with Staff/Principal Data Engineer
        if a.seniority and b.seniority:
            if a.seniority == SeniorityLevel.junior and b.seniority in (SeniorityLevel.senior, SeniorityLevel.staff_plus):
                return False
            if a.seniority == SeniorityLevel.staff_plus and b.seniority in (SeniorityLevel.junior, SeniorityLevel.mid):
                return False

        # 4. Location check: If both have explicit different cities and neither is remote
        if a.city and b.city and a.remote_policy != "remote" and b.remote_policy != "remote":
            if a.city.lower() != b.city.lower():
                return False

        # 5. Title similarity: Compare normalized title tokens and sequence similarity
        norm_title_a = DataNormalizer.normalize_title(a.title)
        norm_title_b = DataNormalizer.normalize_title(b.title)

        tokens_a = cls._title_tokens(norm_title_a)
        tokens_b = cls._title_tokens(norm_title_b)

        # Jaccard similarity of title tokens
        if not tokens_a or not tokens_b:
            return False
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        seq_ratio = SequenceMatcher(None, norm_title_a.lower(), norm_title_b.lower()).ratio()

        # If high title token overlap (e.g. "Senior Data Engineer" vs "Senior Data Engineer, Platform")
        # Example from specification: "Sr. Data Engineer" vs "Senior Data Engineer, Platform"
        if jaccard >= 0.5 or seq_ratio >= 0.70:
            return True

        # Special check for specification example: one title is substring of another
        if norm_title_a.lower() in norm_title_b.lower() or norm_title_b.lower() in norm_title_a.lower():
            return True

        return False

    @staticmethod
    def _classify_core_role(title: str) -> str:
        """Classify title into primary role category to avoid incorrect merging."""
        t = title.lower()
        if "machine learning" in t or "ml engineer" in t or "mlops" in t or "ai engineer" in t:
            return "ml_engineer"
        if "analytics engineer" in t or "bi engineer" in t:
            return "analytics_engineer"
        if "platform engineer" in t or "infrastructure engineer" in t:
            return "platform_engineer"
        if "data engineer" in t or "big data" in t or "data warehouse" in t or "etl" in t:
            return "data_engineer"
        return "general_engineer"

    @classmethod
    def merge_postings(cls, primary: JobPosting, secondary: JobPosting) -> JobPosting:
        """Merge two duplicate postings into one canonical record, preserving all source links."""
        # Canonical title preference: prefer ATS titles or the more descriptive title
        chosen_title = primary.title
        if len(secondary.title) > len(primary.title) and "http" not in secondary.title:
            chosen_title = secondary.title

        # Combine source URLs
        merged_urls = list(dict.fromkeys(primary.source_urls + secondary.source_urls))

        # Union skills
        combined_skills = list(dict.fromkeys(primary.skills + secondary.skills))

        # Merge evidence dictionaries
        merged_evidence = dict(secondary.evidence)
        merged_evidence.update(primary.evidence)

        # Reconcile salary: retain whichever has stated salary
        sal_min = primary.salary_min if primary.salary_min is not None else secondary.salary_min
        sal_max = primary.salary_max if primary.salary_max is not None else secondary.salary_max
        curr = primary.currency or secondary.currency

        # Reconcile enums & attributes (favor non-null)
        seniority = primary.seniority or secondary.seniority
        city = primary.city or secondary.city
        country = primary.country or secondary.country
        remote_policy = primary.remote_policy or secondary.remote_policy
        employment_type = primary.employment_type or secondary.employment_type
        visa_sponsorship = primary.visa_sponsorship if primary.visa_sponsorship is not None else secondary.visa_sponsorship
        posted_date = primary.posted_date or secondary.posted_date

        first_seen = min(primary.first_seen, secondary.first_seen)
        last_seen = max(primary.last_seen, secondary.last_seen)

        # Deterministic posting ID
        posting_id = primary.posting_id or JobPosting.generate_posting_id(
            primary.company, chosen_title, city, str(remote_policy)
        )

        return JobPosting(
            posting_id=posting_id,
            company=DataNormalizer.normalize_company(primary.company),
            title=chosen_title,
            seniority=seniority,
            city=city,
            country=country,
            remote_policy=remote_policy,
            salary_min=sal_min,
            salary_max=sal_max,
            currency=curr,
            employment_type=employment_type,
            skills=combined_skills,
            visa_sponsorship=visa_sponsorship,
            posted_date=posted_date,
            status=primary.status,
            source_urls=merged_urls,
            evidence=merged_evidence,
            first_seen=first_seen,
            last_seen=last_seen,
        )

    @classmethod
    def deduplicate(cls, postings: List[JobPosting]) -> List[JobPosting]:
        """Perform cross-source deduplication across a list of job postings."""
        if not postings:
            return []

        canonical_records: List[JobPosting] = []

        for posting in postings:
            matched_index = -1
            for idx, existing in enumerate(canonical_records):
                if cls.are_same_role(existing, posting):
                    matched_index = idx
                    break

            if matched_index >= 0:
                # Merge into existing record
                merged = cls.merge_postings(canonical_records[matched_index], posting)
                canonical_records[matched_index] = merged
                logger.debug(
                    f"Deduplicated: merged '{posting.title}' ({posting.source_urls}) into "
                    f"'{merged.title}' ({merged.company})"
                )
            else:
                canonical_records.append(posting)

        logger.info(f"Deduplication complete: {len(postings)} input postings reduced to {len(canonical_records)} canonical postings.")
        return canonical_records
