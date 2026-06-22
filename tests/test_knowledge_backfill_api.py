"""Tests for the Phase C.3 backfill API surface in app/api/knowledge_routes.py.

Covers the on-demand GET 202 behavior, idempotent enqueue, and backfill-status.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.knowledge_routes import router as knowledge_router
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType
from app.core.knowledge_backfill import KnowledgeBackfillWorker
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
def _reset_budget():
    get_budget_tracker().reset()
    yield
    get_budget_tracker().reset()


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    s = JobStore(db_path=tmp_path / "api.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    return s


@pytest.fixture
def client(store: JobStore) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_router)
    return TestClient(app)


def _job_with_transcript(store: JobStore, job_id: str, *, n_segments: int = 1) -> None:
    store.create_job(job_id, JobType.TRANSCRIBE)
    store.update_job(
        job_id,
        transcription_result={
            "segments": [
                {"start": float(i), "end": float(i + 1), "text": f"seg {i}", "speaker": None}
                for i in range(n_segments)
            ]
        },
    )


def _make_claim(job_id: str) -> Claim:
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
    def __init__(self, claims):
        self.provider = object()
        self._claims = claims

    async def extract_claims(self, *, episode_id, segments, source_url=None):
        return ExtractionRunResult(
            job_id=episode_id, success=True, claims=self._claims,
            tokens_used=100, model="gpt-4o-mini", provider="openai",
        )


class TestGetKnowledge:
    def test_ready_job_returns_cached_200(self, client: TestClient, store: JobStore):
        _job_with_transcript(store, "j1")
        store.replace_claims_for_job("j1", [_make_claim("j1").model_dump(mode="json")])
        store.set_knowledge_status("j1", "complete")
        r = client.get("/jobs/j1/knowledge?min_confidence=0.1")
        assert r.status_code == 200
        body = r.json()
        assert body["run_state"] == "ready"
        assert body["claim_count"] == 1

    def test_running_job_returns_202(self, client: TestClient, store: JobStore):
        _job_with_transcript(store, "j1")
        store.set_knowledge_status("j1", "running")
        r = client.get("/jobs/j1/knowledge")
        assert r.status_code == 202
        assert r.json()["run_state"] == "running"

    def test_pending_large_job_returns_202(self, client: TestClient, store: JobStore):
        # Transcript exceeds knowledge_inline_max_segments (80) → too big to run
        # inline → deferred to the background worker → 202 pending.
        _job_with_transcript(store, "j1", n_segments=100)
        store.enqueue_knowledge_job("j1")
        r = client.get("/jobs/j1/knowledge")
        assert r.status_code == 202
        assert r.json()["run_state"] == "pending"

    def test_pending_small_job_runs_inline(
        self, client: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
    ):
        _job_with_transcript(store, "j1", n_segments=1)
        store.enqueue_knowledge_job("j1")
        # Force "provider available" + inject a fake extractor into the worker.
        monkeypatch.setattr(
            "app.api.knowledge_routes.KnowledgeExtractor.is_available",
            staticmethod(lambda: True),
        )
        worker = KnowledgeBackfillWorker(
            extractor_factory=lambda downgrade: _FakeExtractor([_make_claim("j1")])
        )
        monkeypatch.setattr(
            "app.api.knowledge_routes.get_backfill_worker", lambda: worker
        )
        r = client.get("/jobs/j1/knowledge?min_confidence=0.1")
        assert r.status_code == 200
        assert r.json()["run_state"] == "ready"
        assert r.json()["claim_count"] == 1


class TestEnqueue:
    def test_enqueue_none_job(self, client: TestClient, store: JobStore):
        _job_with_transcript(store, "j1")
        r = client.post("/jobs/j1/knowledge/enqueue")
        assert r.status_code == 200
        body = r.json()
        assert body["enqueued"] is True
        assert body["knowledge_status"] == "pending"

    def test_enqueue_idempotent(self, client: TestClient, store: JobStore):
        _job_with_transcript(store, "j1")
        client.post("/jobs/j1/knowledge/enqueue")
        r = client.post("/jobs/j1/knowledge/enqueue")
        assert r.json()["enqueued"] is False

    def test_enqueue_unknown_job_404(self, client: TestClient):
        r = client.post("/jobs/ghost/knowledge/enqueue")
        assert r.status_code == 404


class TestBackfillStatus:
    def test_status_reports_counts_and_spend(self, client: TestClient, store: JobStore):
        _job_with_transcript(store, "a")
        _job_with_transcript(store, "b")
        store.enqueue_knowledge_job("a")
        store.set_knowledge_status("b", "complete")
        get_budget_tracker().record(1.25)
        r = client.get("/knowledge/backfill-status")
        assert r.status_code == 200
        body = r.json()
        assert body["pending"] == 1
        assert body["counts"]["ready"] == 1  # 'complete' folded into 'ready'
        assert body["spent_today_usd"] == pytest.approx(1.25)
