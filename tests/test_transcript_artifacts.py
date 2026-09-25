"""Slice 2 tests: versioned transcript artifacts, addressable segments,
dual-write with the legacy blob, and row-fallback reads."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.store as job_store_pkg
from app.store import JobType
from sift_core.transcribe.transcriber import TranscriptionSegment as CoreSegment


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = job_store_pkg.JobStore(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(job_store_pkg, "_job_store", s)
    return s


def _asset_with_job(store, job_id="j1"):
    job = store.create_job(
        job_id, JobType.TRANSCRIBE, source_url="https://youtu.be/dQw4w9WgXcQ"
    )
    return job["asset_id"]


SEGMENTS = [
    CoreSegment(start=0.0, end=1.5, text="hello", speaker="SPEAKER_00", avg_logprob=-0.25),
    CoreSegment(start=1.5, end=3.25, text="world", speaker="SPEAKER_01", avg_logprob=-0.75),
]


# ---------------------------------------------------------------------------
# Artifact + segment persistence
# ---------------------------------------------------------------------------

def test_create_artifact_writes_addressable_segments(store):
    asset_id = _asset_with_job(store)
    artifact_id = store.create_transcript_artifact(
        asset_id=asset_id,
        job_id="j1",
        segments=SEGMENTS,
        pipeline_version="whisper:base/diar=1",
        model_name="base",
        language="en",
        diarization_enabled=True,
    )

    artifact = store.get_latest_transcript_artifact(asset_id)
    assert artifact["artifact_id"] == artifact_id
    assert artifact["pipeline_version"] == "whisper:base/diar=1"
    assert artifact["supersedes_artifact_id"] is None
    assert artifact["diarization_enabled"] == 1

    rows = store.get_transcript_segments(artifact_id)
    assert [r["ordinal"] for r in rows] == [0, 1]
    assert rows[0]["start_ms"] == 0 and rows[0]["end_ms"] == 1500
    assert rows[1]["start_ms"] == 1500 and rows[1]["end_ms"] == 3250
    assert rows[0]["speaker_id"] == "SPEAKER_00"
    assert rows[0]["model_confidence_raw"] == -0.25
    assert rows[0]["confidence_normalized"] is None  # no undocumented transform
    assert rows[1]["text"] == "world"


def test_retranscription_creates_superseding_artifact(store):
    asset_id = _asset_with_job(store)
    first = store.create_transcript_artifact(
        asset_id=asset_id, job_id="j1", segments=SEGMENTS,
        pipeline_version="whisper:base/diar=0",
    )
    better = [CoreSegment(start=0.0, end=3.25, text="hello world", avg_logprob=-0.1)]
    second = store.create_transcript_artifact(
        asset_id=asset_id, job_id="j2", segments=better,
        pipeline_version="whisper:large-v3/diar=0",
    )

    assert store.get_latest_transcript_artifact(asset_id)["artifact_id"] == second
    assert (
        store.get_latest_transcript_artifact(asset_id)["supersedes_artifact_id"]
        == first
    )
    # History is immutable: the first artifact's rows are untouched.
    assert len(store.get_transcript_segments(first)) == 2
    assert len(store.get_transcript_segments(second)) == 1
    assert len(store.get_transcript_artifacts(asset_id)) == 2


def test_record_for_job_requires_asset(store):
    store.create_job("no-asset", JobType.TRANSCRIBE, source_url="resume://x.m4a")
    assert (
        store.record_transcript_artifact_for_job(
            "no-asset", SEGMENTS, pipeline_version="whisper:base/diar=0"
        )
        is None
    )

    _asset_with_job(store, "with-asset")
    artifact_id = store.record_transcript_artifact_for_job(
        "with-asset", SEGMENTS, pipeline_version="whisper:base/diar=0"
    )
    assert artifact_id is not None
    assert store.get_transcript_artifact_for_job("with-asset")["artifact_id"] == artifact_id


# ---------------------------------------------------------------------------
# Dual-write verification
# ---------------------------------------------------------------------------

def test_verify_dual_write_consistency(store):
    _asset_with_job(store, "j1")
    store.update_job(
        "j1",
        transcription_result={
            "text": "hello world",
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                for s in SEGMENTS
            ],
        },
    )
    store.record_transcript_artifact_for_job(
        "j1", SEGMENTS, pipeline_version="whisper:base/diar=0"
    )
    assert store.verify_transcript_dual_write("j1") is True

    # A mismatch is detected (and only logged, never raised).
    store.update_job(
        "j1",
        transcription_result={"text": "hello", "segments": [{"start": 0, "end": 1, "text": "x"}]},
    )
    assert store.verify_transcript_dual_write("j1") is False

    # Missing either side → None.
    _asset_with_job(store, "j2")
    assert store.verify_transcript_dual_write("j2") is None
    assert store.verify_transcript_dual_write("missing") is None


# ---------------------------------------------------------------------------
# Row-fallback read in the durable mapping
# ---------------------------------------------------------------------------

def test_mapping_rebuilds_segments_from_rows_when_blob_lacks_them(store):
    from app.api.transcription_store import transcription_jobs

    _asset_with_job(store, "j1")
    # Legacy-style blob without segments (e.g. text-only workflow result).
    store.update_job("j1", transcription_result={"text": "hello world"})
    store.record_transcript_artifact_for_job(
        "j1", SEGMENTS, pipeline_version="whisper:base/diar=1"
    )

    job = transcription_jobs["j1"]
    assert job.text == "hello world"
    assert len(job.segments) == 2
    assert job.segments[0].start == 0.0
    assert job.segments[1].end == 3.25
    assert job.segments[0].speaker == "SPEAKER_00"
    assert job.segments[0].avg_logprob == -0.25


# ---------------------------------------------------------------------------
# API pipeline integration: blob + rows written, confidence preserved
# ---------------------------------------------------------------------------

def test_process_transcription_dual_writes(store, tmp_path, monkeypatch):
    from app.api import transcription_routes
    from app.api.schemas import JobStatus, TranscriptionJob, TranscriptionOutputFormat
    from app.api.transcription_store import transcription_jobs
    from sift_core.transcribe import transcription_engine as engine_mod

    job_id = "api-1"
    job = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0.0,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        created_at=datetime(2026, 7, 12, 8, 0, 0),
    )
    job._persist_extras = {"model_size": "base"}
    transcription_jobs[job_id] = job

    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"fake")

    fake_result = SimpleNamespace(
        success=True,
        text="hello world",
        segments=SEGMENTS,
        language="en",
        language_probability=0.98,
        duration=3.25,
        error=None,
    )

    class FakeEngine:
        async def transcribe(self, audio_path, language=None):
            return fake_result

    monkeypatch.setattr(engine_mod, "get_engine", lambda et: FakeEngine())

    request = SimpleNamespace(
        engine="sensevoice",
        model=None,
        language=None,
        translate=False,
        diarize=False,
        num_speakers=None,
        output_format=TranscriptionOutputFormat.TEXT,
        save_to=None,
        enhance=False,
        enhancement_preset="medium",
        keep_enhanced=False,
        keep_audio=True,
    )

    asyncio.run(
        transcription_routes._process_transcription(job_id, request, audio)
    )

    # Legacy blob path intact.
    loaded = transcription_jobs[job_id]
    assert loaded.status == JobStatus.COMPLETED
    assert loaded.text == "hello world"
    assert loaded.segments[0].avg_logprob == -0.25

    # Artifact rows written with raw confidence and pipeline stamp.
    artifact = store.get_transcript_artifact_for_job(job_id)
    assert artifact is not None
    assert artifact["pipeline_version"] == "sensevoice:-/diar=0"
    rows = store.get_transcript_segments(artifact["artifact_id"])
    assert len(rows) == 2
    assert rows[1]["model_confidence_raw"] == -0.75

    assert store.verify_transcript_dual_write(job_id) is True
