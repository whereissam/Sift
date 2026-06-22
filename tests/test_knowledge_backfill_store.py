"""Tests for the P18 Phase C.3 backfill control plane on JobStore.

Covers the state machine + claim-lock: enqueue, acquire/release, stale-lock
reaping, pending-queue priority ordering, and status counts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.job_store import JobStore
from app.core.job_store._enums import JobType


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "backfill.db")


def _job_with_transcript(store: JobStore, job_id: str, *, priority: int = 5) -> None:
    store.create_job(job_id, JobType.TRANSCRIBE, priority=priority)
    store.update_job(
        job_id,
        transcription_result={"segments": [{"start": 0, "end": 1, "text": "hi"}]},
    )


class TestEnqueue:
    def test_enqueue_none_job_with_transcript(self, store: JobStore):
        _job_with_transcript(store, "j1")
        assert store.enqueue_knowledge_job("j1") is True
        assert store.get_knowledge_status("j1") == "pending"

    def test_enqueue_is_idempotent_on_pending(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        # Second enqueue is a no-op — already pending.
        assert store.enqueue_knowledge_job("j1") is False

    def test_enqueue_failed_job_requeues(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.set_knowledge_status("j1", "failed")
        assert store.enqueue_knowledge_job("j1") is True
        assert store.get_knowledge_status("j1") == "pending"

    def test_enqueue_ready_job_is_noop(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.set_knowledge_status("j1", "ready")
        assert store.enqueue_knowledge_job("j1") is False

    def test_mark_pending_seeds_only_transcribed_none_jobs(self, store: JobStore):
        _job_with_transcript(store, "has_transcript")
        store.create_job("no_transcript", JobType.TRANSCRIBE)
        n = store.mark_jobs_pending_for_backfill()
        assert n == 1
        assert store.get_knowledge_status("has_transcript") == "pending"
        assert store.get_knowledge_status("no_transcript") == "none"

    def test_mark_pending_is_idempotent(self, store: JobStore):
        _job_with_transcript(store, "j1")
        assert store.mark_jobs_pending_for_backfill() == 1
        assert store.mark_jobs_pending_for_backfill() == 0


class TestLock:
    def test_acquire_pending_flips_to_running(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        assert store.acquire_knowledge_lock("j1", "worker-a") is True
        assert store.get_knowledge_status("j1") == "running"

    def test_second_acquire_fails_while_locked(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        assert store.acquire_knowledge_lock("j1", "worker-a") is True
        # Fresh lock — a competing worker can't steal it.
        assert store.acquire_knowledge_lock("j1", "worker-b") is False

    def test_acquire_reclaims_stale_lock(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        store.acquire_knowledge_lock("j1", "worker-a", ttl_seconds=900)
        # Backdate the lock so it's stale.
        stale = (datetime.utcnow() - timedelta(seconds=1000)).isoformat()
        store.update_job("j1", knowledge_locked_at=stale)
        assert store.acquire_knowledge_lock("j1", "worker-b", ttl_seconds=900) is True

    def test_cannot_acquire_ready_job(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.set_knowledge_status("j1", "ready")
        assert store.acquire_knowledge_lock("j1", "worker-a") is False

    def test_release_ready_bumps_version_and_clears_lock(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        store.acquire_knowledge_lock("j1", "worker-a")
        store.release_knowledge_lock("j1", status="ready", bump_version=True)
        assert store.get_knowledge_status("j1") == "ready"
        assert store.get_knowledge_version("j1") == 1
        job = store.get_job("j1")
        assert job["knowledge_locked_at"] is None
        assert job["knowledge_worker_id"] is None

    def test_release_failed_does_not_bump_version(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        store.acquire_knowledge_lock("j1", "worker-a")
        store.release_knowledge_lock("j1", status="failed")
        assert store.get_knowledge_status("j1") == "failed"
        assert store.get_knowledge_version("j1") == 0

    def test_reap_stale_locks_requeues(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        store.acquire_knowledge_lock("j1", "worker-a")
        stale = (datetime.utcnow() - timedelta(seconds=1000)).isoformat()
        store.update_job("j1", knowledge_locked_at=stale)
        assert store.reap_stale_knowledge_locks(ttl_seconds=900) == 1
        assert store.get_knowledge_status("j1") == "pending"

    def test_reap_leaves_fresh_locks(self, store: JobStore):
        _job_with_transcript(store, "j1")
        store.enqueue_knowledge_job("j1")
        store.acquire_knowledge_lock("j1", "worker-a")
        assert store.reap_stale_knowledge_locks(ttl_seconds=900) == 0
        assert store.get_knowledge_status("j1") == "running"


class TestPendingQueue:
    def test_priority_ordering(self, store: JobStore):
        _job_with_transcript(store, "low", priority=1)
        _job_with_transcript(store, "high", priority=9)
        _job_with_transcript(store, "mid", priority=5)
        for jid in ("low", "high", "mid"):
            store.enqueue_knowledge_job(jid)
        ids = [j["job_id"] for j in store.list_pending_knowledge_jobs()]
        assert ids[0] == "high"
        assert ids[-1] == "low"

    def test_list_excludes_jobs_without_transcript(self, store: JobStore):
        store.create_job("no_transcript", JobType.TRANSCRIBE)
        store.set_knowledge_status("no_transcript", "pending")
        assert store.list_pending_knowledge_jobs() == []

    def test_list_respects_limit(self, store: JobStore):
        for i in range(5):
            _job_with_transcript(store, f"j{i}")
            store.enqueue_knowledge_job(f"j{i}")
        assert len(store.list_pending_knowledge_jobs(limit=3)) == 3

    def test_count_pending(self, store: JobStore):
        for i in range(3):
            _job_with_transcript(store, f"j{i}")
            store.enqueue_knowledge_job(f"j{i}")
        assert store.count_pending_knowledge_jobs() == 3


class TestStatusCounts:
    def test_counts_fold_legacy_aliases(self, store: JobStore):
        _job_with_transcript(store, "a")
        _job_with_transcript(store, "b")
        _job_with_transcript(store, "c")
        store.set_knowledge_status("a", "extracting")  # legacy → running
        store.set_knowledge_status("b", "complete")  # legacy → ready
        store.set_knowledge_status("c", "pending")
        counts = store.get_knowledge_status_counts()
        assert counts["running"] == 1
        assert counts["ready"] == 1
        assert counts["pending"] == 1
