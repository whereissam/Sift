"""Tests for the jobs mixin on JobStore.

Each test gets a fresh on-disk SQLite DB so we exercise the same path
the real app does (no mocks).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.job_store import JobStatus, JobStore, JobType


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "jobs.db")


class TestCreateAndGet:
    def test_create_returns_full_row(self, store: JobStore):
        job = store.create_job("j1", JobType.DOWNLOAD, source_url="https://x")
        assert job["job_id"] == "j1"
        assert job["job_type"] == JobType.DOWNLOAD.value
        assert job["status"] == JobStatus.PENDING.value
        assert job["source_url"] == "https://x"
        assert job["priority"] == 5  # default
        assert job["created_at"] == job["updated_at"]

    def test_get_unknown_returns_none(self, store: JobStore):
        assert store.get_job("nope") is None

    def test_create_accepts_optional_fields(self, store: JobStore):
        job = store.create_job(
            "j1",
            JobType.TRANSCRIBE,
            source_url="https://x",
            platform="youtube",
            model_size="base",
            language="en",
            priority=9,
            batch_id="b1",
            webhook_url="https://hook",
        )
        assert job["platform"] == "youtube"
        assert job["priority"] == 9
        assert job["batch_id"] == "b1"
        assert job["webhook_url"] == "https://hook"


class TestUpdateJob:
    def test_updates_advance_updated_at(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        before = store.get_job("j1")["updated_at"]
        # Sleep so ISO timestamps differ
        time.sleep(0.01)
        store.update_job("j1", progress=0.5)
        after = store.get_job("j1")["updated_at"]
        assert after > before

    def test_invalid_column_raises(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        # `; DROP TABLE jobs` shouldn't be SQL-injectable — the allowlist
        # rejects it before reaching SQLite.
        with pytest.raises(ValueError, match="Invalid column names"):
            store.update_job("j1", malicious_col="x")

    def test_json_fields_serialized(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.update_job("j1", content_info={"title": "hi", "n": 1})
        job = store.get_job("j1")
        # Round-trip: dict in, dict out
        assert job["content_info"] == {"title": "hi", "n": 1}

    def test_json_field_already_string_passes_through(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.update_job("j1", content_info='{"already": "json"}')
        job = store.get_job("j1")
        assert job["content_info"] == {"already": "json"}


class TestSetStatus:
    def test_completed_sets_completed_at_and_progress(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.set_status("j1", JobStatus.COMPLETED)
        job = store.get_job("j1")
        assert job["status"] == JobStatus.COMPLETED.value
        assert job["completed_at"] is not None
        assert job["progress"] == 1.0

    def test_failed_records_error(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.set_status("j1", JobStatus.FAILED, error="boom")
        job = store.get_job("j1")
        assert job["status"] == JobStatus.FAILED.value
        assert job["error"] == "boom"

    def test_in_progress_status_no_completed_at(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.set_status("j1", JobStatus.DOWNLOADING, progress=0.3)
        job = store.get_job("j1")
        assert job["status"] == JobStatus.DOWNLOADING.value
        assert job["completed_at"] is None
        assert job["progress"] == 0.3


class TestGetByStatus:
    def test_filters_and_ordered_newest_first(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        time.sleep(0.01)
        store.create_job("j2", JobType.DOWNLOAD)
        time.sleep(0.01)
        store.create_job("j3", JobType.DOWNLOAD)
        store.set_status("j2", JobStatus.COMPLETED)

        pending = store.get_jobs_by_status(JobStatus.PENDING)
        assert [j["job_id"] for j in pending] == ["j3", "j1"]

    def test_multi_status(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.create_job("j2", JobType.DOWNLOAD)
        store.set_status("j2", JobStatus.FAILED)
        rows = store.get_jobs_by_status(JobStatus.PENDING, JobStatus.FAILED)
        assert {j["job_id"] for j in rows} == {"j1", "j2"}


class TestUnfinishedAndResumable:
    def test_unfinished_excludes_completed_and_failed(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.create_job("j2", JobType.DOWNLOAD)
        store.create_job("j3", JobType.DOWNLOAD)
        store.set_status("j2", JobStatus.COMPLETED)
        store.set_status("j3", JobStatus.FAILED)
        unfinished = store.get_unfinished_jobs()
        assert [j["job_id"] for j in unfinished] == ["j1"]

    def test_resumable_filters_by_job_type(self, store: JobStore):
        store.create_job("d1", JobType.DOWNLOAD)
        store.create_job("t1", JobType.TRANSCRIBE)
        store.set_status("d1", JobStatus.FAILED)
        store.set_status("t1", JobStatus.FAILED)
        only_t = store.get_resumable_jobs(job_type=JobType.TRANSCRIBE)
        assert [j["job_id"] for j in only_t] == ["t1"]


class TestDeleteAndCleanup:
    def test_delete_returns_true_when_deleted(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        assert store.delete_job("j1") is True
        assert store.get_job("j1") is None

    def test_delete_unknown_returns_false(self, store: JobStore):
        assert store.delete_job("nope") is False

    def test_cleanup_only_old_terminal_jobs(self, store: JobStore):
        # ``update_job`` always rewrites ``updated_at`` to now, so we
        # back-date rows directly via SQL to simulate aged data.
        old_time = (datetime.utcnow() - timedelta(days=30)).isoformat()

        # j_old completed long ago — should be cleaned up
        store.create_job("j_old", JobType.DOWNLOAD)
        store.set_status("j_old", JobStatus.COMPLETED)
        # j_new completed today — survives
        store.create_job("j_new", JobType.DOWNLOAD)
        store.set_status("j_new", JobStatus.COMPLETED)
        # j_pending — old but PENDING, must survive
        store.create_job("j_pending", JobType.DOWNLOAD)

        with store._get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id IN (?, ?)",
                (old_time, "j_old", "j_pending"),
            )

        deleted = store.cleanup_old_jobs(days=7)
        assert deleted == 1
        assert store.get_job("j_old") is None
        assert store.get_job("j_new") is not None
        assert store.get_job("j_pending") is not None


class TestPriorityQueue:
    def test_ordered_by_priority_then_created_at(self, store: JobStore):
        store.create_job("low", JobType.DOWNLOAD, priority=2)
        time.sleep(0.01)
        store.create_job("high1", JobType.DOWNLOAD, priority=9)
        time.sleep(0.01)
        store.create_job("high2", JobType.DOWNLOAD, priority=9)

        ordered = store.get_jobs_by_priority()
        # high priority first; within same priority, oldest first
        assert [j["job_id"] for j in ordered] == ["high1", "high2", "low"]

    def test_update_priority_clamps_to_1_to_10(self, store: JobStore):
        store.create_job("j1", JobType.DOWNLOAD)
        store.update_priority("j1", 999)
        assert store.get_job("j1")["priority"] == 10
        store.update_priority("j1", -5)
        assert store.get_job("j1")["priority"] == 1

    def test_skips_jobs_scheduled_in_future(self, store: JobStore):
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        store.create_job("now", JobType.DOWNLOAD)
        store.create_job("later", JobType.DOWNLOAD, scheduled_at=future)
        ordered = store.get_jobs_by_priority()
        assert [j["job_id"] for j in ordered] == ["now"]


class TestScheduledJobs:
    def test_returns_due_pending_jobs_only(self, store: JobStore):
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        store.create_job("due", JobType.DOWNLOAD, scheduled_at=past)
        store.create_job("not_yet", JobType.DOWNLOAD, scheduled_at=future)
        store.create_job("unscheduled", JobType.DOWNLOAD)
        due = store.get_scheduled_jobs()
        assert [j["job_id"] for j in due] == ["due"]

    def test_skips_non_pending(self, store: JobStore):
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        store.create_job("j1", JobType.DOWNLOAD, scheduled_at=past)
        store.set_status("j1", JobStatus.DOWNLOADING)
        assert store.get_scheduled_jobs() == []

    def test_clear_scheduled_at(self, store: JobStore):
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        store.create_job("j1", JobType.DOWNLOAD, scheduled_at=past)
        store.clear_scheduled_at("j1")
        assert store.get_job("j1")["scheduled_at"] is None


class TestBackupAndRestore:
    def test_round_trip_preserves_jobs(self, store: JobStore, tmp_path: Path):
        store.create_job("j1", JobType.DOWNLOAD, source_url="https://x")
        store.set_status("j1", JobStatus.COMPLETED)
        backup_dir = tmp_path / "bk"

        backup_path = store.backup(backup_dir=backup_dir)
        assert backup_path.exists()

        # Wipe the job and restore — should come back
        store.delete_job("j1")
        assert store.get_job("j1") is None

        store.restore(backup_path)
        # Need a new JobStore instance because the connection cache may
        # be stale after the file is swapped under it.
        store2 = JobStore(db_path=store.db_path)
        restored = store2.get_job("j1")
        assert restored is not None
        assert restored["status"] == JobStatus.COMPLETED.value

    def test_list_backups_newest_first(self, store: JobStore, tmp_path: Path):
        backup_dir = tmp_path / "bk"
        p1 = store.backup(backup_dir=backup_dir)
        time.sleep(1.1)  # mtime resolution is whole-second on some FS
        p2 = store.backup(backup_dir=backup_dir)
        listed = store.list_backups(backup_dir=backup_dir)
        assert [b["path"] for b in listed] == [str(p2), str(p1)]

    def test_restore_missing_file_raises(self, store: JobStore, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            store.restore(tmp_path / "does-not-exist.db")

    def test_list_backups_empty_when_dir_missing(self, store: JobStore, tmp_path: Path):
        assert store.list_backups(backup_dir=tmp_path / "nope") == []
