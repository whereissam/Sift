"""Slice 3 tests: /v1 ingestion API — submission, idempotency, caching,
stage-based progress, asset endpoints, and the ingestion runner."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.store as job_store_pkg
from app.store import JobStatus as StoreStatus, JobType
from sift_core.transcribe.transcriber import TranscriptionSegment as CoreSegment


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = job_store_pkg.JobStore(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(job_store_pkg, "_job_store", s)
    return s


@pytest.fixture
def client(store, monkeypatch):
    from app.api import auth as auth_module
    from app.api import ingestion_routes
    from app.api.ratelimit import limiter
    from sift_core.base import Platform as CorePlatform
    from sift_core.fetch.downloader import DownloaderFactory

    class _NoAuth:
        api_key = None

    monkeypatch.setattr(auth_module, "get_settings", lambda: _NoAuth())
    monkeypatch.setattr(
        DownloaderFactory,
        "detect_platform",
        staticmethod(lambda url: CorePlatform.YOUTUBE),
    )

    # Don't execute the real pipeline from endpoint tests.
    launched = []

    async def fake_runner(job_id):
        launched.append(job_id)

    monkeypatch.setattr(ingestion_routes, "run_ingestion_job", fake_runner)

    api = FastAPI()
    api.state.limiter = limiter
    api.include_router(ingestion_routes.router)
    test_client = TestClient(api)
    test_client.launched = launched
    # Shared limiter: don't inherit or leak rate-limit state across tests.
    limiter.reset()
    yield test_client
    limiter.reset()


BODY = {
    "source": {"type": "url", "url": "https://youtu.be/dQw4w9WgXcQ"},
    "outputs": ["transcript", "speakers"],
    "processing": {"language": "en", "diarization": True, "model": "base"},
}


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def test_submit_returns_202_with_asset(client, store):
    resp = client.post("/v1/ingestions", json=BODY)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["cached"] is False
    assert body["asset_id"] is not None

    job = store.get_job(body["job_id"])
    assert job["job_type"] == "transcribe"
    assert job["requested_outputs"] == ["transcript", "speakers"]
    assert job["model_size"] == "base"
    assert client.launched == [body["job_id"]]


def test_submit_media_only_creates_download_job(client, store):
    resp = client.post(
        "/v1/ingestions",
        json={"source": {"url": "https://youtu.be/dQw4w9WgXcQ"}, "outputs": ["media"]},
    )
    assert resp.status_code == 202
    job = store.get_job(resp.json()["job_id"])
    assert job["job_type"] == "download"
    assert job["output_format"] == "m4a"


def test_submit_rejects_bad_urls(client, monkeypatch):
    resp = client.post(
        "/v1/ingestions", json={**BODY, "source": {"url": "ftp://example.com/x"}}
    )
    assert resp.status_code == 400

    from sift_core.fetch.downloader import DownloaderFactory

    monkeypatch.setattr(
        DownloaderFactory, "detect_platform", staticmethod(lambda url: None)
    )
    resp = client.post("/v1/ingestions", json=BODY)
    assert resp.status_code == 400


def test_submit_rejects_unknown_output(client):
    resp = client.post(
        "/v1/ingestions",
        json={**BODY, "outputs": ["transcript", "frames"]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_replay_returns_original_job(client):
    headers = {"Idempotency-Key": "key-1"}
    first = client.post("/v1/ingestions", json=BODY, headers=headers)
    assert first.status_code == 202
    second = client.post("/v1/ingestions", json=BODY, headers=headers)
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["cached"] is True
    # The pipeline only launched once.
    assert len(client.launched) == 1


def test_idempotency_key_conflict_on_different_body(client):
    headers = {"Idempotency-Key": "key-2"}
    assert client.post("/v1/ingestions", json=BODY, headers=headers).status_code == 202
    different = {**BODY, "outputs": ["transcript"]}
    resp = client.post("/v1/ingestions", json=different, headers=headers)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Cache hits
# ---------------------------------------------------------------------------

def _seed_cached_transcript(store, diarized=True):
    job = store.create_job(
        "seed", JobType.TRANSCRIBE, source_url="https://youtu.be/dQw4w9WgXcQ"
    )
    store.create_transcript_artifact(
        asset_id=job["asset_id"],
        job_id="seed",
        segments=[CoreSegment(start=0.0, end=1.0, text="hi", speaker="SPEAKER_00")],
        pipeline_version="whisper:base/diar=1",
        diarization_enabled=diarized,
    )
    return job["asset_id"]


def test_cached_source_completes_immediately(client, store):
    asset_id = _seed_cached_transcript(store)
    resp = client.post("/v1/ingestions", json=BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert body["status"] == "completed"
    assert body["asset_id"] == asset_id
    assert client.launched == []  # nothing ran


def test_speakers_request_ignores_undiarized_cache(client, store):
    _seed_cached_transcript(store, diarized=False)
    resp = client.post("/v1/ingestions", json=BODY)
    assert resp.status_code == 202  # must re-run with diarization


# ---------------------------------------------------------------------------
# Status / progress
# ---------------------------------------------------------------------------

def test_get_ingestion_stage_and_media_seconds(client, store):
    job_id = client.post("/v1/ingestions", json=BODY).json()["job_id"]

    resp = client.get(f"/v1/ingestions/{job_id}").json()
    assert resp["status"] == "queued"
    assert resp["progress"]["unit"] == "fraction"

    store.update_job(job_id, content_info={"duration_seconds": 600})
    store.set_status(job_id, StoreStatus.TRANSCRIBING, progress=0.5)

    resp = client.get(f"/v1/ingestions/{job_id}").json()
    assert resp["stage"] == "transcribing"
    assert resp["progress"] == {
        "completed": 300,
        "total": 600,
        "unit": "media_seconds",
    }

    store.set_status(job_id, StoreStatus.COMPLETED)
    store.update_job(job_id, knowledge_status="running")
    resp = client.get(f"/v1/ingestions/{job_id}").json()
    assert resp["status"] == "completed"
    assert resp["stage"] == "extracting"

    assert client.get("/v1/ingestions/nope").status_code == 404


# ---------------------------------------------------------------------------
# Asset endpoints
# ---------------------------------------------------------------------------

def test_asset_endpoints(client, store):
    asset_id = _seed_cached_transcript(store)

    resp = client.get(f"/v1/assets/{asset_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_source"] == "youtube:video:dQw4w9WgXcQ"
    assert body["latest_transcript_artifact"]["segment_count"] == 1
    assert body["job_count"] == 1

    resp = client.get(f"/v1/assets/{asset_id}/artifacts")
    assert resp.status_code == 200
    assert len(resp.json()["artifacts"]) == 1

    assert client.get("/v1/assets/nope").status_code == 404
    assert client.get("/v1/assets/nope/artifacts").status_code == 404


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def test_runner_transcript_path(store, tmp_path, monkeypatch):
    from app.pipeline import ingestion_service
    from sift_core.fetch.downloader import DownloaderFactory

    job = store.create_job(
        "run-1",
        JobType.TRANSCRIBE,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        model_size="small",
        language="zh",
        transcription_format="json",
        requested_outputs=["transcript", "speakers"],
    )
    assert job["asset_id"] is not None

    media = tmp_path / "raw.m4a"
    media.write_bytes(b"fake")

    class FakeResult:
        success = True
        file_path = media
        metadata = None
        error = None

    class FakeDownloader:
        async def download(self, url, output_format, quality):
            return FakeResult()

    monkeypatch.setattr(
        DownloaderFactory, "get_downloader", staticmethod(lambda url: FakeDownloader())
    )

    calls = {}

    class FakeProcessor:
        def __init__(self, job_store=None):
            self.job_store = job_store

        async def process_transcription(self, job_id, audio_path, **kwargs):
            calls["job_id"] = job_id
            calls["audio_path"] = audio_path
            calls.update(kwargs)
            self.job_store.set_status(job_id, StoreStatus.COMPLETED)

    monkeypatch.setattr(ingestion_service, "WorkflowProcessor", FakeProcessor)

    asyncio.run(ingestion_service.run_ingestion_job("run-1"))

    assert calls["job_id"] == "run-1"
    assert calls["audio_path"] == media
    assert calls["model_size"] == "small"
    assert calls["language"] == "zh"
    assert calls["diarize"] is True
    assert store.get_job("run-1")["raw_file_path"] == str(media)
    assert store.get_job("run-1")["status"] == "completed"


def test_runner_media_only_path(store, monkeypatch):
    from app.pipeline import ingestion_service

    store.create_job(
        "run-2",
        JobType.DOWNLOAD,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        output_format="mp3",
        quality="high",
        requested_outputs=["media"],
    )

    calls = {}

    class FakeProcessor:
        def __init__(self, job_store=None):
            self.job_store = job_store

        async def process_download(self, job_id, url, platform, output_format, quality):
            calls.update(
                job_id=job_id, url=url, output_format=output_format, quality=quality
            )
            self.job_store.set_status(job_id, StoreStatus.COMPLETED)

    monkeypatch.setattr(ingestion_service, "WorkflowProcessor", FakeProcessor)

    asyncio.run(ingestion_service.run_ingestion_job("run-2"))
    assert calls["job_id"] == "run-2"
    assert calls["output_format"] == "mp3"


def test_runner_download_failure_marks_failed(store, monkeypatch):
    from app.pipeline import ingestion_service
    from sift_core.fetch.downloader import DownloaderFactory

    store.create_job(
        "run-3",
        JobType.TRANSCRIBE,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        requested_outputs=["transcript"],
    )

    class FakeDownloader:
        async def download(self, url, output_format, quality):
            class R:
                success = False
                file_path = None
                metadata = None
                error = "blocked by upstream"

            return R()

    monkeypatch.setattr(
        DownloaderFactory, "get_downloader", staticmethod(lambda url: FakeDownloader())
    )

    asyncio.run(ingestion_service.run_ingestion_job("run-3"))
    job = store.get_job("run-3")
    assert job["status"] == "failed"
    assert "blocked by upstream" in job["error"]
