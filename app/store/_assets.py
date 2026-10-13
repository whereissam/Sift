"""Assets mixin: durable content identity (migration Slice 1).

An asset is the durable identity of a piece of media, derived from its
canonical source. Multiple jobs (execution attempts) may reference the
same asset. See docs/ingestion-api-migration.md §2/§4.
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from sift_core.asset_identity import CanonicalSource, canonical_source_for_job

logger = logging.getLogger(__name__)


class _AssetsMixin:
    """Methods that operate on the ``assets`` table."""

    def find_or_create_asset(
        self,
        source: CanonicalSource,
        original_source: Optional[str] = None,
    ) -> str:
        """Return the asset_id for a canonical source, creating it if new."""
        with self._get_conn() as conn:
            return self._find_or_create_asset_tx(conn, source, original_source)

    def _find_or_create_asset_tx(
        self,
        conn: sqlite3.Connection,
        source: CanonicalSource,
        original_source: Optional[str] = None,
    ) -> str:
        """Find-or-create inside an existing transaction.

        Relies on UNIQUE(source_fingerprint): INSERT OR IGNORE means exactly
        one row wins under concurrency, then the SELECT returns it.
        """
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO assets (
                asset_id, source_type, canonical_source, source_fingerprint,
                original_source, platform, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                source.source_type,
                source.canonical_source,
                source.fingerprint,
                original_source,
                source.platform,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT asset_id FROM assets WHERE source_fingerprint = ?",
            (source.fingerprint,),
        ).fetchone()
        return row["asset_id"]

    def get_asset(self, asset_id: str) -> Optional[dict]:
        """Get an asset by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_asset_by_fingerprint(self, fingerprint: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE source_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            return dict(row) if row else None

    def get_asset_for_episode(self, episode_id: str) -> Optional[str]:
        """Compatibility bridge: knowledge records key on episode_id, which
        is historically the job_id. Resolve it to the job's asset."""
        job = self.get_job(episode_id)
        return job.get("asset_id") if job else None

    def get_asset_jobs(self, asset_id: str) -> list[dict]:
        """All jobs (execution attempts) referencing an asset."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE asset_id = ? ORDER BY created_at ASC",
                (asset_id,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    # -- backfill -----------------------------------------------------------

    _ASSETS_BACKFILL_MARKER = "assets_backfilled"

    def _backfill_assets(self, conn: sqlite3.Connection) -> None:
        """One-time link of pre-migration jobs to assets.

        Idempotent: guarded by a schema_meta marker written only on
        completion, and find_or_create is a no-op for existing fingerprints,
        so a crash mid-backfill re-runs cleanly.
        """
        done = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (self._ASSETS_BACKFILL_MARKER,),
        ).fetchone()
        if done:
            return

        rows = conn.execute(
            "SELECT job_id, source_url FROM jobs "
            "WHERE asset_id IS NULL AND source_url IS NOT NULL"
        ).fetchall()

        linked = skipped = 0
        for row in rows:
            source = canonical_source_for_job(row["source_url"])
            if source is None:
                skipped += 1  # resume:// and other non-durable pseudo-sources
                continue
            asset_id = self._find_or_create_asset_tx(
                conn, source, original_source=row["source_url"]
            )
            conn.execute(
                "UPDATE jobs SET asset_id = ? WHERE job_id = ?",
                (asset_id, row["job_id"]),
            )
            linked += 1

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            (self._ASSETS_BACKFILL_MARKER, datetime.utcnow().isoformat()),
        )
        if linked or skipped:
            logger.info(
                "Asset backfill: linked %d jobs, skipped %d without durable identity",
                linked,
                skipped,
            )
