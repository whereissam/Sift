"""Core job CRUD, status / priority / scheduling, and backup/restore."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ._enums import JobStatus, JobType

logger = logging.getLogger(__name__)


class _JobsMixin:
    """Methods that operate on the ``jobs`` table.

    Also owns ``_row_to_dict`` — the JSON-decoding helper that
    other mixins re-use whenever they fetch from ``jobs``.
    """

    # Allowlist of columns that can be updated via update_job()
    _UPDATABLE_COLUMNS = {
        "status", "source_url", "platform", "raw_file_path", "converted_file_path",
        "output_format", "quality", "model_size", "language", "transcription_format",
        "content_info", "transcription_result", "file_size_mb", "error",
        "progress", "last_checkpoint", "priority", "batch_id", "scheduled_at",
        "webhook_url", "updated_at", "completed_at",
        # P18 knowledge backfill control-plane columns
        "knowledge_status", "knowledge_version", "knowledge_locked_at",
        "knowledge_worker_id",
    }

    db_path: Path  # set by JobStore.__init__

    def create_job(
        self,
        job_id: str,
        job_type: JobType,
        source_url: Optional[str] = None,
        platform: Optional[str] = None,
        output_format: Optional[str] = None,
        quality: Optional[str] = None,
        model_size: Optional[str] = None,
        language: Optional[str] = None,
        transcription_format: Optional[str] = None,
        priority: int = 5,
        batch_id: Optional[str] = None,
        scheduled_at: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> dict:
        """Create a new job."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    job_id, job_type, status, source_url, platform,
                    output_format, quality, model_size, language, transcription_format,
                    priority, batch_id, scheduled_at, webhook_url,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, job_type.value, JobStatus.PENDING.value,
                source_url, platform, output_format, quality,
                model_size, language, transcription_format,
                priority, batch_id, scheduled_at, webhook_url,
                now, now
            ))

        logger.info(f"Created job {job_id} ({job_type.value})")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()

            if row:
                return self._row_to_dict(row)
        return None

    def update_job(self, job_id: str, **kwargs) -> Optional[dict]:
        """Update job fields."""
        kwargs["updated_at"] = datetime.utcnow().isoformat()

        # Reject any column names not in the allowlist
        invalid_keys = set(kwargs.keys()) - self._UPDATABLE_COLUMNS
        if invalid_keys:
            raise ValueError(f"Invalid column names: {invalid_keys}")

        # Handle JSON fields
        for json_field in ["content_info", "transcription_result", "last_checkpoint"]:
            if json_field in kwargs and kwargs[json_field] is not None:
                if not isinstance(kwargs[json_field], str):
                    kwargs[json_field] = json.dumps(kwargs[json_field])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [job_id]

        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE job_id = ?",
                values
            )

        return self.get_job(job_id)

    def set_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        progress: Optional[float] = None,
    ) -> Optional[dict]:
        """Update job status."""
        updates = {"status": status.value}

        if error:
            updates["error"] = error
        if progress is not None:
            updates["progress"] = progress
        if status == JobStatus.COMPLETED:
            updates["completed_at"] = datetime.utcnow().isoformat()
            updates["progress"] = 1.0

        return self.update_job(job_id, **updates)

    def get_jobs_by_status(self, *statuses: JobStatus) -> list[dict]:
        """Get all jobs with given statuses."""
        placeholders = ",".join("?" * len(statuses))
        status_values = [s.value for s in statuses]

        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at DESC",
                status_values
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def get_unfinished_jobs(self) -> list[dict]:
        """Get all jobs that are not completed or failed."""
        return self.get_jobs_by_status(
            JobStatus.PENDING,
            JobStatus.DOWNLOADING,
            JobStatus.CONVERTING,
            JobStatus.TRANSCRIBING,
        )

    def get_resumable_jobs(self, job_type: Optional[JobType] = None) -> list[dict]:
        """Get jobs that can be resumed (failed or in-progress)."""
        statuses = [
            JobStatus.DOWNLOADING,
            JobStatus.CONVERTING,
            JobStatus.TRANSCRIBING,
            JobStatus.FAILED,
        ]

        jobs = self.get_jobs_by_status(*statuses)

        if job_type:
            jobs = [j for j in jobs if j["job_type"] == job_type.value]

        return jobs

    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            return cursor.rowcount > 0

    def cleanup_old_jobs(self, days: int = 7) -> int:
        """Delete completed/failed jobs older than N days."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        with self._get_conn() as conn:
            cursor = conn.execute("""
                DELETE FROM jobs
                WHERE status IN (?, ?) AND updated_at < ?
            """, (JobStatus.COMPLETED.value, JobStatus.FAILED.value, cutoff))

            deleted = cursor.rowcount
            if deleted:
                logger.info(f"Cleaned up {deleted} old jobs")
            return deleted

    def backup(self, backup_dir: Optional[Path] = None) -> Path:
        """
        Create a backup of the database.

        Args:
            backup_dir: Directory for backup file. Defaults to db_path.parent/backups

        Returns:
            Path to the backup file
        """

        if backup_dir is None:
            backup_dir = self.db_path.parent / "backups"

        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped backup filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"jobs_{timestamp}.db"

        # Use SQLite's backup API for safe hot backup
        with self._get_conn() as conn:
            backup_conn = sqlite3.connect(str(backup_path))
            try:
                conn.backup(backup_conn)
            finally:
                backup_conn.close()

        logger.info(f"Database backed up to {backup_path}")
        return backup_path

    def list_backups(self, backup_dir: Optional[Path] = None) -> list[dict]:
        """List available backups with metadata."""
        if backup_dir is None:
            backup_dir = self.db_path.parent / "backups"

        if not backup_dir.exists():
            return []

        backups = []
        for f in sorted(backup_dir.glob("jobs_*.db"), reverse=True):
            stat = f.stat()
            backups.append({
                "path": str(f),
                "filename": f.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        return backups

    def restore(self, backup_path: Path) -> bool:
        """
        Restore database from a backup.

        Args:
            backup_path: Path to backup file

        Returns:
            True if restore successful
        """
        import shutil

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        # Create a backup of current db before restoring
        current_backup = self.db_path.with_suffix(".db.before_restore")
        if self.db_path.exists():
            shutil.copy2(self.db_path, current_backup)

        try:
            shutil.copy2(backup_path, self.db_path)
            logger.info(f"Database restored from {backup_path}")
            return True
        except Exception:
            # Restore the original on failure
            if current_backup.exists():
                shutil.copy2(current_backup, self.db_path)
            raise

    # ============ Priority Queue Methods ============

    def get_jobs_by_priority(
        self,
        statuses: Optional[list[JobStatus]] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get jobs ordered by priority (high to low), then by creation time."""
        if statuses is None:
            statuses = [JobStatus.PENDING]

        placeholders = ",".join("?" * len(statuses))
        status_values = [s.value for s in statuses]

        with self._get_conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM jobs
                WHERE status IN ({placeholders})
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (*status_values, datetime.utcnow().isoformat(), limit)).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def update_priority(self, job_id: str, priority: int) -> Optional[dict]:
        """Update a job's priority level."""
        priority = max(1, min(10, priority))  # Clamp to 1-10
        return self.update_job(job_id, priority=priority)

    # ============ Scheduled Jobs Methods ============

    def get_scheduled_jobs(self, before_time: Optional[str] = None) -> list[dict]:
        """Get scheduled jobs that are due to run."""
        if before_time is None:
            before_time = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM jobs
                WHERE status = ?
                  AND scheduled_at IS NOT NULL
                  AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
            """, (JobStatus.PENDING.value, before_time)).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def clear_scheduled_at(self, job_id: str) -> Optional[dict]:
        """Clear the scheduled_at field when a job is queued."""
        return self.update_job(job_id, scheduled_at=None)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a ``jobs`` row to dict, JSON-decoding payload columns."""
        d = dict(row)

        # Parse JSON fields
        for json_field in ["content_info", "transcription_result", "last_checkpoint"]:
            if d.get(json_field):
                try:
                    d[json_field] = json.loads(d[json_field])
                except json.JSONDecodeError:
                    pass

        return d
