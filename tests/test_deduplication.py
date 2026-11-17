"""Unit tests for multi-source deduplication, canonical merging, and edge cases."""

from datetime import datetime, timezone
from pipeline.models import JobPosting, RemotePolicy, SeniorityLevel
from pipeline.transform.deduplicator import JobDeduplicator


def test_dedup_merges_title_variation_specification_example():
    """Test the exact specification example:
    'Sr. Data Engineer' vs 'Senior Data Engineer, Platform' at the same company.
    """
    p1 = JobPosting(
        posting_id="id1",
        company="Stripe",
        title="Sr. Data Engineer",
        seniority=SeniorityLevel.senior,
        city="San Francisco",
        remote_policy=RemotePolicy.hybrid,
        salary_min=180000.0,
        salary_max=240000.0,
        skills=["Python", "Spark"],
        source_urls=["https://news.ycombinator.com/item?id=50338728"],
        evidence={"title": "Sr. Data Engineer"},
        first_seen=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
        last_seen=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
    )

    p2 = JobPosting(
        posting_id="id2",
        company="Stripe, Inc.",
        title="Senior Data Engineer, Platform",
        seniority=SeniorityLevel.senior,
        city="San Francisco",
        remote_policy=RemotePolicy.hybrid,
        salary_min=None,
        salary_max=None,
        skills=["Spark", "Kafka", "SQL"],
        source_urls=["https://boards.greenhouse.io/stripe/jobs/987654"],
        evidence={"title": "Senior Data Engineer, Platform"},
        first_seen=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc),
        last_seen=datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc),
    )

    assert JobDeduplicator.are_same_role(p1, p2) is True

    merged = JobDeduplicator.merge_postings(p1, p2)
    assert merged.company == "Stripe"
    # Preserves both source links
    assert "https://news.ycombinator.com/item?id=50338728" in merged.source_urls
    assert "https://boards.greenhouse.io/stripe/jobs/987654" in merged.source_urls
    assert len(merged.source_urls) == 2

    # Preserves stated salary
    assert merged.salary_min == 180000.0
    assert merged.salary_max == 240000.0

    # Skills union
    assert set(merged.skills) == {"Python", "Spark", "Kafka", "SQL"}

    # Timestamps
    assert merged.first_seen == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    assert merged.last_seen == datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)


def test_dedup_rejects_different_roles_at_same_company():
    """Negative test: 'Data Engineer' vs 'Machine Learning Engineer' at same company must NOT merge."""
    p_de = JobPosting(
        posting_id="de_1",
        company="Stripe",
        title="Senior Data Engineer",
        seniority=SeniorityLevel.senior,
        source_urls=["url1"],
    )
    p_mle = JobPosting(
        posting_id="mle_1",
        company="Stripe",
        title="Senior Machine Learning Engineer",
        seniority=SeniorityLevel.senior,
        source_urls=["url2"],
    )

    assert JobDeduplicator.are_same_role(p_de, p_mle) is False


def test_dedup_rejects_different_seniorities_at_same_company():
    """Negative test: 'Junior Data Engineer' vs 'Staff Data Engineer' at same company must NOT merge."""
    p_jr = JobPosting(
        posting_id="jr_1",
        company="Databricks",
        title="Junior Data Engineer",
        seniority=SeniorityLevel.junior,
        source_urls=["url1"],
    )
    p_staff = JobPosting(
        posting_id="staff_1",
        company="Databricks",
        title="Staff Data Engineer",
        seniority=SeniorityLevel.staff_plus,
        source_urls=["url2"],
    )

    assert JobDeduplicator.are_same_role(p_jr, p_staff) is False


def test_dedup_rejects_same_title_at_different_companies():
    """Negative test: 'Senior Data Engineer' at Stripe vs Airbnb must NOT merge."""
    p_stripe = JobPosting(
        posting_id="s1",
        company="Stripe",
        title="Senior Data Engineer",
        source_urls=["url1"],
    )
    p_airbnb = JobPosting(
        posting_id="a1",
        company="Airbnb",
        title="Senior Data Engineer",
        source_urls=["url2"],
    )

    assert JobDeduplicator.are_same_role(p_stripe, p_airbnb) is False


def test_deduplicate_batch_reduction():
    """Verify list deduplication collapses duplicates and retains singletons."""
    p1 = JobPosting(
        posting_id="1", company="Palantir", title="Data Engineer", source_urls=["u1"]
    )
    p2 = JobPosting(
        posting_id="2", company="Palantir Technologies", title="Data Engineer, Platform", source_urls=["u2"]
    )
    p3 = JobPosting(
        posting_id="3", company="Palantir", title="Machine Learning Engineer", source_urls=["u3"]
    )

    results = JobDeduplicator.deduplicate([p1, p2, p3])
    # p1 and p2 should merge, p3 should remain distinct
    assert len(results) == 2
    merged_de = next(r for r in results if "Data Engineer" in r.title)
    assert len(merged_de.source_urls) == 2
    assert "u1" in merged_de.source_urls and "u2" in merged_de.source_urls
