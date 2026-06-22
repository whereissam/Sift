"""Lifecycle + glue coverage for the backfill worker (P18 Phase C.3).

The core extraction logic is covered in test_knowledge_backfill.py; this file
exercises the asyncio lifecycle (start/stop/run-loop), the default extractor
factory, the module singleton helpers, the seed-on-startup branch, and the
process_job exception path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import get_settings
from app.core import knowledge_backfill as kb
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType
from app.core.knowledge_backfill import (
    KnowledgeBackfillWorker,
    get_backfill_worker,
    start_backfill_worker,
    stop_backfill_worker,
)
from app.core.knowledge_budget import get_budget_tracker


@pytest.fixture(autouse=True)
def _reset_budget():
    get_budget_tracker().reset()
    yield
    get_budget_tracker().reset()


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    s = JobStore(db_path=tmp_path / "lifecycle.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    return s


@pytest.fixture(autouse=True)
def _restore_settings():
    s = get_settings()
    saved = (s.knowledge_backfill_enabled, s.knowledge_seed_on_startup)
    yield s
    (s.knowledge_backfill_enabled, s.knowledge_seed_on_startup) = saved


def _job_with_transcript(store: JobStore, job_id: str) -> None:
    store.create_job(job_id, JobType.TRANSCRIBE)
    store.update_job(
        job_id,
        transcription_result={"segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]},
    )


class TestModuleSingleton:
    def test_get_backfill_worker_is_singleton(self, monkeypatch):
        monkeypatch.setattr(kb, "_worker", None)
        a = get_backfill_worker()
        b = get_backfill_worker()
        assert a is b

    @pytest.mark.asyncio
    async def test_start_and_stop_helpers(self, monkeypatch, _restore_settings, store):
        monkeypatch.setattr(kb, "_worker", None)
        _restore_settings.knowledge_backfill_enabled = True
        _restore_settings.knowledge_seed_on_startup = False
        # Neutralize the real tick so the loop does nothing expensive.
        monkeypatch.setattr(KnowledgeBackfillWorker, "tick", _noop_tick)
        await start_backfill_worker()
        worker = kb._worker
        assert worker is not None and worker._running is True
        await stop_backfill_worker()
        # stop_backfill_worker clears the module singleton.
        assert kb._worker is None


async def _noop_tick(self):  # bound as a method via setattr
    return 0


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_disabled_is_noop(self, _restore_settings):
        _restore_settings.knowledge_backfill_enabled = False
        worker = KnowledgeBackfillWorker()
        await worker.start()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_start_runs_loop_then_stops(self, monkeypatch, _restore_settings, store):
        _restore_settings.knowledge_backfill_enabled = True
        _restore_settings.knowledge_seed_on_startup = False

        ticks = {"n": 0}

        async def counting_tick(self):
            ticks["n"] += 1
            return 0

        monkeypatch.setattr(KnowledgeBackfillWorker, "tick", counting_tick)
        worker = KnowledgeBackfillWorker()
        worker._check_interval = 0.001  # spin fast so the loop ticks within the test
        await worker.start()
        await asyncio.sleep(0.02)
        await worker.stop()
        assert worker._running is False
        assert ticks["n"] >= 1

    @pytest.mark.asyncio
    async def test_double_start_warns_and_stays_single(
        self, monkeypatch, _restore_settings, store
    ):
        _restore_settings.knowledge_backfill_enabled = True
        monkeypatch.setattr(KnowledgeBackfillWorker, "tick", _noop_tick)
        worker = KnowledgeBackfillWorker()
        worker._check_interval = 0.001
        await worker.start()
        first_task = worker._task
        await worker.start()  # already running → warning branch, no new task
        assert worker._task is first_task
        await worker.stop()

    @pytest.mark.asyncio
    async def test_seed_on_startup_marks_pending(
        self, monkeypatch, _restore_settings, store
    ):
        _restore_settings.knowledge_backfill_enabled = True
        _restore_settings.knowledge_seed_on_startup = True
        _job_with_transcript(store, "seedme")  # status 'none' + has transcript
        monkeypatch.setattr(KnowledgeBackfillWorker, "tick", _noop_tick)
        worker = KnowledgeBackfillWorker()
        worker._check_interval = 0.001
        await worker.start()
        await worker.stop()
        assert store.get_knowledge_status("seedme") == "pending"


class TestBuildExtractorDefault:
    def test_default_factory_uses_from_settings(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(
            "app.core.knowledge_backfill.KnowledgeExtractor.from_settings",
            classmethod(lambda cls, *, downgrade=False: sentinel),
        )
        worker = KnowledgeBackfillWorker()  # no injected factory
        assert worker._build_extractor(False) is sentinel


class TestProcessJobException:
    @pytest.mark.asyncio
    async def test_extractor_raises_marks_failed(self, store):
        _job_with_transcript(store, "boom")
        store.enqueue_knowledge_job("boom")

        class _Raiser:
            provider = "openai"

            async def extract_claims(self, **kwargs):
                raise RuntimeError("llm exploded")

        worker = KnowledgeBackfillWorker(extractor_factory=lambda d: _Raiser())
        outcome = await worker.process_job({"job_id": "boom"})
        assert outcome is False
        assert store.get_knowledge_status("boom") == "failed"
