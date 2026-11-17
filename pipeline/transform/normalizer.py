"""Normalization module for company names, job titles, seniority, and salaries."""

from __future__ import annotations

import re
from typing import Optional, Tuple
from pipeline.models import EmploymentType, RemotePolicy, SeniorityLevel


COMPANY_LEGAL_SUFFIXES = [
    r",?\s+inc\.?$",
    r",?\s+llc\.?$",
    r",?\s+corp\.?$",
    r",?\s+corporation\.?$",
    r",?\s+co\.?$",
    r",?\s+ltd\.?$",
    r",?\s+technologies\.?$",
    r",?\s+tech\.?$",
    r",?\s+labs\.?$",
    r",?\s+group\.?$",
    r",?\s+usa\.?$",
]

KNOWN_COMPANY_MAP = {
    "stripe": "Stripe",
    "stripe inc": "Stripe",
    "stripe, inc.": "Stripe",
    "airbnb": "Airbnb",
    "databricks": "Databricks",
    "databricks inc": "Databricks",
    "databricks inc.": "Databricks",
    "figma": "Figma",
    "palantir": "Palantir",
    "palantir technologies": "Palantir",
    "spotify": "Spotify",
    "spotify ab": "Spotify",
    "plaid": "Plaid",
    "wealthfront": "Wealthfront",
    "prior labs": "Prior Labs",
    "cnh": "CNH",
    "cern": "CERN",
    "hestus": "Hestus",
    "epsilon": "Epsilon",
    "estuary": "Estuary",
    "baton": "Baton",
    "sumble": "Sumble",
    "peregrine": "Peregrine",
    "quantum rise": "Quantum Rise",
    "genentech": "Genentech",
    "credit genie": "Credit Genie",
    "ledgebrook": "Ledgebrook",
}


class DataNormalizer:
    """Normalizes unstructured fields into clean canonical values."""

    @classmethod
    def normalize_company(cls, raw_company: str) -> str:
        """Strip legal suffixes and map to canonical company name."""
        if not raw_company:
            return "Unknown"

        cleaned = raw_company.strip()
        cleaned = re.sub(r"^https?://(www\.)?", "", cleaned)
        cleaned = re.sub(r"/.*$", "", cleaned)

        cleaned_lower = cleaned.lower()
        if cleaned_lower in KNOWN_COMPANY_MAP:
            return KNOWN_COMPANY_MAP[cleaned_lower]

        for suffix_pat in COMPANY_LEGAL_SUFFIXES:
            cleaned = re.sub(suffix_pat, "", cleaned, flags=re.IGNORECASE).strip()

        cleaned_lower = cleaned.lower()
        if cleaned_lower in KNOWN_COMPANY_MAP:
            return KNOWN_COMPANY_MAP[cleaned_lower]

        if cleaned.islower() or (cleaned.isupper() and len(cleaned) > 4):
            return cleaned.title()

        return cleaned

    @classmethod
    def normalize_title(cls, raw_title: str) -> str:
        """Clean title of parentheticals, standardize abbreviations (e.g. Sr. -> Senior)."""
        if not raw_title:
            return "Data Engineer"

        title = raw_title.strip()
        title = re.sub(r"\s*[\(\[][^\)\]]*(?:remote|hybrid|onsite|ny|ca|sf|us|usa|full-time)[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*\|\s*(?:remote|hybrid|onsite|us|usa|san francisco|new york).*$", "", title, flags=re.IGNORECASE)

        title = re.sub(r"\bSr\.?\s+", "Senior ", title, flags=re.IGNORECASE)
        title = re.sub(r"\bJr\.?\s+", "Junior ", title, flags=re.IGNORECASE)
        title = re.sub(r"\bML\s+", "Machine Learning ", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" -|,")

        return title

    @classmethod
    def extract_seniority(cls, title: str, body: str = "") -> Tuple[Optional[SeniorityLevel], Optional[str]]:
        """Determine seniority level and source evidence snippet."""
        text = f"{title}\n{body[:400]}".lower()

        # Staff+ indicators
        staff_patterns = [
            (r"\b(staff|principal|distinguished|director|architect|head of)\b", SeniorityLevel.staff_plus),
            (r"\b(senior staff)\b", SeniorityLevel.staff_plus),
        ]
        for pat, level in staff_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return level, m.group(0)

        # Senior indicators
        senior_patterns = [
            (r"\b(senior|lead|sr\.?|iii|iv)\b", SeniorityLevel.senior),
        ]
        for pat, level in senior_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return level, m.group(0)

        # Junior indicators
        junior_patterns = [
            (r"\b(junior|jr\.?|associate|entry level|graduate|intern|internship|interns)\b", SeniorityLevel.junior),
        ]
        for pat, level in junior_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return level, m.group(0)

        # Mid-level indicators (explicit or standard un-prefixed role)
        if re.search(r"\b(mid|mid-level|level ii|ii)\b", text, re.IGNORECASE):
            m = re.search(r"\b(mid|mid-level|level ii|ii)\b", text, re.IGNORECASE)
            return SeniorityLevel.mid, m.group(0)

        # Standard unqualified title (e.g. "Data Engineer", "Machine Learning Engineer") -> mid
        if any(k in title.lower() for k in ["engineer", "developer", "analyst"]):
            return SeniorityLevel.mid, title

        return None, None

    @classmethod
    def extract_remote_policy(cls, location_str: str, body: str = "") -> Tuple[Optional[RemotePolicy], Optional[str]]:
        """Determine remote policy (onsite, hybrid, remote) and source evidence."""
        loc_lower = (location_str or "").lower()
        body_intro = (body or "")[:500].lower()

        # Check location string first (highest precision)
        if "hybrid" in loc_lower or "hybrid" in body_intro:
            m = re.search(r"\b(hybrid|flexible)\b", f"{loc_lower} {body_intro}")
            return RemotePolicy.hybrid, m.group(0) if m else "hybrid"

        if any(term in loc_lower for term in ["onsite", "on-site", "in-office", "in office"]):
            m = re.search(r"\b(onsite|on-site|in-office|in office)\b", loc_lower)
            return RemotePolicy.onsite, m.group(0) if m else "onsite"

        if "remote" in loc_lower:
            m = re.search(r"\b(remote|work from home|wfh|distributed)\b", loc_lower)
            return RemotePolicy.remote, m.group(0) if m else "remote"

        # Check body text
        if any(term in body_intro for term in ["onsite", "on-site", "in-office", "in office", "must work onsite", "onsite in"]):
            m = re.search(r"\b(onsite|on-site|in-office|in office|must work onsite)\b", body_intro)
            return RemotePolicy.onsite, m.group(0) if m else "onsite"

        if re.search(r"\b(work anywhere in the us|remote eligible|remote within|remote role|100% remote)\b", body_intro):
            m = re.search(r"\b(work anywhere in the us|remote eligible|remote within|remote role|100% remote)\b", body_intro)
            return RemotePolicy.remote, m.group(0) if m else "remote"

        if re.search(r"\b(remote|work from home|wfh)\b", body_intro):
            m = re.search(r"\b(remote|work from home|wfh)\b", body_intro)
            return RemotePolicy.remote, m.group(0) if m else "remote"

        # If a physical city is specified without remote mentions, default to onsite
        if loc_lower and any(c in loc_lower for c in ["san francisco", "new york", "seattle", "mountain view", "chicago", "boston", "nyc", "tempe"]):
            return RemotePolicy.onsite, location_str

        return None, None

    @classmethod
    def extract_employment_type(cls, text: str) -> Tuple[Optional[EmploymentType], Optional[str]]:
        """Determine employment type and source evidence."""
        t_lower = text[:2500].lower()
        if re.search(r"\b(intern|internship|summer intern|co-op)\b", t_lower):
            m = re.search(r"\b(intern|internship|summer intern|co-op)\b", t_lower)
            return EmploymentType.intern, m.group(0) if m else "intern"

        if re.search(r"\b(contract|contractor|temp|part-time|part time)\b", t_lower):
            m = re.search(r"\b(contract|contractor|temp|part-time|part time)\b", t_lower)
            return EmploymentType.contract, m.group(0) if m else "contract"

        if re.search(r"\b(full-time|full time|permanent|regular full-time)\b", t_lower):
            m = re.search(r"\b(full-time|full time|permanent|regular full-time)\b", t_lower)
            return EmploymentType.full_time, m.group(0) if m else "full_time"

        if any(term in t_lower for term in ["annual base salary", "base pay range", "salary range", "health benefits", "401k"]):
            return EmploymentType.full_time, "annual base salary"

        return None, None

    @classmethod
    def extract_salary_range(cls, text: str) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
        """Extract salary_min, salary_max, currency, and evidence snippet."""
        if not text:
            return None, None, None, None

        range_pattern = re.compile(
            r"(\$|USD\s*)\s*([0-9]{2,3}(?:,[0-9]{3})*|[0-9]{2,3})\s*(k|K)?\s*(?:-|–|—|to|and)\s*(\$|USD\s*)?\s*([0-9]{2,3}(?:,[0-9]{3})*|[0-9]{2,3})\s*(k|K)?\s*(USD)?\s*(?:(?:per\s+year|/yr|/year|annually|a\s+year)|(?:per\s+hour|/hr|/hour))?",
            re.IGNORECASE,
        )

        for match in range_pattern.finditer(text):
            evidence_snippet = match.group(0).strip()
            val1_str = match.group(2).replace(",", "")
            is_k1 = bool(match.group(3))
            val2_str = match.group(5).replace(",", "")
            is_k2 = bool(match.group(6))

            try:
                v1 = float(val1_str)
                v2 = float(val2_str)
            except ValueError:
                continue

            if is_k1 or (v1 < 1000 and not is_k1 and is_k2):
                v1 *= 1000
            elif v1 < 500 and ("hour" in evidence_snippet.lower() or "/hr" in evidence_snippet.lower()):
                v1 *= 2080

            if is_k2 or (v2 < 1000 and is_k1 and not is_k2):
                v2 *= 1000
            elif v2 < 500 and ("hour" in evidence_snippet.lower() or "/hr" in evidence_snippet.lower()):
                v2 *= 2080

            if 30000 <= v1 <= 1500000 and 30000 <= v2 <= 1500000:
                s_min = min(v1, v2)
                s_max = max(v1, v2)
                return s_min, s_max, "USD", evidence_snippet

        single_pattern = re.compile(
            r"(?:salary|compensation|base|pay|at)?\s*(?:is|of|:)?\s*(\$|USD\s*)\s*([0-9]{2,3}(?:,[0-9]{3})*|[0-9]{2,3})\s*(k|K)?\s*(USD)?\s*(?:(?:per\s+year|/yr|/year|annually|/hour|/hr))?",
            re.IGNORECASE,
        )
        for match in single_pattern.finditer(text):
            evidence_snippet = match.group(0).strip()
            val_str = match.group(2).replace(",", "")
            is_k = bool(match.group(3))
            try:
                v = float(val_str)
            except ValueError:
                continue

            if is_k or (v < 1000 and "k" in evidence_snippet.lower()):
                v *= 1000
            elif v < 500 and ("hour" in evidence_snippet.lower() or "/hr" in evidence_snippet.lower()):
                v *= 2080

            if 30000 <= v <= 1500000:
                return v, v, "USD", evidence_snippet

        return None, None, None, None

    @classmethod
    def extract_skills(cls, text: str) -> Tuple[list[str], dict[str, str]]:
        """Extract explicit technical skills mentioned in the posting."""
        common_tech = [
            "Python", "SQL", "Spark", "PySpark", "Kafka", "dbt", "Airflow", "Snowflake",
            "Databricks", "AWS", "GCP", "Azure", "PostgreSQL", "Kubernetes", "Docker",
            "Scala", "Java", "Go", "Rust", "Flink", "Hadoop", "Presto", "Trino", "BigQuery",
            "Redshift", "ClickHouse", "Terraform", "Git", "CI/CD", "Linux", "TensorFlow",
            "PyTorch", "scikit-learn", "MLflow", "Kubeflow", "Pandas", "Polars", "FastAPI",
            "Ray", "CUDA"
        ]

        found_skills = []
        evidence_snippets = {}
        for skill in common_tech:
            pattern = re.compile(rf"\b{re.escape(skill)}\b", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                found_skills.append(skill)
                start = max(0, match.start() - 20)
                end = min(len(text), match.end() + 20)
                evidence_snippets[skill] = text[start:end].strip().replace("\n", " ")

        return found_skills, evidence_snippets
