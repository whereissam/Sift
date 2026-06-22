"""P18 Phase C.3: knowledge backfill control plane (state machine + locking).

Split from ``_knowledge.py`` because this is the *orchestration* layer —
claim-locks, the pending queue, stale-lock reaping, and version bumps — as
opposed to the knowledge *data* accessors. Keeping it in its own mixin keeps
the lock semantics visible in one place.

Run-state model (on the ``jobs`` row):

    none ──mark_pending──▶ pending ──acquire_lock──▶ running
                                                      │
                              ┌───────────────────────┤
                              ▼                        ▼
                            ready                    failed ──(retry)──▶ pending
                            (knowledge_version++)

``ready``/``failed`` clear the lock columns. ``running`` jobs whose lock is
older than the TTL are reclaimable (crashed worker) — either lazily at
``acquire_knowledge_lock`` time or eagerly via ``reap_stale_knowledge_locks``.

The synchronous extract route's legacy ``extracting``/``complete`` values map
onto ``running``/``ready`` and are still accepted everywhere.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Canonical run-states for the backfill path. `none` = never attempted.
RUN_STATE_NONE = "none"
RUN_STATE_PENDING = "pending"
RUN_STATE_RUNNING = "running"
RUN_STATE_READY = "ready"
RUN_STATE_FAILED = "failed"

# Legacy aliases written by the synchronous extract route, treated as
# acquirable / terminal equivalents so the two paths interoperate.
_ACQUIRABLE_STATES = ("none", "pending", "failed", "extracting")


class _BackfillMixin:
    """Lock + state-machine methods for the Phase C.3 backfill worker."""

    # ===== Version =====

    def get_knowledge_version(self, job_id: str) -> Optional[int]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT knowledge_version FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return row["knowledge_version"] if row else None

    # ===== Lock acquire / release =====

    def acquire_knowledge_lock(
        self, job_id: str, worker_id: str, ttl_seconds: int = 900
    ) -> bool:
        """Atomically claim a job for knowledge extraction.

        Succeeds (and flips the job to ``running``) when the job is in an
        acquirable state (``none``/``pending``/``failed``/legacy
        ``extracting``) **or** it is ``running`` with a lock older than
        ``ttl_seconds`` (a crashed worker — we reclaim it). Returns ``False``
        without side effects when the job is already ``ready`` or freshly
        locked by another worker.

        The whole decision is a single conditional UPDATE so two workers
        racing for the same job can never both win.
        """
        now = datetime.utcnow()
        cutoff = (now - timedelta(seconds=ttl_seconds)).isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET
                    knowledge_status = 'running',
                    knowledge_locked_at = ?,
                    knowledge_worker_id = ?,
                    updated_at = ?
                WHERE job_id = ?
                  AND (
                    knowledge_status IN ('none', 'pending', 'failed', 'extracting')
                    OR (
                        knowledge_status = 'running'
                        AND (knowledge_locked_at IS NULL OR knowledge_locked_at < ?)
                    )
                  )
                """,
                (now.isoformat(), worker_id, now.isoformat(), job_id, cutoff),
            )
            return cur.rowcount == 1

    def release_knowledge_lock(
        self,
        job_id: str,
        *,
        status: str = RUN_STATE_READY,
        bump_version: bool = False,
    ) -> None:
        """Release the lock and set a terminal (or back-to-pending) state.

        ``status=ready`` on success (pass ``bump_version=True`` to advance
        ``knowledge_version``), ``failed`` on error, ``pending`` to requeue.
        Always clears ``knowledge_locked_at``/``knowledge_worker_id``.
        """
        now = datetime.utcnow().isoformat()
        version_clause = (
            "knowledge_version = knowledge_version + 1," if bump_version else ""
        )
        with self._get_conn() as conn:
            conn.execute(
                f"""
                UPDATE jobs SET
                    knowledge_status = ?,
                    {version_clause}
                    knowledge_locked_at = NULL,
                    knowledge_worker_id = NULL,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (status, now, job_id),
            )

    def reap_stale_knowledge_locks(self, ttl_seconds: int = 900) -> int:
        """Requeue ``running`` jobs whose lock is older than the TTL.

        For crashed workers that never released their lock. Returns the
        number of jobs reset to ``pending``. ``acquire_knowledge_lock``
        already reclaims stale locks lazily; this is the eager sweep the
        worker runs each tick so status reporting stays honest.
        """
        cutoff = (datetime.utcnow() - timedelta(seconds=ttl_seconds)).isoformat()
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET
                    knowledge_status = 'pending',
                    knowledge_locked_at = NULL,
                    knowledge_worker_id = NULL,
                    updated_at = ?
                WHERE knowledge_status = 'running'
                  AND (knowledge_locked_at IS NULL OR knowledge_locked_at < ?)
                """,
                (now, cutoff),
            )
            return cur.rowcount

    # ===== Pending queue =====

    def mark_jobs_pending_for_backfill(self) -> int:
        """Mark every never-attempted job that *has a transcript* as pending.

        The first-deploy seed: any completed transcription with no knowledge
        yet (``knowledge_status='none'``) becomes a backfill candidate. Jobs
        without a persisted transcript are skipped — there's nothing to
        extract from. Idempotent: re-running only touches ``none`` rows.
        """
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET knowledge_status = 'pending', updated_at = ?
                WHERE (knowledge_status = 'none' OR knowledge_status IS NULL)
                  AND transcription_result IS NOT NULL
                """,
                (now,),
            )
            return cur.rowcount

    def enqueue_knowledge_job(self, job_id: str) -> bool:
        """Idempotently mark a single job pending.

        No-op (returns ``False``) when the job is already pending, running,
        or ready — only ``none``/``failed`` jobs flip to ``pending``. Returns
        ``True`` when the state actually changed.
        """
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET knowledge_status = 'pending', updated_at = ?
                WHERE job_id = ?
                  AND (knowledge_status IN ('none', 'failed') OR knowledge_status IS NULL)
                """,
                (now, job_id),
            )
            return cur.rowcount == 1

    def list_pending_knowledge_jobs(self, limit: int = 50) -> list[dict]:
        """Return pending backfill jobs in priority order.

        Ordering: higher ``priority`` first (reuses the existing 1-10 queue
        priority column — subscription-driven jobs can be created with a
        boosted priority), then most-recent first. This realizes the
        "recent → high-value" intent of the locked design without a separate
        priority table.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE knowledge_status = 'pending'
                  AND transcription_result IS NOT NULL
                ORDER BY priority DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def count_pending_knowledge_jobs(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM jobs
                WHERE knowledge_status = 'pending'
                  AND transcription_result IS NOT NULL
                """
            ).fetchone()
            return row["n"] if row else 0

    def get_knowledge_status_counts(self) -> dict[str, int]:
        """Counts grouped by knowledge_status (legacy aliases folded in).

        Powers ``GET /api/knowledge/backfill-status``. Legacy ``extracting``
        is folded into ``running`` and ``complete`` into ``ready`` so the
        report speaks one vocabulary.
        """
        alias = {"extracting": "running", "complete": "ready"}
        out = {
            RUN_STATE_NONE: 0,
            RUN_STATE_PENDING: 0,
            RUN_STATE_RUNNING: 0,
            RUN_STATE_READY: 0,
            RUN_STATE_FAILED: 0,
        }
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(knowledge_status, 'none') AS s, COUNT(*) AS n
                FROM jobs GROUP BY s
                """
            ).fetchall()
        for r in rows:
            key = alias.get(r["s"], r["s"])
            out[key] = out.get(key, 0) + r["n"]
        return out
