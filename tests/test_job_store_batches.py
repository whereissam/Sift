"""Tests for the batches mixin on JobStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.job_store import JobStatus, JobStore, JobType


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "jobs.db")


class TestCreateAndGet:
    def test_create_returns_row(self, store: JobStore):
        b = store.create_batch("b1", name="hello", total_jobs=3, webhook_url="https://hk")
        assert b["batch_id"] == "b1"
        assert b["name"] == "hello"
        assert b["total_jobs"] == 3
        assert b["webhook_url"] == "https://hk"
        assert b["status"] == "pending"
        assert b["completed_jobs"] == 0
        assert b["failed_jobs"] == 0

    def test_get_unknown_returns_none(self, store: JobStore):
        assert store.get_batch("nope") is None


class TestGetBatchJobs:
    def test_returns_only_jobs_in_batch_ordered_oldest_first(self, store: JobStore):
        import time

        store.create_batch("b1")
        store.create_job("j_outside", JobType.DOWNLOAD)
        store.create_job("j1", JobType.DOWNLOAD, batch_id="b1")
        time.sleep(0.01)
        store.create_job("j2", JobType.DOWNLOAD, batch_id="b1")
        rows = store.get_batch_jobs("b1")
        assert [j["job_id"] for j in rows] == ["j1", "j2"]


class TestUpdateBatchStats:
    def test_returns_none_when_batch_has_no_jobs(self, store: JobStore):
        store.create_batch("b1")
        assert store.update_batch_stats("b1") is None

    def test_status_in_progress(self, store: JobStore):
        store.create_batch("b1")
        store.create_job("j1", JobType.DOWNLOAD, batch_id="b1")
        store.create_job("j2", JobType.DOWNLOAD, batch_id="b1")
        store.set_status("j1", JobStatus.COMPLETED)
        b = store.update_batch_stats("b1")
        assert b["status"] == "in_progress"
        assert b["completed_jobs"] == 1
        assert b["failed_jobs"] == 0

    def test_status_completed_when_all_succeeded(self, store: JobStore):
        store.create_batch("b1")
        store.create_job("j1", JobType.DOWNLOAD, batch_id="b1")
        store.create_job("j2", JobType.DOWNLOAD, batch_id="b1")
        store.set_status("j1", JobStatus.COMPLETED)
        store.set_status("j2", JobStatus.COMPLETED)
        b = store.update_batch_stats("b1")
        assert b["status"] == "completed"
        assert b["completed_jobs"] == 2
        assert b["failed_jobs"] == 0

    def test_status_completed_with_errors_when_any_failed(self, store: JobStore):
        store.create_batch("b1")
        store.create_job("j1", JobType.DOWNLOAD, batch_id="b1")
        store.create_job("j2", JobType.DOWNLOAD, batch_id="b1")
        store.set_status("j1", JobStatus.COMPLETED)
        store.set_status("j2", JobStatus.FAILED)
        b = store.update_batch_stats("b1")
        assert b["status"] == "completed_with_errors"
        assert b["completed_jobs"] == 1
        assert b["failed_jobs"] == 1


class TestDelete:
    def test_delete_returns_true(self, store: JobStore):
        store.create_batch("b1")
        assert store.delete_batch("b1") is True
        assert store.get_batch("b1") is None

    def test_delete_does_not_remove_associated_jobs(self, store: JobStore):
        # Per docstring: "does not delete associated jobs". This is a
        # behavior contract — flag it if it changes.
        store.create_batch("b1")
        store.create_job("j1", JobType.DOWNLOAD, batch_id="b1")
        store.delete_batch("b1")
        assert store.get_job("j1") is not None


class TestGetAllBatches:
    def test_filters_by_status_and_limit(self, store: JobStore):
        store.create_batch("b1")
        store.create_batch("b2")
        store.create_batch("b3")
        # b2 finished
        store.create_job("j", JobType.DOWNLOAD, batch_id="b2")
        store.set_status("j", JobStatus.COMPLETED)
        store.update_batch_stats("b2")

        all_batches = store.get_all_batches()
        assert {b["batch_id"] for b in all_batches} == {"b1", "b2", "b3"}

        only_completed = store.get_all_batches(status="completed")
        assert [b["batch_id"] for b in only_completed] == ["b2"]
