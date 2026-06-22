"""Tests for app/core/knowledge_backfill.py (P18 Phase C.3).

The worker's testable surface is ``tick`` / ``process_job`` driven with an
injected extractor factory — no real LLM calls, no asyncio loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType
from app.core.knowledge_backfill import (
    KnowledgeBackfillWorker,
    resolve_segments_for_job,
)
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
    s = JobStore(db_path=tmp_path / "backfill_worker.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    return s


def _job_with_transcript(store: JobStore, job_id: str, *, priority: int = 5) -> None:
    store.create_job(job_id, JobType.TRANSCRIBE, priority=priority)
    store.update_job(
        job_id,
        transcription_result={
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Bitcoin will hit 200k", "speaker": "A"}
            ]
        },
    )
    store.enqueue_knowledge_job(job_id)


def _make_claim(job_id: str, text: str = "Bitcoin will hit 200k") -> Claim:
    return Claim(
        claim_id=compute_claim_id(
            text=text, episode_id=job_id, speaker=None, timestamp_start=0.0
        ),
        episode_id=job_id,
        text=text,
        timestamp_start=0.0,
        timestamp_end=2.0,
        claim_type=ClaimType.PREDICTION,
        confidence=0.9,
        evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )


class _FakeExtractor:
    def __init__(self, *, claims=None, success=True, tokens=1000,
                 model="gpt-4o", provider="openai", has_provider=True):
        self.provider = object() if has_provider else None
        self._claims = claims or []
        self._success = success
        self._tokens = tokens
        self._model = model
        self._provider_name = provider

    async def extract_claims(self, *, episode_id, segments, source_url=None):
        return ExtractionRunResult(
            job_id=episode_id,
            success=self._success,
            claims=self._claims,
            tokens_used=self._tokens,
            model=self._model,
            provider=self._provider_name,
        )


def _factory(extractor, *, capture: list | None = None):
    def make(downgrade: bool):
        if capture is not None:
            capture.append(downgrade)
        return extractor
    return make


# ===== process_job =====


async def test_process_job_happy_path(store: JobStore):
    _job_with_transcript(store, "j1")
    fake = _FakeExtractor(claims=[_make_claim("j1")])
    worker = KnowledgeBackfillWorker(extractor_factory=_factory(fake))

    assert await worker.process_job(store.get_job("j1")) is True
    assert store.get_knowledge_status("j1") == "ready"
    assert store.get_knowledge_version("j1") == 1
    assert len(store.get_claims_for_job("j1")) == 1
    # tokens recorded as spend (gpt-4o priced > 0)
    assert get_budget_tracker().spent_today() > 0


async def test_process_job_no_segments_fails(store: JobStore):
    store.create_job("j1", JobType.TRANSCRIBE)
    store.set_knowledge_status("j1", "pending")
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(_FakeExtractor(claims=[_make_claim("j1")]))
    )
    assert await worker.process_job({"job_id": "j1"}) is False
    assert store.get_knowledge_status("j1") == "failed"


async def test_process_job_lock_lost_returns_none(store: JobStore):
    _job_with_transcript(store, "j1")
    # Another worker grabs the lock first.
    assert store.acquire_knowledge_lock("j1", "other-worker") is True
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(_FakeExtractor(claims=[_make_claim("j1")]))
    )
    assert await worker.process_job(store.get_job("j1")) is None


async def test_process_job_extraction_failure_marks_failed(store: JobStore):
    _job_with_transcript(store, "j1")
    fake = _FakeExtractor(claims=[], success=False)
    worker = KnowledgeBackfillWorker(extractor_factory=_factory(fake))
    assert await worker.process_job(store.get_job("j1")) is False
    assert store.get_knowledge_status("j1") == "failed"


async def test_process_job_no_provider_requeues(store: JobStore):
    _job_with_transcript(store, "j1")
    fake = _FakeExtractor(has_provider=False)
    worker = KnowledgeBackfillWorker(extractor_factory=_factory(fake))
    assert await worker.process_job(store.get_job("j1")) is None
    # Requeued, not failed — provider may appear later.
    assert store.get_knowledge_status("j1") == "pending"


# ===== downgrade =====


async def test_downgrade_when_over_threshold(store: JobStore):
    _job_with_transcript(store, "j1")
    get_budget_tracker().record(5.0)  # push spend over threshold
    captured: list[bool] = []
    fake = _FakeExtractor(claims=[_make_claim("j1")])
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(fake, capture=captured),
        downgrade_threshold_usd=1.0,
    )
    await worker.process_job(store.get_job("j1"))
    assert captured == [True]
    assert get_budget_tracker().downgrades_today() == 1


async def test_no_downgrade_under_threshold(store: JobStore):
    _job_with_transcript(store, "j1")
    captured: list[bool] = []
    fake = _FakeExtractor(claims=[_make_claim("j1")])
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(fake, capture=captured),
        downgrade_threshold_usd=1.0,
    )
    await worker.process_job(store.get_job("j1"))
    assert captured == [False]
    assert get_budget_tracker().downgrades_today() == 0


# ===== tick =====


async def test_tick_processes_priority_order_and_batch(store: JobStore):
    _job_with_transcript(store, "low", priority=1)
    _job_with_transcript(store, "high", priority=9)
    order: list[str] = []

    class _RecordingExtractor(_FakeExtractor):
        async def extract_claims(self, *, episode_id, segments, source_url=None):
            order.append(episode_id)
            return await super().extract_claims(
                episode_id=episode_id, segments=segments, source_url=source_url
            )

    fake = _RecordingExtractor(claims=[])
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(fake), batch_size=5
    )
    processed = await worker.tick()
    assert processed == 2
    assert order[0] == "high"  # priority-ordered


async def test_tick_respects_batch_size(store: JobStore):
    for i in range(4):
        _job_with_transcript(store, f"j{i}")
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(_FakeExtractor(claims=[])), batch_size=2
    )
    assert await worker.tick() == 2


async def test_tick_skips_when_over_budget(store: JobStore):
    _job_with_transcript(store, "j1")
    get_budget_tracker().record(10.0)
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(_FakeExtractor(claims=[])),
        daily_budget_usd=5.0,
    )
    assert await worker.tick() == 0
    # Job untouched — still pending.
    assert store.get_knowledge_status("j1") == "pending"


async def test_tick_reaps_stale_lock(store: JobStore):
    from datetime import datetime, timedelta

    _job_with_transcript(store, "j1")
    store.acquire_knowledge_lock("j1", "dead-worker")
    stale = (datetime.utcnow() - timedelta(seconds=10000)).isoformat()
    store.update_job("j1", knowledge_locked_at=stale)
    worker = KnowledgeBackfillWorker(
        extractor_factory=_factory(_FakeExtractor(claims=[_make_claim("j1")])),
        lock_ttl=900,
    )
    processed = await worker.tick()
    assert processed == 1
    assert store.get_knowledge_status("j1") == "ready"


# ===== segment resolution =====


def test_resolve_segments_cold_path(store: JobStore):
    store.create_job("j1", JobType.TRANSCRIBE, source_url="https://x.test/a")
    store.update_job(
        "j1",
        transcription_result={
            "segments": [{"start": 0, "end": 1, "text": "hello", "speaker": None}]
        },
    )
    segs, url = resolve_segments_for_job("j1", store)
    assert len(segs) == 1
    assert segs[0]["text"] == "hello"
    assert url == "https://x.test/a"


def test_resolve_segments_missing_returns_empty(store: JobStore):
    store.create_job("j1", JobType.TRANSCRIBE)
    assert resolve_segments_for_job("j1", store) == ([], None)
