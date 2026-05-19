"""Batch CRUD and aggregate statistics."""

from datetime import datetime
from typing import Optional

from ._enums import JobStatus


class _BatchesMixin:
    """Methods that operate on the ``batches`` table."""

    def create_batch(
        self,
        batch_id: str,
        name: Optional[str] = None,
        total_jobs: int = 0,
        webhook_url: Optional[str] = None,
    ) -> dict:
        """Create a new batch."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO batches (batch_id, name, total_jobs, webhook_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (batch_id, name, total_jobs, webhook_url, now, now))

        return self.get_batch(batch_id)

    def get_batch(self, batch_id: str) -> Optional[dict]:
        """Get batch by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()

            if row:
                return dict(row)
        return None

    def get_batch_jobs(self, batch_id: str) -> list[dict]:
        """Get all jobs in a batch."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE batch_id = ? ORDER BY created_at ASC",
                (batch_id,)
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def update_batch_stats(self, batch_id: str) -> Optional[dict]:
        """Recalculate and update batch statistics."""
        jobs = self.get_batch_jobs(batch_id)
        if not jobs:
            return None

        completed = sum(1 for j in jobs if j["status"] == JobStatus.COMPLETED.value)
        failed = sum(1 for j in jobs if j["status"] == JobStatus.FAILED.value)
        total = len(jobs)

        # Determine batch status
        if completed + failed == total:
            status = "completed" if failed == 0 else "completed_with_errors"
        elif completed + failed > 0:
            status = "in_progress"
        else:
            status = "pending"

        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE batches
                SET completed_jobs = ?, failed_jobs = ?, status = ?, updated_at = ?
                WHERE batch_id = ?
            """, (completed, failed, status, now, batch_id))

        return self.get_batch(batch_id)

    def delete_batch(self, batch_id: str) -> bool:
        """Delete a batch (does not delete associated jobs)."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
            return cursor.rowcount > 0

    def get_all_batches(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Get all batches with optional status filter."""
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM batches WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()

            return [dict(row) for row in rows]
