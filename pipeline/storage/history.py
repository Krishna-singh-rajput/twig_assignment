"""Change history tracking layer recording field-level mutations and job closures across runs."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pipeline.models import ChangeRecord, JobPosting, PostingStatus

logger = logging.getLogger("pipeline.storage.history")


class ChangeHistoryTracker:
    """Detects differences across incremental pipeline runs and stores an audit trail."""

    TRACKED_FIELDS = [
        "salary_min",
        "salary_max",
        "currency",
        "remote_policy",
        "city",
        "country",
        "status",
        "seniority",
        "employment_type",
        "visa_sponsorship",
    ]

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self.conn = db_conn
        self._init_table()

    def _init_table(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS change_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    posting_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_posting ON change_history(posting_id);"
            )

    def record_diff(self, old_record: JobPosting, new_record: JobPosting) -> List[ChangeRecord]:
        """Compare two versions of the same posting and persist field changes."""
        changes: List[ChangeRecord] = []
        now = datetime.now(timezone.utc)

        for field in self.TRACKED_FIELDS:
            old_val = getattr(old_record, field, None)
            new_val = getattr(new_record, field, None)

            # Convert enums to string
            if hasattr(old_val, "value"):
                old_val = old_val.value
            if hasattr(new_val, "value"):
                new_val = new_val.value

            str_old = str(old_val) if old_val is not None else None
            str_new = str(new_val) if new_val is not None else None

            if str_old != str_new:
                record = ChangeRecord(
                    posting_id=new_record.posting_id,
                    field_name=field,
                    old_value=str_old,
                    new_value=str_new,
                    changed_at=now,
                )
                changes.append(record)
                logger.info(
                    f"Audit Change detected for {new_record.posting_id} ({new_record.company} - {new_record.title}): "
                    f"{field} changed from '{str_old}' to '{str_new}'"
                )

        if changes:
            with self.conn:
                for c in changes:
                    self.conn.execute(
                        """
                        INSERT INTO change_history (posting_id, field_name, old_value, new_value, changed_at)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (c.posting_id, c.field_name, c.old_value, c.new_value, c.changed_at.isoformat()),
                    )

        return changes

    def record_closure(self, posting_id: str) -> None:
        """Mark posting status as closed and record in audit trail."""
        now = datetime.now(timezone.utc)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO change_history (posting_id, field_name, old_value, new_value, changed_at)
                VALUES (?, 'status', 'open', 'closed', ?);
                """,
                (posting_id, now.isoformat()),
            )
            self.conn.execute(
                "UPDATE job_postings SET status = 'closed', last_seen = ? WHERE posting_id = ?;",
                (now.isoformat(), posting_id),
            )
        logger.info(f"Marked posting {posting_id} as closed in change history.")

    def get_history(self, posting_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve audit log records."""
        cursor = self.conn.cursor()
        if posting_id:
            cursor.execute(
                "SELECT history_id, posting_id, field_name, old_value, new_value, changed_at "
                "FROM change_history WHERE posting_id = ? ORDER BY history_id DESC",
                (posting_id,),
            )
        else:
            cursor.execute(
                "SELECT history_id, posting_id, field_name, old_value, new_value, changed_at "
                "FROM change_history ORDER BY history_id DESC"
            )

        rows = cursor.fetchall()
        return [
            {
                "history_id": r[0],
                "posting_id": r[1],
                "field_name": r[2],
                "old_value": r[3],
                "new_value": r[4],
                "changed_at": r[5],
            }
            for r in rows
        ]
