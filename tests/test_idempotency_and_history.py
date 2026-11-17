"""Unit tests for incremental runs, idempotency, raw caching, and change history audit trail."""

import tempfile
from pathlib import Path
from pipeline.models import JobPosting, PostingStatus, RawJobPosting, RemotePolicy, SeniorityLevel
from pipeline.storage.database import DatabaseManager


def test_idempotent_re_runs_never_duplicate():
    """Verify executing multiple upserts with identical data creates 0 duplicates."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = DatabaseManager(db_path)

        posting = JobPosting(
            posting_id="post_1",
            company="Stripe",
            title="Senior Data Engineer",
            seniority=SeniorityLevel.senior,
            salary_min=180000.0,
            salary_max=240000.0,
            source_urls=["https://boards.greenhouse.io/stripe/jobs/1"],
        )

        # Run 1: initial insert
        ins1, upd1 = db.upsert_postings([posting])
        assert ins1 == 1
        assert upd1 == 0
        assert len(db.get_all_postings()) == 1

        # Run 2: idempotent re-run
        ins2, upd2 = db.upsert_postings([posting])
        assert ins2 == 0
        assert upd2 == 1
        # Crucial check: row count remains exactly 1!
        assert len(db.get_all_postings()) == 1

        # Run 3: third re-run
        ins3, upd3 = db.upsert_postings([posting])
        assert ins3 == 0
        assert upd3 == 1
        assert len(db.get_all_postings()) == 1

        db.close()


def test_raw_cache_detects_unchanged_and_changed_payloads():
    """Verify raw cache correctly identifies identical content vs mutated content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = DatabaseManager(db_path)

        raw1 = RawJobPosting(
            source_name="greenhouse",
            source_id="gh_101",
            source_url="https://example.com/101",
            company_raw="Figma",
            title_raw="Data Platform Engineer",
            body_raw="Initial description text",
        )

        assert db.cache.is_cached_and_unchanged(raw1) is False
        db.cache.put(raw1)
        assert db.cache.is_cached_and_unchanged(raw1) is True

        # Mutate body
        raw1_updated = RawJobPosting(
            source_name="greenhouse",
            source_id="gh_101",
            source_url="https://example.com/101",
            company_raw="Figma",
            title_raw="Data Platform Engineer",
            body_raw="Updated description with new salary info",
        )
        # Content hash changed -> cache miss
        assert db.cache.is_cached_and_unchanged(raw1_updated) is False

        db.close()


def test_change_history_records_salary_and_location_mutations():
    """Verify that when a posting's salary or location changes, an audit record is logged."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = DatabaseManager(db_path)

        p_v1 = JobPosting(
            posting_id="post_mut_1",
            company="Airbnb",
            title="Senior Analytics Engineer",
            remote_policy=RemotePolicy.onsite,
            city="San Francisco",
            salary_min=160000.0,
            salary_max=200000.0,
            source_urls=["https://boards.greenhouse.io/airbnb/jobs/1"],
        )
        db.upsert_postings([p_v1])
        assert len(db.history.get_history()) == 0

        # Version 2: salary increased and remote policy changed to remote
        p_v2 = JobPosting(
            posting_id="post_mut_1",
            company="Airbnb",
            title="Senior Analytics Engineer",
            remote_policy=RemotePolicy.remote,
            city=None,
            salary_min=175000.0,
            salary_max=220000.0,
            source_urls=["https://boards.greenhouse.io/airbnb/jobs/1"],
        )
        db.upsert_postings([p_v2])

        history = db.history.get_history(posting_id="post_mut_1")
        assert len(history) >= 3

        history_map = {h["field_name"]: (h["old_value"], h["new_value"]) for h in history}
        assert "salary_min" in history_map
        assert history_map["salary_min"] == ("160000.0", "175000.0")

        assert "salary_max" in history_map
        assert history_map["salary_max"] == ("200000.0", "220000.0")

        assert "remote_policy" in history_map
        assert history_map["remote_policy"] == ("onsite", "remote")

        db.close()


def test_posting_closure_detection_and_history():
    """Verify that disappearing postings are marked closed and recorded in audit history."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        db = DatabaseManager(db_path)

        p = JobPosting(
            posting_id="close_test_1",
            company="Databricks",
            title="Machine Learning Engineer",
            status=PostingStatus.open,
            source_urls=["https://boards.greenhouse.io/databricks/jobs/999"],
        )
        db.upsert_postings([p])

        # Current scrape of greenhouse no longer contains posting "close_test_1"
        closed_count = db.detect_and_close_missing(current_source_ids={"some_other_id"}, source_name="greenhouse")
        assert closed_count == 1

        stored = db.get_posting("close_test_1")
        assert stored.status == PostingStatus.closed

        # Check audit trail
        history = db.history.get_history(posting_id="close_test_1")
        assert any(h["field_name"] == "status" and h["new_value"] == "closed" for h in history)

        db.close()
