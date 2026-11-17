"""End-to-end integration tests for PipelineOrchestrator and database lifecycle."""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline.models import RawJobPosting
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.storage.database import DatabaseManager


def test_full_pipeline_orchestrator_integration():
    """Verify PipelineOrchestrator end-to-end flow with mocked source payloads."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "postings.db"
        duckdb_path = tmp_path / "postings.duckdb"
        csv_path = tmp_path / "jobs.csv"
        json_path = tmp_path / "jobs.json"

        db = DatabaseManager(db_path)
        orchestrator = PipelineOrchestrator(db_manager=db)

        # Mock source postings
        mock_raw_gh = [
            RawJobPosting(
                source_name="greenhouse",
                source_id="gh_stripe_1",
                source_url="https://boards.greenhouse.io/stripe/jobs/1",
                company_raw="Stripe",
                title_raw="Senior Data Engineer, Core Infrastructure",
                location_raw="San Francisco, CA",
                body_raw="Stripe is hiring a Senior Data Engineer. Python, Spark, SQL. Base salary: $180,000 - $240,000.",
            ),
            RawJobPosting(
                source_name="greenhouse",
                source_id="gh_stripe_non_data",
                source_url="https://boards.greenhouse.io/stripe/jobs/2",
                company_raw="Stripe",
                title_raw="Account Executive, Enterprise Sales",
                location_raw="New York, NY",
                body_raw="Sales role selling payments software.",
            ),
        ]

        mock_raw_hn = [
            RawJobPosting(
                source_name="hackernews",
                source_id="hn_stripe_1",
                source_url="https://news.ycombinator.com/item?id=50338728",
                company_raw="Stripe",
                title_raw="Sr. Data Engineer",
                location_raw="San Francisco, CA (Hybrid)",
                body_raw="Stripe | Sr. Data Engineer | San Francisco, CA | Full-time | $180k-$240k",
            )
        ]

        with patch("pipeline.scrapers.greenhouse.GreenhouseScraper.scrape_all", return_value=mock_raw_gh), \
             patch("pipeline.scrapers.lever.LeverScraper.scrape_all", return_value=[]), \
             patch("pipeline.scrapers.hackernews.HackerNewsScraper.scrape_latest", return_value=mock_raw_hn), \
             patch("pipeline.config.config.csv_output_path", csv_path), \
             patch("pipeline.config.config.json_output_path", json_path), \
             patch("pipeline.config.config.duckdb_path", duckdb_path):

            stats = orchestrator.run()

            # Checks:
            # 1. Non-data role was filtered out
            assert stats["filtered_kept"] == 2
            # 2. Both postings (GH and HN) represented the same Stripe role -> deduplicated to 1!
            assert stats["canonical_postings"] == 1
            assert stats["new_inserted"] == 1

            # Verify persisted DB
            postings = db.get_all_postings()
            assert len(postings) == 1
            canonical = postings[0]
            assert canonical.company == "Stripe"
            assert "Senior Data Engineer" in canonical.title
            # Preserved both sources
            assert len(canonical.source_urls) == 2
            assert canonical.salary_min == 180000.0
            assert canonical.salary_max == 240000.0

            # Verify CSV export
            assert csv_path.exists()
            with open(csv_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                assert len(rows) == 1
                assert rows[0]["company"] == "Stripe"

            # Verify JSON export
            assert json_path.exists()
            with open(json_path, "r", encoding="utf-8") as f:
                j_data = json.load(f)
                assert len(j_data) == 1
                assert j_data[0]["company"] == "Stripe"

        db.close()
