"""Persistent subscription storage using SQLite."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SubscriptionType(str, Enum):
    """Subscription types."""
    RSS = "rss"
    YOUTUBE_CHANNEL = "youtube_channel"
    YOUTUBE_PLAYLIST = "youtube_playlist"


class SubscriptionPlatform(str, Enum):
    """Supported platforms for subscriptions."""
    PODCAST = "podcast"
    YOUTUBE = "youtube"


class SubscriptionItemStatus(str, Enum):
    """Status states for subscription items."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SubscriptionStore:
    """SQLite-based persistent subscription storage."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = db_path
        else:
            from ..config import get_settings
            settings = get_settings()
            self.db_path = Path(settings.download_dir) / "subscriptions.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """Get database connection with context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            # Subscriptions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    subscription_type TEXT NOT NULL,
                    source_url TEXT,
                    source_id TEXT,
                    platform TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    auto_transcribe INTEGER DEFAULT 0,
                    transcribe_model TEXT DEFAULT 'base',
                    transcribe_language TEXT,
                    download_limit INTEGER DEFAULT 10,
                    output_format TEXT DEFAULT 'm4a',
                    quality TEXT DEFAULT 'high',
                    output_dir TEXT,
                    last_checked_at TEXT,
                    last_new_content_at TEXT,
                    total_downloaded INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Subscription items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscription_items (
                    id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    content_id TEXT NOT NULL,
                    content_url TEXT NOT NULL,
                    title TEXT,
                    published_at TEXT,
                    status TEXT DEFAULT 'pending',
                    job_id TEXT,
                    file_path TEXT,
                    transcription_path TEXT,
                    error TEXT,
                    discovered_at TEXT NOT NULL,
                    downloaded_at TEXT,
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
                    UNIQUE(subscription_id, content_id)
                )
            """)

            # Indexes for faster queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled "
                "ON subscriptions(enabled)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_subscription "
                "ON subscription_items(subscription_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_status "
                "ON subscription_items(status)"
            )

    # ============ Subscription CRUD ============

    def create_subscription(
        self,
        subscription_id: str,
        name: str,
        subscription_type: SubscriptionType,
        platform: SubscriptionPlatform,
        source_url: Optional[str] = None,
        source_id: Optional[str] = None,
        auto_transcribe: bool = False,
        transcribe_model: str = "base",
        transcribe_language: Optional[str] = None,
        download_limit: int = 10,
        output_format: str = "m4a",
        quality: str = "high",
        output_dir: Optional[str] = None,
    ) -> dict:
        """Create a new subscription."""
        now = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO subscriptions (
                    id, name, subscription_type, source_url, source_id, platform,
                    enabled, auto_transcribe, transcribe_model, transcribe_language,
                    download_limit, output_format, quality, output_dir,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                subscription_id, name, subscription_type.value, source_url, source_id,
                platform.value, 1, int(auto_transcribe), transcribe_model,
                transcribe_language, download_limit, output_format, quality,
                output_dir, now, now
            ))

        logger.info(f"Created subscription {subscription_id} ({name})")
        return self.get_subscription(subscription_id)

    def get_subscription(self, subscription_id: str) -> Optional[dict]:
        """Get subscription by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
            ).fetchone()

            if row:
                return self._row_to_subscription_dict(row)
        return None

    def list_subscriptions(
        self,
        enabled_only: bool = False,
        platform: Optional[SubscriptionPlatform] = None,
    ) -> list[dict]:
        """List all subscriptions with optional filtering."""
        query = "SELECT * FROM subscriptions WHERE 1=1"
        params = []

        if enabled_only:
            query += " AND enabled = 1"

        if platform:
            query += " AND platform = ?"
            params.append(platform.value)

        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_subscription_dict(row) for row in rows]

    # Allowlist of columns that can be updated
    _UPDATABLE_COLUMNS = {
        "name", "url", "subscription_type", "platform", "enabled",
        "check_interval", "auto_transcribe", "output_format", "quality",
        "last_checked_at", "last_item_at", "error", "updated_at",
    }

    def update_subscription(self, subscription_id: str, **kwargs) -> Optional[dict]:
        """Update subscription fields."""
        kwargs["updated_at"] = datetime.utcnow().isoformat()

        # Reject any column names not in the allowlist
        invalid_keys = set(kwargs.keys()) - self._UPDATABLE_COLUMNS
        if invalid_keys:
            raise ValueError(f"Invalid column names: {invalid_keys}")

        # Convert boolean fields to int
        for bool_field in ["enabled", "auto_transcribe"]:
            if bool_field in kwargs:
                kwargs[bool_field] = int(kwargs[bool_field])

        # Convert enum fields to value
        if "subscription_type" in kwargs and isinstance(kwargs["subscription_type"], SubscriptionType):
            kwargs["subscription_type"] = kwargs["subscription_type"].value
        if "platform" in kwargs and isinstance(kwargs["platform"], SubscriptionPlatform):
            kwargs["platform"] = kwargs["platform"].value

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [subscription_id]

        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE subscriptions SET {set_clause} WHERE id = ?",
                values
            )

        return self.get_subscription(subscription_id)

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete a subscription and all its items."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE id = ?", (subscription_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted subscription {subscription_id}")
            return deleted

    def set_last_checked(self, subscription_id: str) -> None:
        """Update last_checked_at timestamp."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
                (now, now, subscription_id)
            )

    def set_last_new_content(self, subscription_id: str) -> None:
        """Update last_new_content_at timestamp."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE subscriptions SET last_new_content_at = ?, updated_at = ? WHERE id = ?",
                (now, now, subscription_id)
            )

    def increment_total_downloaded(self, subscription_id: str) -> None:
        """Increment total_downloaded counter."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE subscriptions SET total_downloaded = total_downloaded + 1, updated_at = ? WHERE id = ?",
                (now, subscription_id)
            )

    # ============ Subscription Item CRUD ============

    def create_item(
        self,
        item_id: str,
        subscription_id: str,
        content_id: str,
        content_url: str,
        title: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a new subscription item."""
        now = datetime.utcnow().isoformat()

        try:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT INTO subscription_items (
                        id, subscription_id, content_id, content_url, title,
                        published_at, status, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, subscription_id, content_id, content_url, title,
                    published_at, SubscriptionItemStatus.PENDING.value, now
                ))
            return self.get_item(item_id)
        except sqlite3.IntegrityError:
            # Duplicate item (subscription_id, content_id)
            logger.debug(f"Item already exists: {subscription_id}/{content_id}")
            return None

    def get_item(self, item_id: str) -> Optional[dict]:
        """Get item by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM subscription_items WHERE id = ?", (item_id,)
            ).fetchone()

            if row:
                return self._row_to_item_dict(row)
        return None

    def get_item_by_content_id(
        self, subscription_id: str, content_id: str
    ) -> Optional[dict]:
        """Get item by subscription and content ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM subscription_items WHERE subscription_id = ? AND content_id = ?",
                (subscription_id, content_id)
            ).fetchone()

            if row:
                return self._row_to_item_dict(row)
        return None

    def list_items(
        self,
        subscription_id: str,
        status: Optional[SubscriptionItemStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List items for a subscription."""
        query = "SELECT * FROM subscription_items WHERE subscription_id = ?"
        params = [subscription_id]

        if status:
            query += " AND status = ?"
            params.append(status.value)

        query += " ORDER BY published_at DESC, discovered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_item_dict(row) for row in rows]

    def get_pending_items(self, subscription_id: str, limit: int = 10) -> list[dict]:
        """Get pending items for a subscription, ordered by publish date."""
        return self.list_items(
            subscription_id,
            status=SubscriptionItemStatus.PENDING,
            limit=limit,
        )

    def update_item(self, item_id: str, **kwargs) -> Optional[dict]:
        """Update item fields."""
        # Convert enum fields to value
        if "status" in kwargs and isinstance(kwargs["status"], SubscriptionItemStatus):
            kwargs["status"] = kwargs["status"].value

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [item_id]

        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE subscription_items SET {set_clause} WHERE id = ?",
                values
            )

        return self.get_item(item_id)

    def set_item_status(
        self,
        item_id: str,
        status: SubscriptionItemStatus,
        error: Optional[str] = None,
        job_id: Optional[str] = None,
        file_path: Optional[str] = None,
        transcription_path: Optional[str] = None,
    ) -> Optional[dict]:
        """Update item status."""
        updates = {"status": status.value}

        if error is not None:
            updates["error"] = error
        if job_id is not None:
            updates["job_id"] = job_id
        if file_path is not None:
            updates["file_path"] = file_path
        if transcription_path is not None:
            updates["transcription_path"] = transcription_path
        if status == SubscriptionItemStatus.COMPLETED:
            updates["downloaded_at"] = datetime.utcnow().isoformat()

        return self.update_item(item_id, **updates)

    def delete_item(self, item_id: str) -> bool:
        """Delete an item."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM subscription_items WHERE id = ?", (item_id,)
            )
            return cursor.rowcount > 0

    def count_items(
        self,
        subscription_id: str,
        status: Optional[SubscriptionItemStatus] = None,
    ) -> int:
        """Count items for a subscription."""
        query = "SELECT COUNT(*) FROM subscription_items WHERE subscription_id = ?"
        params = [subscription_id]

        if status:
            query += " AND status = ?"
            params.append(status.value)

        with self._get_conn() as conn:
            return conn.execute(query, params).fetchone()[0]

    def get_oldest_completed_items(
        self, subscription_id: str, limit: int
    ) -> list[dict]:
        """Get oldest completed items (for cleanup when limit exceeded)."""
        query = """
            SELECT * FROM subscription_items
            WHERE subscription_id = ? AND status = ?
            ORDER BY downloaded_at ASC
            LIMIT ?
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                query,
                (subscription_id, SubscriptionItemStatus.COMPLETED.value, limit)
            ).fetchall()
            return [self._row_to_item_dict(row) for row in rows]

    # ============ Helper Methods ============

    def _row_to_subscription_dict(self, row: sqlite3.Row) -> dict:
        """Convert database row to subscription dictionary."""
        d = dict(row)
        # Convert integer booleans back to Python bool
        d["enabled"] = bool(d.get("enabled", 1))
        d["auto_transcribe"] = bool(d.get("auto_transcribe", 0))
        return d

    def _row_to_item_dict(self, row: sqlite3.Row) -> dict:
        """Convert database row to item dictionary."""
        return dict(row)


# Global instance
_subscription_store: Optional[SubscriptionStore] = None


def get_subscription_store() -> SubscriptionStore:
    """Get or create the global subscription store instance."""
    global _subscription_store
    if _subscription_store is None:
        _subscription_store = SubscriptionStore()
    return _subscription_store
