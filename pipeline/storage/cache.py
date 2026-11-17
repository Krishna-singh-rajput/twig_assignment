"""Raw response caching layer to guarantee incremental idempotency and minimize LLM calls."""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional, Tuple
from pipeline.models import RawJobPosting

logger = logging.getLogger("pipeline.storage.cache")


class RawResponseCache:
    """Manages raw payload cache to prevent redundant LLM extraction when raw data has not changed."""

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self.conn = db_conn
        self._init_table()

    def _init_table(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_cache (
                    source_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    company_raw TEXT,
                    title_raw TEXT,
                    location_raw TEXT,
                    body_raw TEXT,
                    published_raw TEXT,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_hash ON raw_cache(content_hash);")

    def get_cached_hash(self, source_id: str) -> Optional[str]:
        """Retrieve stored content hash for a source ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT content_hash FROM raw_cache WHERE source_id = ?", (source_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def is_cached_and_unchanged(self, posting: RawJobPosting) -> bool:
        """Check if posting is already cached with identical raw content hash."""
        stored_hash = self.get_cached_hash(posting.source_id)
        if stored_hash and stored_hash == posting.raw_payload_hash:
            return True
        return False

    def put(self, posting: RawJobPosting) -> None:
        """Store or update raw payload in cache."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO raw_cache (
                    source_id, source_name, source_url, content_hash,
                    company_raw, title_raw, location_raw, body_raw, published_raw, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    location_raw = excluded.location_raw,
                    body_raw = excluded.body_raw,
                    published_raw = excluded.published_raw,
                    scraped_at = excluded.scraped_at;
                """,
                (
                    posting.source_id,
                    posting.source_name,
                    posting.source_url,
                    posting.raw_payload_hash,
                    posting.company_raw,
                    posting.title_raw,
                    posting.location_raw,
                    posting.body_raw,
                    posting.published_raw,
                    posting.scraped_at.isoformat(),
                ),
            )
