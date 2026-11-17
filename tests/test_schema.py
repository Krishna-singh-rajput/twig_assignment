"""Unit tests for Pydantic schema validation, null enforcement, and evidence mapping."""

import pytest
from datetime import date
from pydantic import ValidationError

from pipeline.models import (
    EmploymentType,
    ExtractedJobFields,
    JobPosting,
    PostingStatus,
    RemotePolicy,
    SeniorityLevel,
)
from pipeline.transform.normalizer import DataNormalizer


def test_schema_valid_complete_posting():
    """Verify JobPosting instantiates cleanly with all schema fields."""
    posting = JobPosting(
        posting_id="abc1234567890def",
        company="Databricks",
        title="Staff Data Engineer",
        seniority=SeniorityLevel.staff_plus,
        city="San Francisco",
        country="USA",
        remote_policy=RemotePolicy.hybrid,
        salary_min=210000.0,
        salary_max=275000.0,
        currency="USD",
        employment_type=EmploymentType.full_time,
        skills=["Python", "Spark", "SQL", "dbt"],
        visa_sponsorship=True,
        posted_date=date(2026, 11, 1),
        status=PostingStatus.open,
        source_urls=["https://boards.greenhouse.io/databricks/jobs/12345"],
        evidence={
            "company": "Databricks",
            "title": "Staff Data Engineer",
            "salary_min": "$210,000 - $275,000",
            "visa_sponsorship": "We sponsor H1B",
        },
    )

    assert posting.company == "Databricks"
    assert posting.seniority == SeniorityLevel.staff_plus
    assert posting.salary_min == 210000.0
    assert "Spark" in posting.skills
    assert posting.visa_sponsorship is True


def test_schema_nulls_over_guesses():
    """Verify that unspecified fields are strictly None / null and not hallucinated."""
    extracted = ExtractedJobFields(
        company="Stripe",
        title="Data Engineer",
    )

    assert extracted.seniority is None
    assert extracted.city is None
    assert extracted.country is None
    assert extracted.remote_policy is None
    assert extracted.salary_min is None
    assert extracted.salary_max is None
    assert extracted.visa_sponsorship is None
    assert extracted.posted_date is None
    assert extracted.skills == []


def test_salary_swapping_when_inverted():
    """Verify validator corrects min > max if passed in reversed order."""
    extracted = ExtractedJobFields(
        company="TestCo",
        title="Data Engineer",
        salary_min=200000.0,
        salary_max=150000.0,
    )
    assert extracted.salary_min == 150000.0
    assert extracted.salary_max == 200000.0
    assert extracted.currency == "USD"


def test_hourly_rate_annualization():
    """Verify hourly wages are annualized (rate * 2080)."""
    text = "Competitive rate of $75/hr for contract work."
    s_min, s_max, curr, snip = DataNormalizer.extract_salary_range(text)
    assert s_min == 75.0 * 2080  # 156,000
    assert s_max == 75.0 * 2080
    assert curr == "USD"
    assert "$75/hr" in snip


def test_invalid_enum_raises_validation_error():
    """Verify invalid enum strings raise ValidationError."""
    with pytest.raises(ValidationError):
        JobPosting(
            posting_id="test",
            company="TestCo",
            title="Engineer",
            seniority="super_senior",  # Invalid enum value
        )


def test_deterministic_posting_id():
    """Verify identical role attributes generate the exact same posting_id."""
    id1 = JobPosting.generate_posting_id("Stripe", "Senior Data Engineer", "San Francisco", "hybrid")
    id2 = JobPosting.generate_posting_id("stripe", "senior data engineer", "san francisco", "hybrid")
    id3 = JobPosting.generate_posting_id("Stripe", "Senior Data Engineer", "New York", "hybrid")

    assert id1 == id2
    assert id1 != id3
