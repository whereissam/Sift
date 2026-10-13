"""One job's cleanup must not delete another job's file.

Regression tests: jobs for the same video share one output name
(`%(title)s [%(id)s].ext`). A scheduled mp3 job downloaded the same m4a a
batch job had finished with, converted it, then deleted that "raw" m4a —
the batch job's result.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import job_management_routes
from app.pipeline import workflow
from app.store import JobStatus, JobType
from app.store._store import JobStore


@pytest.fixture
def store(tmp_path):
    return JobStore(db_path=tmp_path / "jobs.db")


@pytest.fixture
def shared(tmp_path):
    path = tmp_path / "Song [abc123def45].m4a"
    path.write_bytes(b"m4a")
    return path


def _finished_download(store, job_id, path):
    store.create_job(job_id, JobType.DOWNLOAD, source_url="https://youtu.be/abc123def45")
    store.update_job(job_id, raw_file_path=str(path), converted_file_path=str(path))
    store.set_status(job_id, JobStatus.COMPLETED)


class TestFileUsedByOtherJob:
    def test_detects_another_job(self, store, shared):
        _finished_download(store, "a", shared)
        assert store.file_used_by_other_job(shared, "b")
        assert not store.file_used_by_other_job(shared, "a")

    def test_unreferenced_file(self, store, tmp_path):
        assert not store.file_used_by_other_job(tmp_path / "x.m4a", "a")


class TestConvertCleanup:
    @pytest.fixture(autouse=True)
    def _fake_converter(self, monkeypatch):
        class FakeConverter:
            async def convert(self, input_path, output_format, quality):
                out = Path(input_path).with_suffix(f".{output_format}")
                out.write_bytes(b"converted")
                return out

        monkeypatch.setattr(workflow, "AudioConverter", FakeConverter)

    async def _convert(self, store, job_id, raw):
        store.create_job(job_id, JobType.DOWNLOAD, source_url="https://youtu.be/abc123def45")
        store.update_job(job_id, raw_file_path=str(raw), status=JobStatus.CONVERTING.value)
        await workflow.WorkflowProcessor(store)._phase_convert(job_id, "mp3", "high")

    async def test_shared_raw_file_is_kept(self, store, shared):
        _finished_download(store, "batch", shared)
        await self._convert(store, "scheduled", shared)
        assert shared.exists(), "the batch job's m4a was deleted"
        assert shared.with_suffix(".mp3").exists()

    async def test_own_raw_file_is_still_cleaned_up(self, store, shared):
        await self._convert(store, "only", shared)
        assert not shared.exists()
        assert shared.with_suffix(".mp3").exists()


class TestDeleteJobRoute:
    @pytest.fixture
    def client(self, store, monkeypatch):
        monkeypatch.setattr("app.store.get_job_store", lambda: store)
        app = FastAPI()
        app.include_router(job_management_routes.router, prefix="/api")
        return TestClient(app)

    def test_shared_file_survives_deleting_one_job(self, client, store, shared):
        _finished_download(store, "a", shared)
        _finished_download(store, "b", shared)
        assert client.delete("/api/jobs/a").status_code == 200
        assert shared.exists()
        assert client.delete("/api/jobs/b").status_code == 200
        assert not shared.exists()
