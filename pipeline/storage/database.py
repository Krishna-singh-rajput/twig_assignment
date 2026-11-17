"""Database storage and export manager using SQLite and DuckDB."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from pipeline.models import JobPosting, PostingStatus, RemotePolicy, SeniorityLevel, EmploymentType
from pipeline.storage.cache import RawResponseCache
from pipeline.storage.history import ChangeHistoryTracker

logger = logging.getLogger("pipeline.storage.database")


class DatabaseManager:
    """Central storage engine orchestrating SQLite persistence, caching,
    history auditing, and analytics exports.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

        self.cache = RawResponseCache(self.conn)
        self.history = ChangeHistoryTracker(self.conn)

    def _init_schema(self) -> None:
        """Create canonical job postings table."""
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    posting_id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    seniority TEXT,
                    city TEXT,
                    country TEXT,
                    remote_policy TEXT,
                    salary_min REAL,
                    salary_max REAL,
                    currency TEXT,
                    employment_type TEXT,
                    skills TEXT,
                    visa_sponsorship INTEGER,
                    posted_date TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    source_urls TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL
                );
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_postings_comp ON job_postings(company);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_postings_status ON job_postings(status);")

    def get_posting(self, posting_id: str) -> Optional[JobPosting]:
        """Fetch a single posting by posting_id."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM job_postings WHERE posting_id = ?", (posting_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def get_all_postings(self, status: Optional[str] = None) -> List[JobPosting]:
        """Fetch all stored postings."""
        cursor = self.conn.cursor()
        if status:
            cursor.execute("SELECT * FROM job_postings WHERE status = ? ORDER BY company, title", (status,))
        else:
            cursor.execute("SELECT * FROM job_postings ORDER BY company, title")
        rows = cursor.fetchall()
        return [self._row_to_model(r) for r in rows]

    def upsert_postings(self, postings: List[JobPosting]) -> Tuple[int, int]:
        """Idempotently insert or update postings, tracking field changes.
        
        Returns: (inserted_count, updated_count)
        """
        inserted = 0
        updated = 0

        for new_p in postings:
            existing = self.get_posting(new_p.posting_id)
            if existing is None:
                # Insert fresh record
                self._insert_posting(new_p)
                inserted += 1
            else:
                # Existing record: check diffs and update
                # Merge source URLs
                all_urls = list(dict.fromkeys(existing.source_urls + new_p.source_urls))
                new_p.source_urls = all_urls
                new_p.first_seen = existing.first_seen
                new_p.last_seen = datetime.now(timezone.utc)

                # Record any field changes to change history
                self.history.record_diff(existing, new_p)

                # Update in DB
                self._update_posting(new_p)
                updated += 1

        logger.info(f"Storage upsert complete: {inserted} new inserted, {updated} existing updated.")
        return inserted, updated

    def detect_and_close_missing(self, current_source_ids: Set[str], source_name: str) -> int:
        """Mark postings as 'closed' if they previously belonged to this source but disappeared."""
        # Find postings where source_urls contains this source and status='open'
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM job_postings WHERE status = 'open'")
        rows = cursor.fetchall()
        closed_count = 0

        for row in rows:
            urls_json = row["source_urls"]
            urls = urls_json.split(" | ") if urls_json else []
            # Check if any URL belongs to this source
            matches_source = any(source_name in u.lower() for u in urls)
            if matches_source:
                # Check if posting_id or any source URL was in the current run
                p_id = row["posting_id"]
                if p_id not in current_source_ids and not any(u in current_source_ids for u in urls):
                    self.history.record_closure(p_id)
                    closed_count += 1

        return closed_count

    def _insert_posting(self, p: JobPosting) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO job_postings (
                    posting_id, company, title, seniority, city, country, remote_policy,
                    salary_min, salary_max, currency, employment_type, skills,
                    visa_sponsorship, posted_date, status, source_urls, evidence,
                    first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    p.posting_id,
                    p.company,
                    p.title,
                    p.seniority.value if p.seniority else None,
                    p.city,
                    p.country,
                    p.remote_policy.value if p.remote_policy else None,
                    p.salary_min,
                    p.salary_max,
                    p.currency,
                    p.employment_type.value if p.employment_type else None,
                    json.dumps(p.skills),
                    1 if p.visa_sponsorship is True else (0 if p.visa_sponsorship is False else None),
                    p.posted_date.isoformat() if p.posted_date else None,
                    p.status.value,
                    " | ".join(p.source_urls),
                    json.dumps(p.evidence),
                    p.first_seen.isoformat(),
                    p.last_seen.isoformat(),
                ),
            )

    def _update_posting(self, p: JobPosting) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE job_postings SET
                    company = ?,
                    title = ?,
                    seniority = ?,
                    city = ?,
                    country = ?,
                    remote_policy = ?,
                    salary_min = ?,
                    salary_max = ?,
                    currency = ?,
                    employment_type = ?,
                    skills = ?,
                    visa_sponsorship = ?,
                    posted_date = ?,
                    status = ?,
                    source_urls = ?,
                    evidence = ?,
                    last_seen = ?
                WHERE posting_id = ?;
                """,
                (
                    p.company,
                    p.title,
                    p.seniority.value if p.seniority else None,
                    p.city,
                    p.country,
                    p.remote_policy.value if p.remote_policy else None,
                    p.salary_min,
                    p.salary_max,
                    p.currency,
                    p.employment_type.value if p.employment_type else None,
                    json.dumps(p.skills),
                    1 if p.visa_sponsorship is True else (0 if p.visa_sponsorship is False else None),
                    p.posted_date.isoformat() if p.posted_date else None,
                    p.status.value,
                    " | ".join(p.source_urls),
                    json.dumps(p.evidence),
                    p.last_seen.isoformat(),
                    p.posting_id,
                ),
            )

    def _row_to_model(self, row: sqlite3.Row) -> JobPosting:
        skills_raw = row["skills"]
        try:
            skills = json.loads(skills_raw) if skills_raw else []
        except Exception:
            skills = [s.strip() for s in str(skills_raw).split(",") if s.strip()]

        evidence_raw = row["evidence"]
        try:
            evidence = json.loads(evidence_raw) if evidence_raw else {}
        except Exception:
            evidence = {}

        source_urls_raw = row["source_urls"]
        source_urls = source_urls_raw.split(" | ") if source_urls_raw else []

        visa_raw = row["visa_sponsorship"]
        visa = True if visa_raw == 1 else (False if visa_raw == 0 else None)

        posted_date_raw = row["posted_date"]
        posted_date = datetime.fromisoformat(posted_date_raw).date() if posted_date_raw else None

        return JobPosting(
            posting_id=row["posting_id"],
            company=row["company"],
            title=row["title"],
            seniority=SeniorityLevel(row["seniority"]) if row["seniority"] else None,
            city=row["city"],
            country=row["country"],
            remote_policy=RemotePolicy(row["remote_policy"]) if row["remote_policy"] else None,
            salary_min=row["salary_min"],
            salary_max=row["salary_max"],
            currency=row["currency"],
            employment_type=EmploymentType(row["employment_type"]) if row["employment_type"] else None,
            skills=skills,
            visa_sponsorship=visa,
            posted_date=posted_date,
            status=PostingStatus(row["status"]) if row["status"] else PostingStatus.open,
            source_urls=source_urls,
            evidence=evidence,
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def export_csv(self, output_path: Path) -> None:
        """Export all canonical job postings to a CSV file."""
        postings = self.get_all_postings()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not postings:
            logger.warning("No postings to export to CSV.")
            return

        rows = [p.to_dict_for_export() for p in postings]
        headers = list(rows[0].keys())

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Successfully exported {len(rows)} postings to CSV: {output_path}")

    def export_json(self, output_path: Path) -> None:
        """Export all canonical job postings to a JSON file."""
        postings = self.get_all_postings()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = [p.model_dump(mode="json") for p in postings]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Successfully exported {len(data)} postings to JSON: {output_path}")

    def export_duckdb(self, duckdb_path: Path) -> None:
        """Export canonical dataset to DuckDB for high-performance analytical queries."""
        try:
            import duckdb

            duckdb_path = Path(duckdb_path)
            duckdb_path.parent.mkdir(parents=True, exist_ok=True)

            dconn = duckdb.connect(str(duckdb_path))
            postings = self.get_all_postings()

            # Create table natively without external extension downloads
            dconn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    posting_id VARCHAR PRIMARY KEY,
                    company VARCHAR,
                    title VARCHAR,
                    seniority VARCHAR,
                    city VARCHAR,
                    country VARCHAR,
                    remote_policy VARCHAR,
                    salary_min DOUBLE,
                    salary_max DOUBLE,
                    currency VARCHAR,
                    employment_type VARCHAR,
                    skills VARCHAR,
                    visa_sponsorship BOOLEAN,
                    posted_date DATE,
                    status VARCHAR,
                    source_urls VARCHAR,
                    evidence VARCHAR,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP
                );
                """
            )
            dconn.execute("DELETE FROM job_postings;")

            if postings:
                rows = []
                for p in postings:
                    d = p.to_dict_for_export()
                    rows.append((
                        d["posting_id"],
                        d["company"],
                        d["title"],
                        d["seniority"],
                        d["city"],
                        d["country"],
                        d["remote_policy"],
                        d["salary_min"],
                        d["salary_max"],
                        d["currency"],
                        d["employment_type"],
                        d["skills"],
                        d["visa_sponsorship"],
                        d["posted_date"],
                        d["status"],
                        d["source_urls"],
                        d["evidence"],
                        d["first_seen"],
                        d["last_seen"],
                    ))

                dconn.executemany(
                    "INSERT INTO job_postings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                    rows,
                )

            dconn.close()
            logger.info(f"Successfully synced {len(postings)} postings to DuckDB: {duckdb_path}")
        except Exception as e:
            logger.warning(f"DuckDB export note: {e}")

    def close(self) -> None:
        """Close SQLite database connection."""
        self.conn.close()
