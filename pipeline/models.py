"""Data models and Pydantic schemas for the B2B Market Intelligence Job Pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class SeniorityLevel(str, Enum):
    """Seniority classification matching target schema."""
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff_plus = "staff_plus"


class RemotePolicy(str, Enum):
    """Remote work classification matching target schema."""
    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"


class EmploymentType(str, Enum):
    """Employment arrangement classification matching target schema."""
    full_time = "full_time"
    contract = "contract"
    intern = "intern"


class PostingStatus(str, Enum):
    """Lifecycle status of a job posting."""
    open = "open"
    closed = "closed"


class RawJobPosting(BaseModel):
    """Raw scraped posting from an ATS or website prior to normalization."""
    source_name: str  # "greenhouse", "lever", "hackernews"
    source_id: str    # ATS internal job id or HN comment id
    source_url: str
    company_raw: str
    title_raw: str
    location_raw: Optional[str] = None
    body_raw: str
    published_raw: Optional[str] = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.raw_payload_hash:
            payload = f"{self.source_name}|{self.source_id}|{self.company_raw}|{self.title_raw}|{self.body_raw}"
            self.raw_payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExtractedJobFields(BaseModel):
    """Structured extraction returned by LLM or extractor before canonical merging.
    
    CRITICAL RULE FROM SPECIFICATION:
    A field not stated in the posting must be null, never guessed.
    Store the source snippet each field came from.
    """
    company: str
    title: str
    seniority: Optional[SeniorityLevel] = None
    city: Optional[str] = None
    country: Optional[str] = None
    remote_policy: Optional[RemotePolicy] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    skills: List[str] = Field(default_factory=list)
    visa_sponsorship: Optional[bool] = None
    posted_date: Optional[date] = None
    evidence: Dict[str, str] = Field(default_factory=dict)

    @field_validator("skills", mode="before")
    @classmethod
    def clean_skills(cls, v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        # Dedup and strip
        seen = set()
        cleaned = []
        for s in v:
            item = str(s).strip()
            item_lower = item.lower()
            if item and item_lower not in seen:
                seen.add(item_lower)
                cleaned.append(item)
        return cleaned

    @model_validator(mode="after")
    def validate_salary_and_evidence(self) -> ExtractedJobFields:
        # Validate salary range logic
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                # Swap if inverted
                self.salary_min, self.salary_max = self.salary_max, self.salary_min
        
        # If salary is provided, ensure currency defaults to USD if not given for US roles
        if (self.salary_min is not None or self.salary_max is not None) and not self.currency:
            self.currency = "USD"
            
        return self


class JobPosting(BaseModel):
    """The canonical target schema specified in Page 3 of the assignment.
    
    Fields:
    - posting_id: string (Stable across runs)
    - company: string (Normalized company name)
    - title: string (Canonical title)
    - seniority: enum (junior, mid, senior, staff_plus)
    - city, country: string
    - remote_policy: enum (onsite, hybrid, remote)
    - salary_min, salary_max, currency: number, string (Only if stated; annualized)
    - employment_type: enum (full_time, contract, intern)
    - skills: list[string] (e.g. Python, Spark, dbt)
    - visa_sponsorship: bool (Null if not stated)
    - posted_date: date (Null if not stated)
    - status: enum (open, closed)
    - source_urls: list[string] (All sources merged into this record)
    - evidence: object (Field -> source snippet)
    - first_seen, last_seen: datetime
    """
    posting_id: str
    company: str
    title: str
    seniority: Optional[SeniorityLevel] = None
    city: Optional[str] = None
    country: Optional[str] = None
    remote_policy: Optional[RemotePolicy] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = None
    employment_type: Optional[EmploymentType] = None
    skills: List[str] = Field(default_factory=list)
    visa_sponsorship: Optional[bool] = None
    posted_date: Optional[date] = None
    status: PostingStatus = PostingStatus.open
    source_urls: List[str] = Field(default_factory=list)
    evidence: Dict[str, str] = Field(default_factory=dict)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def generate_posting_id(company: str, title: str, city: Optional[str] = None, remote_policy: Optional[str] = None) -> str:
        """Generates a stable, deterministic posting ID for deduplication and idempotency."""
        norm_company = company.strip().lower()
        norm_title = title.strip().lower()
        norm_loc = (city or remote_policy or "us").strip().lower()
        content = f"{norm_company}::{norm_title}::{norm_loc}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def to_dict_for_export(self) -> Dict[str, Any]:
        """Convert to flattened representation for CSV / DuckDB export."""
        return {
            "posting_id": self.posting_id,
            "company": self.company,
            "title": self.title,
            "seniority": self.seniority.value if self.seniority else None,
            "city": self.city,
            "country": self.country,
            "remote_policy": self.remote_policy.value if self.remote_policy else None,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "currency": self.currency,
            "employment_type": self.employment_type.value if self.employment_type else None,
            "skills": ", ".join(self.skills) if self.skills else "",
            "visa_sponsorship": self.visa_sponsorship,
            "posted_date": self.posted_date.isoformat() if self.posted_date else None,
            "status": self.status.value,
            "source_urls": " | ".join(self.source_urls),
            "evidence": json.dumps(self.evidence),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


class ChangeRecord(BaseModel):
    """Audit record capturing changes to a posting over time across incremental re-runs."""
    history_id: Optional[int] = None
    posting_id: str
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
