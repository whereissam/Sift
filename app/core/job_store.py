"""Persistent job storage using SQLite."""

import base64
import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_encryption_key() -> bytes:
    """Get or derive a Fernet-compatible encryption key for secrets at rest."""
    from ..config import get_settings
    settings = get_settings()
    if settings.encryption_key:
        # Derive a 32-byte key from the user-provided key
        key_bytes = hashlib.sha256(settings.encryption_key.encode()).digest()
    else:
        # Derive a machine-specific key from the download directory path
        key_bytes = hashlib.sha256(settings.download_dir.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _encrypt_secret(value: str) -> str:
    """Encrypt a secret value for storage."""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_encryption_key())
        return "enc:" + f.encrypt(value.encode()).decode()
    except ImportError:
        logger.warning("cryptography package not installed — storing secret with basic obfuscation")
        encoded = base64.b64encode(value.encode()).decode()
        return "b64:" + encoded


def _decrypt_secret(value: str) -> str:
    """Decrypt a stored secret value."""
    if not value:
        return value
    if value.startswith("enc:"):
        try:
            from cryptography.fernet import Fernet
            f = Fernet(_get_encryption_key())
            return f.decrypt(value[4:].encode()).decode()
        except Exception:
            logger.warning("Failed to decrypt secret — returning empty")
            return ""
    elif value.startswith("b64:"):
        return base64.b64decode(value[4:].encode()).decode()
    # Plaintext (legacy, pre-encryption) — return as-is
    return value

# Current schema version for migrations
SCHEMA_VERSION = 2


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Job types."""
    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"


class JobStore:
    """SQLite-based persistent job storage."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = db_path
        else:
            from ..config import get_settings
            settings = get_settings()
            self.db_path = Path(settings.download_dir) / "jobs.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,

                    -- Source info
                    source_url TEXT,
                    platform TEXT,

                    -- File paths (two-phase tracking)
                    raw_file_path TEXT,
                    converted_file_path TEXT,

                    -- Settings
                    output_format TEXT,
                    quality TEXT,

                    -- Transcription specific
                    model_size TEXT,
                    language TEXT,
                    transcription_format TEXT,

                    -- Results
                    content_info TEXT,  -- JSON
                    transcription_result TEXT,  -- JSON
                    file_size_mb REAL,
                    error TEXT,

                    -- Progress tracking
                    progress REAL DEFAULT 0.0,
                    last_checkpoint TEXT,  -- JSON for transcription segments

                    -- Priority & Batching (v2)
                    priority INTEGER DEFAULT 5,
                    batch_id TEXT,

                    -- Scheduling (v2)
                    scheduled_at TEXT,

                    -- Webhooks (v2)
                    webhook_url TEXT,

                    -- Timestamps
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)

            # Index for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_type ON jobs(job_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON jobs(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_id ON jobs(batch_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_at ON jobs(scheduled_at)")

            # Batches table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY,
                    name TEXT,
                    total_jobs INTEGER DEFAULT 0,
                    completed_jobs INTEGER DEFAULT 0,
                    failed_jobs INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    webhook_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Annotations table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    segment_start REAL,
                    segment_end REAL,
                    user_id TEXT NOT NULL,
                    user_name TEXT,
                    content TEXT NOT NULL,
                    parent_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_job ON annotations(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_annotations_parent ON annotations(parent_id)")

            # Cloud providers table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cloud_providers (
                    id TEXT PRIMARY KEY,
                    provider_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    credentials TEXT,
                    settings TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Export jobs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS export_jobs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT,
                    file_path TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    destination_path TEXT,
                    status TEXT DEFAULT 'pending',
                    progress REAL DEFAULT 0.0,
                    bytes_uploaded INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    cloud_url TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (provider_id) REFERENCES cloud_providers(id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_export_jobs_status ON export_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_export_jobs_job ON export_jobs(job_id)")

            # AI settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_settings (
                    id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'ollama',
                    model TEXT NOT NULL DEFAULT 'llama3.2',
                    api_key TEXT,
                    base_url TEXT,
                    is_default INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Obsidian settings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS obsidian_settings (
                    id INTEGER PRIMARY KEY,
                    vault_path TEXT NOT NULL,
                    subfolder TEXT DEFAULT 'Sift',
                    template TEXT,
                    default_tags TEXT DEFAULT 'sift,transcript',
                    is_default INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # P18: Knowledge layer (claims). Entities/topics/predictions land
            # in Phase B/C — but the join columns (entity_ids, topic_ids) are
            # already on Claim records as JSON arrays so the schema is forward-
            # compatible.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    speaker TEXT,
                    timestamp_start REAL NOT NULL,
                    timestamp_end REAL NOT NULL,
                    claim_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_excerpt TEXT NOT NULL,
                    entity_ids TEXT DEFAULT '[]',  -- JSON array
                    topic_ids TEXT DEFAULT '[]',   -- JSON array
                    source_url TEXT,
                    extraction_version INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_episode ON claims(episode_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_speaker ON claims(speaker)")

            # Generic embeddings table — keyed by (object_type, object_id, model)
            # so we can embed segments / claims / entities / episodes uniformly.
            # Phase A creates the table; population starts in Phase B (entity
            # canonicalization) and P10 (semantic search). Behind a thin
            # interface in embedding_store.py so the SQLite→Chroma swap is a
            # one-file change later.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    norm REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (object_type, object_id, model)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_type ON embeddings(object_type)")

            # P18 Phase B: Entities + mentions. Dual-ID (`entity_id` PK +
            # UNIQUE `slug`) lets us rename slugs on demand without breaking
            # references. Mentions carry an optional `claim_id` so entities
            # can exist without a specific claim reference.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    aliases TEXT DEFAULT '[]',  -- JSON array of surface forms
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_slug ON entities(slug)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    episode_id TEXT NOT NULL,
                    claim_id TEXT,
                    chunk_id TEXT,
                    raw_text TEXT NOT NULL,
                    start_char INTEGER,
                    end_char INTEGER,
                    timestamp REAL,
                    speaker TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_episode ON entity_mentions(episode_id)")

            # Quarantine for malformed extraction outputs — keep raw response
            # and error so we can debug prompt drift without crashing the
            # pipeline.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id TEXT NOT NULL,
                    chunk_index INTEGER,
                    raw_output TEXT,
                    error TEXT NOT NULL,
                    extraction_version INTEGER,
                    model TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_failures_episode ON extraction_failures(episode_id)")

            # Run migrations for existing databases
            self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Run database migrations for schema updates."""
        # Check existing columns in jobs table
        cursor = conn.execute("PRAGMA table_info(jobs)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add missing columns (v2 schema)
        migrations = [
            ("priority", "INTEGER DEFAULT 5"),
            ("batch_id", "TEXT"),
            ("scheduled_at", "TEXT"),
            ("webhook_url", "TEXT"),
            # P18: knowledge layer status. Values: none|pending|extracting|complete|failed.
            # 'none' = never attempted; 'pending' = queued for backfill or on-demand.
            ("knowledge_status", "TEXT DEFAULT 'none'"),
        ]

        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")
                    logger.info(f"Added column {col_name} to jobs table")
                except sqlite3.OperationalError:
                    pass  # Column might already exist

        # ai_settings.task_presets — JSON map of TaskType -> {provider,model,...}
        cursor = conn.execute("PRAGMA table_info(ai_settings)")
        ai_existing = {row[1] for row in cursor.fetchall()}
        if "task_presets" not in ai_existing:
            try:
                conn.execute("ALTER TABLE ai_settings ADD COLUMN task_presets TEXT")
                logger.info("Added column task_presets to ai_settings")
            except sqlite3.OperationalError:
                pass

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

    # Allowlist of columns that can be updated via update_job()
    _UPDATABLE_COLUMNS = {
        "status", "source_url", "platform", "raw_file_path", "converted_file_path",
        "output_format", "quality", "model_size", "language", "transcription_format",
        "content_info", "transcription_result", "file_size_mb", "error",
        "progress", "last_checkpoint", "priority", "batch_id", "scheduled_at",
        "webhook_url", "updated_at", "completed_at",
    }

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
        import shutil

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
        except Exception as e:
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

    # ============ Batch Methods ============

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

    # ============ Annotation Methods ============

    def create_annotation(
        self,
        annotation_id: str,
        job_id: str,
        user_id: str,
        content: str,
        segment_start: Optional[float] = None,
        segment_end: Optional[float] = None,
        parent_id: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> dict:
        """Create a new annotation."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO annotations (
                    id, job_id, user_id, content, segment_start, segment_end,
                    parent_id, user_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                annotation_id, job_id, user_id, content, segment_start, segment_end,
                parent_id, user_name, now, now
            ))

        return self.get_annotation(annotation_id)

    def get_annotation(self, annotation_id: str) -> Optional[dict]:
        """Get annotation by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
            ).fetchone()

            if row:
                return dict(row)
        return None

    def get_annotations_for_job(
        self,
        job_id: str,
        segment_start: Optional[float] = None,
        segment_end: Optional[float] = None,
    ) -> list[dict]:
        """Get all annotations for a job, optionally filtered by time range."""
        with self._get_conn() as conn:
            if segment_start is not None and segment_end is not None:
                rows = conn.execute("""
                    SELECT * FROM annotations
                    WHERE job_id = ? AND parent_id IS NULL
                      AND ((segment_start IS NULL) OR
                           (segment_start <= ? AND segment_end >= ?))
                    ORDER BY segment_start ASC, created_at ASC
                """, (job_id, segment_end, segment_start)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM annotations
                    WHERE job_id = ? AND parent_id IS NULL
                    ORDER BY segment_start ASC, created_at ASC
                """, (job_id,)).fetchall()

            return [dict(row) for row in rows]

    def get_annotation_replies(self, parent_id: str) -> list[dict]:
        """Get replies to an annotation."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM annotations
                WHERE parent_id = ?
                ORDER BY created_at ASC
            """, (parent_id,)).fetchall()

            return [dict(row) for row in rows]

    def get_annotation_with_replies(self, annotation_id: str) -> Optional[dict]:
        """Get an annotation with all its replies."""
        annotation = self.get_annotation(annotation_id)
        if not annotation:
            return None

        annotation["replies"] = self.get_annotation_replies(annotation_id)
        return annotation

    def update_annotation(self, annotation_id: str, content: str) -> Optional[dict]:
        """Update an annotation's content."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            cursor = conn.execute("""
                UPDATE annotations SET content = ?, updated_at = ?
                WHERE id = ?
            """, (content, now, annotation_id))

            if cursor.rowcount > 0:
                return self.get_annotation(annotation_id)
        return None

    def delete_annotation(self, annotation_id: str) -> bool:
        """Delete an annotation and its replies."""
        with self._get_conn() as conn:
            # Delete replies first
            conn.execute("DELETE FROM annotations WHERE parent_id = ?", (annotation_id,))
            # Delete the annotation
            cursor = conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
            return cursor.rowcount > 0

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert database row to dictionary."""
        d = dict(row)

        # Parse JSON fields
        for json_field in ["content_info", "transcription_result", "last_checkpoint"]:
            if d.get(json_field):
                try:
                    d[json_field] = json.loads(d[json_field])
                except json.JSONDecodeError:
                    pass

        return d

    # ============ AI Settings Methods ============

    def get_ai_settings(self) -> Optional[dict]:
        """Get the current AI provider settings."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ai_settings WHERE is_default = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if row:
                result = dict(row)
                # Decrypt API key if present
                if result.get("api_key"):
                    result["api_key"] = _decrypt_secret(result["api_key"])
                return result
        return None

    def save_ai_settings(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> dict:
        """Save AI provider settings.

        Args:
            provider: Provider name (ollama, openai, anthropic, groq, deepseek, custom)
            model: Model name/identifier
            api_key: API key for cloud providers
            base_url: Base URL for custom endpoints or Ollama

        Returns:
            The saved settings
        """
        now = datetime.utcnow().isoformat()

        # Encrypt API key before storing
        encrypted_key = _encrypt_secret(api_key) if api_key else None

        with self._get_conn() as conn:
            # Check if settings exist
            existing = conn.execute(
                "SELECT id FROM ai_settings WHERE is_default = 1"
            ).fetchone()

            if existing:
                # Update existing settings
                conn.execute("""
                    UPDATE ai_settings
                    SET provider = ?, model = ?, api_key = ?, base_url = ?, updated_at = ?
                    WHERE is_default = 1
                """, (provider, model, encrypted_key, base_url, now))
            else:
                # Insert new settings
                conn.execute("""
                    INSERT INTO ai_settings (provider, model, api_key, base_url, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                """, (provider, model, encrypted_key, base_url, now, now))

        logger.info(f"Saved AI settings: provider={provider}, model={model}")
        return self.get_ai_settings()

    # ============ Obsidian Settings Methods ============

    def get_obsidian_settings(self) -> Optional[dict]:
        """Get the current Obsidian settings."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM obsidian_settings WHERE is_default = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if row:
                result = dict(row)
                # Parse default_tags from comma-separated string to list
                if result.get("default_tags"):
                    result["default_tags"] = [
                        tag.strip() for tag in result["default_tags"].split(",")
                    ]
                else:
                    result["default_tags"] = []
                return result
        return None

    def save_obsidian_settings(
        self,
        vault_path: str,
        subfolder: Optional[str] = "Sift",
        template: Optional[str] = None,
        default_tags: Optional[list[str]] = None,
    ) -> dict:
        """Save Obsidian settings.

        Args:
            vault_path: Path to Obsidian vault
            subfolder: Subfolder within vault for notes
            template: Custom template for notes
            default_tags: Default tags for exported notes

        Returns:
            The saved settings
        """
        now = datetime.utcnow().isoformat()

        # Convert tags list to comma-separated string
        tags_str = ",".join(default_tags) if default_tags else "sift,transcript"

        with self._get_conn() as conn:
            # Check if settings exist
            existing = conn.execute(
                "SELECT id FROM obsidian_settings WHERE is_default = 1"
            ).fetchone()

            if existing:
                # Update existing settings
                conn.execute("""
                    UPDATE obsidian_settings
                    SET vault_path = ?, subfolder = ?, template = ?, default_tags = ?, updated_at = ?
                    WHERE is_default = 1
                """, (vault_path, subfolder, template, tags_str, now))
            else:
                # Insert new settings
                conn.execute("""
                    INSERT INTO obsidian_settings (vault_path, subfolder, template, default_tags, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                """, (vault_path, subfolder, template, tags_str, now, now))

        logger.info(f"Saved Obsidian settings: vault_path={vault_path}, subfolder={subfolder}")
        return self.get_obsidian_settings()

    # ===== P18: Knowledge layer accessors =====

    def set_knowledge_status(self, job_id: str, status: str) -> None:
        """Set the knowledge_status on a job.

        Valid values: 'none' | 'pending' | 'extracting' | 'complete' | 'failed'.
        Used by the extractor and the (Phase C) backfill worker.
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET knowledge_status = ?, updated_at = ? WHERE job_id = ?",
                (status, datetime.utcnow().isoformat(), job_id),
            )

    def get_knowledge_status(self, job_id: str) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT knowledge_status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return row["knowledge_status"] if row else None

    def upsert_claims(self, claims: list[dict]) -> int:
        """Upsert a batch of claim dicts. Returns the number of rows written.

        Each dict must contain the full Claim shape. We upsert by claim_id so
        re-extracting the same episode is idempotent — same input produces the
        same id, no duplicates.
        """
        if not claims:
            return 0

        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            for c in claims:
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, episode_id, text, speaker, timestamp_start,
                        timestamp_end, claim_type, confidence, evidence_excerpt,
                        entity_ids, topic_ids, source_url, extraction_version,
                        schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(claim_id) DO UPDATE SET
                        text = excluded.text,
                        speaker = excluded.speaker,
                        timestamp_start = excluded.timestamp_start,
                        timestamp_end = excluded.timestamp_end,
                        claim_type = excluded.claim_type,
                        confidence = excluded.confidence,
                        evidence_excerpt = excluded.evidence_excerpt,
                        entity_ids = excluded.entity_ids,
                        topic_ids = excluded.topic_ids,
                        source_url = excluded.source_url,
                        extraction_version = excluded.extraction_version,
                        schema_version = excluded.schema_version
                    """,
                    (
                        c["claim_id"],
                        c["episode_id"],
                        c["text"],
                        c.get("speaker"),
                        c["timestamp_start"],
                        c["timestamp_end"],
                        c["claim_type"],
                        c["confidence"],
                        c["evidence_excerpt"],
                        json.dumps(c.get("entity_ids", [])),
                        json.dumps(c.get("topic_ids", [])),
                        c.get("source_url"),
                        c["extraction_version"],
                        c["schema_version"],
                        c.get("created_at") or now,
                    ),
                )
        return len(claims)

    def get_claims_for_job(
        self, job_id: str, min_confidence: float = 0.0
    ) -> list[dict]:
        """Return all claims for an episode, ordered by timestamp."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM claims
                WHERE episode_id = ? AND confidence >= ?
                ORDER BY timestamp_start ASC
                """,
                (job_id, min_confidence),
            ).fetchall()
            return [self._claim_row_to_dict(r) for r in rows]

    def query_claims(
        self,
        *,
        claim_type: Optional[str] = None,
        speaker: Optional[str] = None,
        min_confidence: float = 0.0,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Library-wide claim query with filters."""
        clauses: list[str] = ["confidence >= ?"]
        params: list = [min_confidence]
        if claim_type:
            clauses.append("claim_type = ?")
            params.append(claim_type)
        if speaker:
            clauses.append("speaker = ?")
            params.append(speaker)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM claims
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return [self._claim_row_to_dict(r) for r in rows]

    def delete_claims_for_job(self, job_id: str) -> int:
        """Wipe claims for an episode (used before re-extraction)."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM claims WHERE episode_id = ?", (job_id,))
            return cur.rowcount

    def replace_claims_for_job(
        self,
        job_id: str,
        claims: list[dict],
        entities: Optional[list[dict]] = None,
        mentions: Optional[list[dict]] = None,
    ) -> int:
        """Atomically replace all claims for an episode (delete + insert in one tx).

        Closes the data-integrity hole where a separate delete + upsert
        could leave the episode with zero claims if the second call lost
        a race or the process crashed in between. The whole operation
        commits or rolls back as a unit because both statements share a
        single connection inside one `_get_conn()` context.

        Phase B extension: optionally upsert discovered entities and replace
        entity_mentions for this episode in the same transaction. Entities
        are global (PK on `entity_id`) — we upsert, never wipe — but an
        episode's mentions are episode-scoped so we delete-then-insert them
        alongside the claims.
        """
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM claims WHERE episode_id = ?", (job_id,))
            if mentions is not None:
                conn.execute(
                    "DELETE FROM entity_mentions WHERE episode_id = ?",
                    (job_id,),
                )
            if entities:
                for e in entities:
                    self._upsert_entity_row(conn, e, now)
            for c in claims:
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, episode_id, text, speaker, timestamp_start,
                        timestamp_end, claim_type, confidence, evidence_excerpt,
                        entity_ids, topic_ids, source_url, extraction_version,
                        schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c["claim_id"],
                        c["episode_id"],
                        c["text"],
                        c.get("speaker"),
                        c["timestamp_start"],
                        c["timestamp_end"],
                        c["claim_type"],
                        c["confidence"],
                        c["evidence_excerpt"],
                        json.dumps(c.get("entity_ids", [])),
                        json.dumps(c.get("topic_ids", [])),
                        c.get("source_url"),
                        c["extraction_version"],
                        c["schema_version"],
                        c.get("created_at") or now,
                    ),
                )
            if mentions:
                for m in mentions:
                    self._insert_mention_row(conn, m, now)
        return len(claims)

    # ===== P18 Phase B: Entity + Mention accessors =====

    @staticmethod
    def _upsert_entity_row(conn: sqlite3.Connection, e: dict, now: str) -> None:
        """Internal: upsert an entity on an existing connection.

        Merge semantics: on conflict on `entity_id` we update `name` +
        `confidence` (latest wins) and union the `aliases` list so novel
        surface forms accumulate across episodes.
        """
        row = conn.execute(
            "SELECT aliases FROM entities WHERE entity_id = ?",
            (e["entity_id"],),
        ).fetchone()
        existing_aliases: list[str] = []
        if row and row["aliases"]:
            try:
                existing_aliases = json.loads(row["aliases"])
            except (TypeError, json.JSONDecodeError):
                existing_aliases = []
        incoming = e.get("aliases", []) or []
        merged: list[str] = list(existing_aliases)
        for a in incoming:
            if a and a not in merged:
                merged.append(a)
        conn.execute(
            """
            INSERT INTO entities (
                entity_id, slug, name, entity_type, aliases, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                name = excluded.name,
                entity_type = excluded.entity_type,
                aliases = excluded.aliases,
                confidence = excluded.confidence
            """,
            (
                e["entity_id"],
                e["slug"],
                e["name"],
                e["entity_type"],
                json.dumps(merged),
                e.get("confidence", 1.0),
                e.get("created_at") or now,
            ),
        )

    @staticmethod
    def _insert_mention_row(conn: sqlite3.Connection, m: dict, now: str) -> None:
        conn.execute(
            """
            INSERT INTO entity_mentions (
                entity_id, episode_id, claim_id, chunk_id, raw_text,
                start_char, end_char, timestamp, speaker, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m["entity_id"],
                m["episode_id"],
                m.get("claim_id"),
                m.get("chunk_id"),
                m["raw_text"],
                m.get("start_char"),
                m.get("end_char"),
                m.get("timestamp"),
                m.get("speaker"),
                m.get("created_at") or now,
            ),
        )

    def upsert_entity(self, entity: dict) -> None:
        """Upsert a single entity."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._upsert_entity_row(conn, entity, now)

    def get_entity_by_id(self, entity_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            return self._entity_row_to_dict(row) if row else None

    def get_entity_by_slug(self, slug: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE slug = ?", (slug,)
            ).fetchone()
            return self._entity_row_to_dict(row) if row else None

    def slug_exists(self, slug: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM entities WHERE slug = ?", (slug,)
            ).fetchone()
            return row is not None

    def list_entities(
        self,
        *,
        entity_type: Optional[str] = None,
        slug: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if slug:
            clauses.append("slug = ?")
            params.append(slug)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM entities {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._entity_row_to_dict(r) for r in rows]

    def find_entity_ids_by_type(self, entity_type: str) -> list[str]:
        """Candidate set for the canonicalizer's cosine scan."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ?",
                (entity_type,),
            ).fetchall()
        return [r["entity_id"] for r in rows]

    def add_entity_mention(self, mention: dict) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._insert_mention_row(conn, mention, now)

    def get_mentions_for_entity(
        self, entity_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM entity_mentions
                WHERE entity_id = ?
                ORDER BY episode_id ASC, timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (entity_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_mentions_for_episode(self, episode_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM entity_mentions WHERE episode_id = ?", (episode_id,)
            )
            return cur.rowcount

    @staticmethod
    def _entity_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        raw = d.get("aliases")
        try:
            d["aliases"] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            d["aliases"] = []
        return d

    def get_task_presets(self) -> dict[str, dict]:
        """Read `ai_settings.task_presets`, decrypting any nested api_keys.

        Mirrors the encryption boundary that `ai_settings.api_key` already
        enforces — secrets stored inside the JSON column round-trip through
        `_decrypt_secret` so an attacker dumping the raw column doesn't
        recover usable provider credentials.
        """
        settings = self.get_ai_settings()
        if not settings:
            return {}
        raw = settings.get("task_presets")
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("task_presets contained invalid JSON; ignoring")
                return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict] = {}
        for task, preset in raw.items():
            if not isinstance(preset, dict):
                # Defensive: drop malformed entries instead of crashing every
                # call to get_provider_for_task() that touches them.
                logger.warning("task_presets[%s] is not a dict; skipping", task)
                continue
            preset = dict(preset)  # copy so we don't mutate the cached row
            api_key = preset.get("api_key")
            if api_key:
                preset["api_key"] = _decrypt_secret(api_key)
            out[task] = preset
        return out

    def set_task_presets(self, presets: dict[str, dict]) -> None:
        """Write `ai_settings.task_presets`, encrypting any nested api_keys.

        Caller must ensure an `ai_settings` row exists (typically by calling
        `save_ai_settings(...)` first); this method only updates the JSON
        column on the existing default row.
        """
        encrypted: dict[str, dict] = {}
        for task, preset in presets.items():
            if not isinstance(preset, dict):
                continue
            p = dict(preset)
            api_key = p.get("api_key")
            if api_key:
                p["api_key"] = _encrypt_secret(api_key)
            encrypted[task] = p

        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM ai_settings WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            if not row:
                logger.warning(
                    "set_task_presets: no default ai_settings row; "
                    "call save_ai_settings(...) first"
                )
                return
            conn.execute(
                "UPDATE ai_settings SET task_presets = ?, updated_at = ? WHERE id = ?",
                (json.dumps(encrypted), now, row["id"]),
            )

    @staticmethod
    def _claim_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # JSON-array columns
        for k in ("entity_ids", "topic_ids"):
            raw = d.get(k)
            try:
                d[k] = json.loads(raw) if raw else []
            except (TypeError, json.JSONDecodeError):
                d[k] = []
        return d

    def record_extraction_failure(
        self,
        *,
        episode_id: str,
        chunk_index: Optional[int],
        error: str,
        raw_output: Optional[str] = None,
        extraction_version: Optional[int] = None,
        model: Optional[str] = None,
    ) -> None:
        """Quarantine a malformed extractor response so the pipeline never
        crashes on bad LLM output."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO extraction_failures
                    (episode_id, chunk_index, raw_output, error,
                     extraction_version, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    chunk_index,
                    raw_output,
                    error,
                    extraction_version,
                    model,
                    datetime.utcnow().isoformat(),
                ),
            )


# Global instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create the global job store instance."""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store
