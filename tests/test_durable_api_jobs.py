"""Slice 0 regression tests: API jobs survive process restarts.

The legacy in-memory dicts (download_routes.jobs, transcription_jobs) are
now SQLite-backed mappings. "Restart" is simulated by replacing the job
store singleton with a fresh instance over the same database file.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.store as job_store_pkg
from app.api.durable_jobs import DurableDownloadJobs, DurableTranscriptionJobs
from app.api.schemas import (
    ContentInfo,
    DownloadJob,
    JobStatus,
    Platform,
    TranscriptionJob,
    TranscriptionSegment,
)
from app.store import JobStatus as StoreStatus, JobType


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.db"


@pytest.fixture
def store(db_path, monkeypatch):
    """Fresh JobStore over a temp db, installed as the singleton."""
    s = job_store_pkg.JobStore(db_path=db_path)
    monkeypatch.setattr(job_store_pkg, "_job_store", s)
    return s


def _restart(db_path, monkeypatch):
    """Simulate a process restart: new store instance, same database."""
    fresh = job_store_pkg.JobStore(db_path=db_path)
    monkeypatch.setattr(job_store_pkg, "_job_store", fresh)
    return fresh


def _download_job(job_id="dl-1", **overrides):
    defaults = dict(
        job_id=job_id,
        status=JobStatus.PENDING,
        platform=Platform.YOUTUBE,
        progress=0.0,
        created_at=datetime(2026, 7, 11, 10, 0, 0),
    )
    defaults.update(overrides)
    return DownloadJob(**defaults)


# ---------------------------------------------------------------------------
# Durability across restart
# ---------------------------------------------------------------------------

def test_download_job_survives_restart(store, db_path, monkeypatch):
    jobs = DurableDownloadJobs()
    job = _download_job()
    job._persist_extras = {"source_url": "https://youtube.com/watch?v=abc"}
    jobs["dl-1"] = job

    _restart(db_path, monkeypatch)

    assert "dl-1" in jobs
    loaded = jobs["dl-1"]
    assert loaded.job_id == "dl-1"
    assert loaded.status == JobStatus.PENDING
    assert loaded.platform == Platform.YOUTUBE
    assert loaded.created_at == datetime(2026, 7, 11, 10, 0, 0)


def test_completed_download_roundtrip(store, db_path, monkeypatch, tmp_path):
    media = tmp_path / "audio.m4a"
    media.write_bytes(b"fake audio")

    jobs = DurableDownloadJobs()
    info = ContentInfo(platform=Platform.YOUTUBE, content_id="abc", title="T")
    job = _download_job(
        status=JobStatus.COMPLETED,
        progress=1.0,
        content_info=info,
        file_path=str(media),
        file_size_mb=0.01,
        completed_at=datetime(2026, 7, 11, 10, 5, 0),
    )
    jobs["dl-1"] = job

    _restart(db_path, monkeypatch)

    loaded = jobs["dl-1"]
    assert loaded.status == JobStatus.COMPLETED
    assert loaded.download_url == "/api/download/dl-1/file"
    assert loaded.file_path == str(media)
    # Legacy contract used by the file endpoint
    assert getattr(loaded, "_file_path", None) == str(media)
    assert loaded.content_info.content_id == "abc"
    assert loaded.space_info.content_id == "abc"  # compat alias
    assert loaded.completed_at == datetime(2026, 7, 11, 10, 5, 0)


def test_transcription_job_survives_restart_lossless(store, db_path, monkeypatch):
    jobs = DurableTranscriptionJobs()
    job = TranscriptionJob(
        job_id="tr-1",
        status=JobStatus.COMPLETED,
        progress=1.0,
        text="hello world",
        segments=[
            TranscriptionSegment(start=0.0, end=1.5, text="hello", speaker="SPEAKER_00"),
            TranscriptionSegment(start=1.5, end=3.0, text="world", speaker="SPEAKER_01"),
        ],
        language="en",
        language_probability=0.99,
        duration_seconds=3.0,
        formatted_output="hello world",
        source_url="https://youtube.com/watch?v=abc",
        created_at=datetime(2026, 7, 11, 9, 0, 0),
        completed_at=datetime(2026, 7, 11, 9, 10, 0),
    )
    jobs["tr-1"] = job

    _restart(db_path, monkeypatch)

    loaded = jobs["tr-1"]
    # Saving resolves the URL to an asset (Slice 1), so the loaded copy
    # carries the asset link the in-memory original didn't have yet.
    assert loaded.asset_id is not None
    assert loaded.model_dump(exclude={"asset_id"}) == job.model_dump(
        exclude={"asset_id"}
    )


# ---------------------------------------------------------------------------
# Status mapping and type isolation
# ---------------------------------------------------------------------------

def test_store_stage_statuses_map_to_processing(store):
    jobs = DurableTranscriptionJobs()
    jobs["tr-1"] = TranscriptionJob(
        job_id="tr-1", status=JobStatus.PENDING, created_at=datetime.utcnow()
    )
    store.set_status("tr-1", StoreStatus.TRANSCRIBING, progress=0.4)

    assert jobs["tr-1"].status == JobStatus.PROCESSING
    assert jobs["tr-1"].progress == 0.4


def test_processing_persists_as_stage_status(store):
    jobs = DurableDownloadJobs()
    job = _download_job(status=JobStatus.PROCESSING, progress=0.5)
    jobs["dl-1"] = job

    row = store.get_job("dl-1")
    assert row["status"] == StoreStatus.DOWNLOADING.value


def test_job_type_isolation(store):
    downloads = DurableDownloadJobs()
    transcriptions = DurableTranscriptionJobs()
    downloads["dl-1"] = _download_job()

    assert "dl-1" in downloads
    assert "dl-1" not in transcriptions
    assert transcriptions.get("dl-1") is None
    with pytest.raises(KeyError):
        transcriptions["dl-1"]


def test_delete_removes_row(store):
    jobs = DurableDownloadJobs()
    jobs["dl-1"] = _download_job()
    del jobs["dl-1"]
    assert "dl-1" not in jobs
    assert store.get_job("dl-1") is None
    with pytest.raises(KeyError):
        del jobs["dl-1"]


def test_items_lists_only_own_type(store):
    downloads = DurableDownloadJobs()
    transcriptions = DurableTranscriptionJobs()
    downloads["dl-1"] = _download_job()
    transcriptions["tr-1"] = TranscriptionJob(
        job_id="tr-1", status=JobStatus.PENDING, created_at=datetime.utcnow()
    )

    assert [jid for jid, _ in transcriptions.items()] == ["tr-1"]
    assert set(downloads.keys()) == {"dl-1"}
    assert len(transcriptions) == 1


# ---------------------------------------------------------------------------
# Legacy row compatibility (WorkflowProcessor blob format)
# ---------------------------------------------------------------------------

def test_workflow_format_blob_falls_back_to_columns(store):
    store.create_job("wf-1", JobType.TRANSCRIBE, source_url="https://ex.com/a")
    store.update_job(
        "wf-1",
        transcription_result={
            "text": "workflow text",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "workflow text", "speaker": None}
            ],
            "formatted_output": "workflow text",
            "output_format": "text",
        },
    )
    store.set_status("wf-1", StoreStatus.COMPLETED)

    jobs = DurableTranscriptionJobs()
    loaded = jobs["wf-1"]
    assert loaded.status == JobStatus.COMPLETED
    assert loaded.text == "workflow text"
    assert loaded.segments[0].end == 2.0
    assert loaded.source_url == "https://ex.com/a"


# ---------------------------------------------------------------------------
# Endpoint-level: POST /api/download survives a restart
# ---------------------------------------------------------------------------

def test_download_endpoint_job_survives_restart(store, db_path, monkeypatch, tmp_path):
    from app.api import auth as auth_module
    from app.api import download_routes
    from app.api.ratelimit import limiter
    from sift_core.base import Platform as CorePlatform

    class _NoAuth:
        api_key = None

    monkeypatch.setattr(auth_module, "get_settings", lambda: _NoAuth())

    media = tmp_path / "out.m4a"
    media.write_bytes(b"fake audio bytes")

    class FakeResult:
        success = True
        file_path = media
        metadata = None
        error = None

    class FakeDownloader:
        async def download(self, url, output_format, quality):
            return FakeResult()

    monkeypatch.setattr(
        download_routes.DownloaderFactory,
        "detect_platform",
        staticmethod(lambda url: CorePlatform.YOUTUBE),
    )
    monkeypatch.setattr(
        download_routes.DownloaderFactory,
        "get_downloader",
        staticmethod(lambda url: FakeDownloader()),
    )

    api = FastAPI()
    api.state.limiter = limiter
    api.include_router(download_routes.router, prefix="/api")
    client = TestClient(api)

    resp = client.post(
        "/api/download",
        json={"url": "https://youtube.com/watch?v=abc"},
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # TestClient runs background tasks before returning: job is done.
    _restart(db_path, monkeypatch)

    resp = client.get(f"/api/download/{job_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["file_path"] == str(media)

    # File endpoint works from the durable record too.
    resp = client.get(f"/api/download/{job_id}/file")
    assert resp.status_code == 200
    assert resp.content == b"fake audio bytes"


# ---------------------------------------------------------------------------
# Route prefix fix: /api/models, not /api/api/models
# ---------------------------------------------------------------------------

def test_model_routes_mount_under_single_api_prefix():
    from app.api import model_routes

    api = FastAPI()
    api.include_router(model_routes.router, prefix="/api")

    # Assert against the OpenAPI schema rather than walking `app.routes`:
    # Starlette 1.x keeps an included router as one opaque entry there, so a
    # flat scan both misses the paths and trips over entries with no `.path`.
    paths = set(api.openapi()["paths"])

    assert "/api/models/whisper" in paths
    assert not any(p.startswith("/api/api/") for p in paths)
