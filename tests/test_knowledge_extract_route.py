"""Tests for the synchronous POST /jobs/{id}/extract-knowledge route.

This is the manual (re-)extract path. It reads segments from the in-memory
transcription store, runs the configured extractor, and persists through the
shared ``persist_extraction_result`` helper — the same transaction the backfill
worker uses. Covers the success, total-failure, and all guard branches.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import transcription_store
from app.api.knowledge_routes import router as knowledge_router
from app.api.schemas import JobStatus, TranscriptionJob, TranscriptionSegment
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType
from app.core.knowledge_budget import get_budget_tracker
from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    ExtractionRunResult,
    compute_claim_id,
)


@pytest.fixture(autouse=True)
def _reset_state():
    get_budget_tracker().reset()
    transcription_store.transcription_jobs.clear()
    yield
    get_budget_tracker().reset()
    transcription_store.transcription_jobs.clear()


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    s = JobStore(db_path=tmp_path / "extract.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    return s


@pytest.fixture
def client(store: JobStore) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_router)
    return TestClient(app)


def _completed_transcription(store: JobStore, job_id: str, *, segments: bool = True) -> None:
    # The route reads segments from the in-memory transcription store but writes
    # knowledge_status onto the persisted jobs row, so both must exist.
    store.create_job(job_id, JobType.TRANSCRIBE)
    segs = (
        [TranscriptionSegment(start=0.0, end=1.0, text="hello world", speaker=None)]
        if segments
        else None
    )
    transcription_store.transcription_jobs[job_id] = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.COMPLETED,
        segments=segs,
        source_url="https://example.com/ep",
        created_at=datetime.utcnow(),
    )


def _claim(job_id: str) -> Claim:
    return Claim(
        claim_id=compute_claim_id(
            text="x", episode_id=job_id, speaker=None, timestamp_start=0.0
        ),
        episode_id=job_id,
        text="x",
        timestamp_start=0.0,
        timestamp_end=1.0,
        claim_type=ClaimType.FACT,
        confidence=0.9,
        evidence_excerpt="x",
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )


class _FakeExtractor:
    """Stands in for KnowledgeExtractor.from_settings()."""

    def __init__(self, *, success: bool = True, claims=None):
        self.provider = "openai"
        self._success = success
        self._claims = claims or []

    async def extract_claims(self, *, episode_id, segments, source_url=None):
        return ExtractionRunResult(
            job_id=episode_id,
            success=self._success,
            claims=self._claims,
            chunks_processed=1,
            chunks_failed=0 if self._success else 1,
            tokens_used=100,
            model="gpt-4o-mini",
            provider="openai",
            error=None if self._success else "all chunks failed",
        )


def _patch_extractor(monkeypatch, extractor):
    monkeypatch.setattr(
        "app.api.knowledge_routes.KnowledgeExtractor.from_settings",
        classmethod(lambda cls, **kw: extractor),
    )


class TestExtractRoute:
    def test_happy_path_persists_claims(self, client, store, monkeypatch):
        _completed_transcription(store, "j1")
        _patch_extractor(monkeypatch, _FakeExtractor(claims=[_claim("j1")]))

        r = client.post("/jobs/j1/extract-knowledge")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["claim_count"] == 1
        # Persisted + status flipped to the legacy 'complete' (== ready) alias.
        assert store.get_knowledge_status("j1") == "complete"
        assert len(store.get_claims_for_job("j1")) == 1
        # Spend recorded against the shared daily budget.
        assert get_budget_tracker().spent_today() > 0

    def test_unknown_job_404(self, client):
        r = client.post("/jobs/ghost/extract-knowledge")
        assert r.status_code == 404

    def test_not_completed_400(self, client, store):
        store.create_job("j1", JobType.TRANSCRIBE)
        transcription_store.transcription_jobs["j1"] = TranscriptionJob(
            job_id="j1", status=JobStatus.PROCESSING, created_at=datetime.utcnow()
        )
        r = client.post("/jobs/j1/extract-knowledge")
        assert r.status_code == 400

    def test_no_segments_400(self, client, store):
        _completed_transcription(store, "j1", segments=False)
        r = client.post("/jobs/j1/extract-knowledge")
        assert r.status_code == 400

    def test_no_provider_503(self, client, store, monkeypatch):
        _completed_transcription(store, "j1")
        no_provider = _FakeExtractor()
        no_provider.provider = None
        _patch_extractor(monkeypatch, no_provider)
        r = client.post("/jobs/j1/extract-knowledge")
        assert r.status_code == 503

    def test_total_failure_does_not_overwrite(self, client, store, monkeypatch):
        _completed_transcription(store, "j1")
        # Seed an existing claim so we can prove a failed run doesn't wipe it.
        store.replace_claims_for_job("j1", [_claim("j1").model_dump(mode="json")])
        _patch_extractor(monkeypatch, _FakeExtractor(success=False))

        r = client.post("/jobs/j1/extract-knowledge")
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert store.get_knowledge_status("j1") == "failed"
        # Prior claims survived the failed run.
        assert len(store.get_claims_for_job("j1")) == 1
