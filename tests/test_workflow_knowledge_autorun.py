"""Tests for P18 Phase D auto-run: a completed transcription enqueues
knowledge extraction so new episodes flow into the KB without a manual trigger.

The hook is deliberately non-blocking, idempotent, and best-effort: it reuses
the Phase C.3 ``enqueue_knowledge_job`` state machine (``none|failed → pending``)
and must never let an enqueue failure break the transcription that just
succeeded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.core.job_store import JobStore
from app.core.job_store._enums import JobStatus, JobType
from app.core.workflow import WorkflowProcessor


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "autorun.db")


@pytest.fixture
def processor(store: JobStore) -> WorkflowProcessor:
    return WorkflowProcessor(job_store=store)


@pytest.fixture(autouse=True)
def _reset_auto_extract():
    """Default the flag ON for every test; restore after."""
    settings = get_settings()
    original = settings.knowledge_auto_extract
    settings.knowledge_auto_extract = True
    yield settings
    settings.knowledge_auto_extract = original


def _transcribed_job(store: JobStore, job_id: str = "j1") -> None:
    store.create_job(job_id, JobType.TRANSCRIBE)
    store.update_job(
        job_id,
        transcription_result={"segments": [{"start": 0, "end": 1, "text": "hi"}]},
    )
    store.set_status(job_id, JobStatus.COMPLETED)


class TestEnqueueHook:
    def test_enqueues_pending_when_flag_on(
        self, processor: WorkflowProcessor, store: JobStore
    ):
        _transcribed_job(store)
        processor._enqueue_knowledge_extraction("j1")
        assert store.get_knowledge_status("j1") == "pending"

    def test_noop_when_flag_off(
        self, processor: WorkflowProcessor, store: JobStore, _reset_auto_extract
    ):
        _reset_auto_extract.knowledge_auto_extract = False
        _transcribed_job(store)
        processor._enqueue_knowledge_extraction("j1")
        # Flag off → job is left untouched (still 'none'), nothing queued.
        assert store.get_knowledge_status("j1") == "none"

    def test_idempotent_on_repeat(
        self, processor: WorkflowProcessor, store: JobStore
    ):
        _transcribed_job(store)
        processor._enqueue_knowledge_extraction("j1")
        # Second call is a harmless no-op — already pending.
        processor._enqueue_knowledge_extraction("j1")
        assert store.get_knowledge_status("j1") == "pending"

    def test_best_effort_swallows_store_errors(
        self, processor: WorkflowProcessor
    ):
        class _BoomStore:
            def enqueue_knowledge_job(self, job_id):  # noqa: ARG002
                raise RuntimeError("db down")

        processor.job_store = _BoomStore()
        # Must not raise — a failed enqueue can never break the transcription.
        processor._enqueue_knowledge_extraction("j1")

    def test_already_ready_job_not_requeued(
        self, processor: WorkflowProcessor, store: JobStore
    ):
        _transcribed_job(store)
        store.set_knowledge_status("j1", "ready")
        processor._enqueue_knowledge_extraction("j1")
        # ready jobs are terminal for enqueue — stay ready, not re-pended.
        assert store.get_knowledge_status("j1") == "ready"


class _FakeSegment:
    def __init__(self, start, end, text, speaker=None):
        self.start = start
        self.end = end
        self.text = text
        self.speaker = speaker


class _FakeResult:
    success = True
    text = "hello world"
    language = "en"
    language_probability = 0.99
    duration = 1.0
    error = None

    def __init__(self):
        self.segments = [_FakeSegment(0.0, 1.0, "hello world")]


class _FakeTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    async def transcribe(self, *args, **kwargs):
        return _FakeResult()


class TestProcessTranscriptionIntegration:
    @pytest.mark.asyncio
    async def test_completed_transcription_enqueues_knowledge(
        self, processor: WorkflowProcessor, store: JobStore, monkeypatch, tmp_path
    ):
        import app.core.transcriber as transcriber_mod

        monkeypatch.setattr(
            transcriber_mod, "AudioTranscriber", _FakeTranscriber
        )

        store.create_job("jx", JobType.TRANSCRIBE)
        audio = tmp_path / "a.m4a"
        audio.write_bytes(b"\x00")

        await processor.process_transcription(
            "jx", audio, model_size="base", output_format="text"
        )

        assert store.get_job("jx")["status"] == JobStatus.COMPLETED.value
        assert store.get_knowledge_status("jx") == "pending"
