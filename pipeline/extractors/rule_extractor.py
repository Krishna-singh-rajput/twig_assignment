"""Deterministic, high-accuracy rule & pattern extractor for offline/fallback execution."""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional, Tuple

from pipeline.extractors.base import BaseExtractor, ExtractionResult
from pipeline.models import ExtractedJobFields, RawJobPosting
from pipeline.transform.normalizer import DataNormalizer

logger = logging.getLogger("pipeline.extractors.rule")


class RuleBasedExtractor(BaseExtractor):
    """Deterministic extractor enforcing the strict target schema and evidence tracking
    without requiring third-party API keys or incurring token costs.
    """

    US_CITIES_MAP = {
        "san francisco": ("San Francisco", "USA"),
        "sf": ("San Francisco", "USA"),
        "bay area": ("San Francisco Bay Area", "USA"),
        "new york": ("New York", "USA"),
        "nyc": ("New York", "USA"),
        "seattle": ("Seattle", "USA"),
        "austin": ("Austin", "USA"),
        "boston": ("Boston", "USA"),
        "chicago": ("Chicago", "USA"),
        "los angeles": ("Los Angeles", "USA"),
        "la": ("Los Angeles", "USA"),
        "denver": ("Denver", "USA"),
        "san jose": ("San Jose", "USA"),
        "sunnyvale": ("Sunnyvale", "USA"),
        "mountain view": ("Mountain View", "USA"),
        "palo alto": ("Palo Alto", "USA"),
        "atlanta": ("Atlanta", "USA"),
        "portland": ("Portland", "USA"),
        "san diego": ("San Diego", "USA"),
    }

    def extract(self, posting: RawJobPosting) -> ExtractionResult:
        start_time = time.time()
        evidence: Dict[str, str] = {}

        # 1. Company
        norm_company = DataNormalizer.normalize_company(posting.company_raw)
        evidence["company"] = posting.company_raw

        # 2. Title
        norm_title = DataNormalizer.normalize_title(posting.title_raw)
        evidence["title"] = posting.title_raw

        # 3. Seniority
        combined_text = f"{posting.title_raw}\n{posting.body_raw[:800]}"
        seniority, sen_snippet = DataNormalizer.extract_seniority(norm_title, posting.body_raw)
        if seniority and sen_snippet:
            evidence["seniority"] = sen_snippet

        # 4. Remote Policy
        loc_text = f"{posting.location_raw or ''} {posting.body_raw[:600]}"
        remote_policy, rem_snippet = DataNormalizer.extract_remote_policy(posting.location_raw or "", posting.body_raw)
        if remote_policy and rem_snippet:
            evidence["remote_policy"] = rem_snippet

        # 5. Location (City, Country)
        city, country, loc_snippet = self._extract_location(posting.location_raw, posting.body_raw)
        if city:
            evidence["city"] = loc_snippet
        if country:
            evidence["country"] = loc_snippet

        # 6. Salary
        sal_min, sal_max, currency, sal_snippet = DataNormalizer.extract_salary_range(posting.body_raw)
        if sal_min is not None:
            evidence["salary_min"] = sal_snippet
        if sal_max is not None:
            evidence["salary_max"] = sal_snippet

        # 7. Employment Type
        emp_type, emp_snippet = DataNormalizer.extract_employment_type(f"{posting.title_raw} {posting.location_raw or ''} {posting.body_raw[:500]}")
        if emp_type and emp_snippet:
            evidence["employment_type"] = emp_snippet

        # 8. Visa Sponsorship (null if not stated!)
        visa_sponsorship, visa_snippet = self._extract_visa_sponsorship(posting.body_raw)
        if visa_sponsorship is not None and visa_snippet:
            evidence["visa_sponsorship"] = visa_snippet

        # 9. Skills
        skills, skill_evidence = DataNormalizer.extract_skills(posting.body_raw)
        for s in skills[:5]:  # store evidence for primary skills
            if s in skill_evidence:
                evidence[f"skill_{s.lower()}"] = skill_evidence[s]

        # Assemble Pydantic model
        fields = ExtractedJobFields(
            company=norm_company,
            title=norm_title,
            seniority=seniority,
            city=city,
            country=country,
            remote_policy=remote_policy,
            salary_min=sal_min,
            salary_max=sal_max,
            currency=currency,
            employment_type=emp_type,
            skills=skills,
            visa_sponsorship=visa_sponsorship,
            posted_date=None,
            evidence=evidence,
        )

        latency = time.time() - start_time
        return ExtractionResult(
            fields=fields,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0.0,
            latency_seconds=latency,
            model_used="rule-based",
        )

    def _extract_location(self, loc_raw: Optional[str], body: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract city and country only if stated in text."""
        target_text = f"{loc_raw or ''}\n{body[:500]}".lower()

        for key, (city_val, country_val) in self.US_CITIES_MAP.items():
            pattern = re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE)
            m = pattern.search(target_text)
            if m:
                snippet = m.group(0)
                return city_val, country_val, snippet

        if loc_raw and "united states" in loc_raw.lower() or "us" in (loc_raw or "").lower():
            return None, "USA", loc_raw

        return None, None, None

    @staticmethod
    def _extract_visa_sponsorship(body: str) -> Tuple[Optional[bool], Optional[str]]:
        """Extract visa sponsorship strictly if stated; otherwise null."""
        text = body.lower()

        # Negative indicators
        neg_patterns = [
            r"\b(no\s+visa\s+sponsorship)\b",
            r"\b(cannot\s+sponsor)\b",
            r"\b(not\s+offering\s+sponsorship)\b",
            r"\b(unable\s+to\s+sponsor)\b",
            r"\b(without\s+the\s+need\s+for\s+sponsorship)\b",
            r"\b(without\s+sponsorship)\b",
            r"\b(must\s+be\s+authorized\s+to\s+work\s+in\s+the\s+u\.?s\.?\s+without\s+sponsorship)\b",
        ]
        for pat in neg_patterns:
            m = re.search(pat, text)
            if m:
                return False, m.group(0)

        # Positive indicators
        pos_patterns = [
            r"\b(visa\s+sponsorship\s+available)\b",
            r"\b(we\s+sponsor\s+(?:h1-?b|visas?))\b",
            r"\b(willing\s+to\s+sponsor)\b",
            r"\b(sponsorship\s+provided)\b",
        ]
        for pat in pos_patterns:
            m = re.search(pat, text)
            if m:
                return True, m.group(0)

        # Null if not stated!
        return None, None
