"""P12: agentic ingest pipeline — one URL in, maximum extracted value out.

Composes the services that already exist into named pipeline profiles:

  * ``quick`` — download + transcribe, then search-index (P10)
  * ``deep``  — quick + knowledge extraction (P18) + LLM summary
  * ``full``  — deep + sentiment analysis + viral-clip suggestions

Every profile ends with a ``notify`` stage that fires the job's webhook when
one is configured. Stages run sequentially; the ``transcribe`` stage is
load-bearing (its failure aborts the pipeline), every enrichment stage is
additive (a failure is recorded on that stage and the run continues) —
the same never-block-the-pipeline stance as the P18 topic/prediction passes.

Per-stage status lives in the job row's ``pipeline_state`` JSON (statuses:
``pending | running | completed | skipped | failed``), so the pipeline
endpoint can render progress and a restart can see where a run died.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from ..store import JobStatus, get_job_store
from ..knowledge.knowledge_budget import estimate_cost_usd, get_budget_tracker

logger = logging.getLogger(__name__)


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


STAGE_TRANSCRIBE = "transcribe"
STAGE_INDEX = "index"
STAGE_KNOWLEDGE = "knowledge"
STAGE_SUMMARIZE = "summarize"
STAGE_SENTIMENT = "sentiment"
STAGE_CLIPS = "clips"
STAGE_NOTIFY = "notify"

PIPELINE_PROFILES: dict[str, list[str]] = {
    "quick": [STAGE_TRANSCRIBE, STAGE_INDEX, STAGE_NOTIFY],
    "deep": [
        STAGE_TRANSCRIBE,
        STAGE_INDEX,
        STAGE_KNOWLEDGE,
        STAGE_SUMMARIZE,
        STAGE_NOTIFY,
    ],
    "full": [
        STAGE_TRANSCRIBE,
        STAGE_INDEX,
        STAGE_KNOWLEDGE,
        STAGE_SUMMARIZE,
        STAGE_SENTIMENT,
        STAGE_CLIPS,
        STAGE_NOTIFY,
    ],
}
DEFAULT_PROFILE = "deep"

PROFILE_DESCRIPTIONS = {
    "quick": "Download, transcribe, and make searchable.",
    "deep": "Quick + structured knowledge extraction and an LLM summary.",
    "full": "Deep + sentiment/heat analysis and viral clip suggestions.",
}


def _now() -> str:
    return datetime.utcnow().isoformat()


def init_pipeline_state(job_id: str, profile: str, *, job_store=None) -> dict:
    """Write the initial all-pending stage list onto the job row."""
    store = job_store or get_job_store()
    state = {
        "profile": profile,
        "started_at": _now(),
        "completed_at": None,
        "stages": [
            {
                "name": name,
                "status": StageStatus.PENDING.value,
                "started_at": None,
                "completed_at": None,
                "error": None,
                "detail": None,
            }
            for name in PIPELINE_PROFILES[profile]
        ],
    }
    store.set_pipeline_state(job_id, state)
    return state


class PipelineRunner:
    """Sequential stage executor for one job."""

    def __init__(self, *, job_store=None):
        self._job_store = job_store

    @property
    def store(self):
        if self._job_store is not None:
            return self._job_store
        return get_job_store()

    # ----- stage bookkeeping -----

    def _start(self, job_id: str, stage: str) -> None:
        self.store.update_pipeline_stage(
            job_id, stage, status=StageStatus.RUNNING.value, started_at=_now()
        )

    def _finish(
        self,
        job_id: str,
        stage: str,
        status: StageStatus,
        *,
        detail=None,
        error: Optional[str] = None,
    ) -> None:
        self.store.update_pipeline_stage(
            job_id,
            stage,
            status=status.value,
            completed_at=_now(),
            detail=detail,
            error=error,
        )

    # ----- pipeline entry point -----

    async def run(self, job_id: str) -> dict:
        """Drive the job through its profile. Returns the final state.

        Everything needed is read from the job row (restart-safe, like the
        Slice 3 ingestion runner). ``transcribe`` failure aborts; enrichment
        failures are recorded and the run continues.
        """
        store = self.store
        state = store.get_pipeline_state(job_id)
        if not state:
            raise ValueError(f"Job {job_id} has no pipeline state")

        stages = [s["name"] for s in state["stages"]]
        aborted = False
        for stage in stages:
            if aborted:
                self._finish(
                    job_id,
                    stage,
                    StageStatus.SKIPPED,
                    error="Upstream transcribe stage failed.",
                )
                continue
            self._start(job_id, stage)
            try:
                if stage == STAGE_TRANSCRIBE:
                    detail = await self._run_transcribe(job_id)
                elif stage == STAGE_INDEX:
                    detail = await self._run_index(job_id)
                elif stage == STAGE_KNOWLEDGE:
                    detail = self._run_knowledge(job_id)
                elif stage == STAGE_SUMMARIZE:
                    detail = await self._run_summarize(job_id)
                elif stage == STAGE_SENTIMENT:
                    detail = await self._run_sentiment(job_id)
                elif stage == STAGE_CLIPS:
                    detail = await self._run_clips(job_id)
                elif stage == STAGE_NOTIFY:
                    detail = await self._run_notify(job_id)
                else:  # pragma: no cover — profile registry is code-owned
                    raise RuntimeError(f"Unknown stage {stage}")
            except _StageSkipped as skip:
                self._finish(job_id, stage, StageStatus.SKIPPED, error=str(skip))
                continue
            except Exception as e:  # noqa: BLE001 - recorded per-stage
                logger.error("[%s] Pipeline stage %s failed: %s", job_id, stage, e)
                self._finish(job_id, stage, StageStatus.FAILED, error=str(e))
                if stage == STAGE_TRANSCRIBE:
                    aborted = True
                continue
            self._finish(job_id, stage, StageStatus.COMPLETED, detail=detail)

        final = store.get_pipeline_state(job_id) or state
        final["completed_at"] = _now()
        store.set_pipeline_state(job_id, final)
        return final

    # ----- stages -----

    async def _run_transcribe(self, job_id: str) -> dict:
        """Acquire audio + transcribe — same path as the Slice 3 runner.

        ``process_transcription`` already dual-writes artifacts, enqueues
        knowledge (global gate), and auto-indexes for search, so downstream
        stages are mostly confirmations with an on-demand fallback.
        """
        from sift_core.fetch.downloader import DownloaderFactory
        from .ingestion_service import _safe_metadata_dict
        from .workflow import WorkflowProcessor

        store = self.store
        job = store.get_job(job_id)
        url = job.get("source_url")
        if not url:
            raise RuntimeError("Job has no source_url")

        store.set_status(job_id, JobStatus.DOWNLOADING, progress=0.05)
        downloader = DownloaderFactory.get_downloader(url)
        result = await downloader.download(url=url, output_format="m4a", quality="high")
        if not result.success or not result.file_path:
            raise RuntimeError(result.error or "Download failed")
        store.update_job(
            job_id,
            raw_file_path=str(result.file_path),
            content_info=_safe_metadata_dict(result.metadata),
        )

        processor = WorkflowProcessor(store)
        await processor.process_transcription(
            job_id,
            result.file_path,
            model_size=job.get("model_size") or "base",
            language=job.get("language"),
            output_format=job.get("transcription_format") or "json",
            diarize=False,
        )
        refreshed = store.get_job(job_id) or {}
        tr = refreshed.get("transcription_result") or {}
        return {
            "language": tr.get("language"),
            "duration_seconds": tr.get("duration_seconds"),
            "segment_count": len(tr.get("segments") or []),
        }

    async def _run_index(self, job_id: str) -> dict:
        """Ensure the transcript is search-indexed (idempotent)."""
        from ..knowledge.segment_indexer import SegmentIndexer

        indexer = SegmentIndexer(job_store=self.store)
        existing = self.store.count_search_chunks_for_job(job_id)
        if existing:
            return {"chunks": existing, "already_indexed": True}
        return {"chunks": await indexer.index_job(job_id), "already_indexed": False}

    def _run_knowledge(self, job_id: str) -> dict:
        """Ensure knowledge extraction is queued; the backfill worker owns
        the actual run. The pipeline endpoint surfaces live knowledge_status."""
        store = self.store
        status = store.get_knowledge_status(job_id) or "none"
        if status in ("none", "failed"):
            store.enqueue_knowledge_job(job_id)
            status = store.get_knowledge_status(job_id) or status
        return {"knowledge_status": status}

    async def _run_summarize(self, job_id: str) -> dict:
        from ..knowledge.summarizer import SummaryType, TranscriptSummarizer

        job = self.store.get_job(job_id) or {}
        text = (job.get("transcription_result") or {}).get("text")
        if not text:
            raise RuntimeError("No transcript text to summarize")
        summarizer = TranscriptSummarizer.from_settings()
        if not summarizer.provider:
            raise _StageSkipped("No LLM provider configured for summarization.")
        result = await summarizer.summarize(text, SummaryType.BULLET_POINTS)
        get_budget_tracker().record(
            estimate_cost_usd(result.model, result.tokens_used or 0)
        )
        return {
            "summary_type": result.summary_type.value,
            "content": result.content,
            "model": result.model,
            "tokens_used": result.tokens_used,
        }

    async def _run_sentiment(self, job_id: str) -> dict:
        from ..knowledge.knowledge_backfill import resolve_segments_for_job
        from ..knowledge.sentiment_analyzer import SentimentAnalyzer

        segments, _ = resolve_segments_for_job(job_id, self.store)
        if not segments:
            raise RuntimeError("No segments for sentiment analysis")
        analyzer = SentimentAnalyzer.from_settings()
        if not analyzer.provider:
            raise _StageSkipped("No LLM provider configured for sentiment.")
        result = await analyzer.analyze_sentiment(segments=segments, job_id=job_id)
        if not result.success:
            raise RuntimeError(result.error or "Sentiment analysis failed")
        get_budget_tracker().record(
            estimate_cost_usd(result.model, result.tokens_used or 0)
        )
        # Push into the API-layer cache so GET /jobs/{id}/sentiment sees it
        # (lazy import mirrors resolve_segments_for_job's warm-path pattern).
        try:
            from ..api.sentiment_routes import _sentiment_storage

            _sentiment_storage[job_id] = result.to_dict()
        except Exception:  # pragma: no cover — cache is best-effort
            pass
        arc = result.emotional_arc
        return {
            "window_count": len(result.time_windows or []),
            "overall_sentiment": arc.overall_sentiment if arc else None,
            "avg_heat_score": arc.avg_heat_score if arc else None,
            "tokens_used": result.tokens_used,
        }

    async def _run_clips(self, job_id: str) -> dict:
        from ..delivery.clip_generator import ClipGenerator
        from ..knowledge.knowledge_backfill import resolve_segments_for_job

        segments, _ = resolve_segments_for_job(job_id, self.store)
        if not segments:
            raise RuntimeError("No segments for clip generation")
        generator = ClipGenerator.from_settings()
        if not generator.provider:
            raise _StageSkipped("No LLM provider configured for clips.")
        result = await generator.generate_clips(segments=segments, job_id=job_id)
        if not result.success:
            raise RuntimeError(result.error or "Clip generation failed")
        get_budget_tracker().record(
            estimate_cost_usd(result.model, result.tokens_used or 0)
        )
        clips = [
            {
                "start_time": c.start_time,
                "end_time": c.end_time,
                "caption": c.caption,
                "viral_score": c.viral_score,
            }
            for c in (result.clips or [])
        ]
        try:
            from ..api.clip_routes import _clips_storage

            _clips_storage[job_id] = [c.to_dict() for c in (result.clips or [])]
        except Exception:  # pragma: no cover — cache is best-effort
            pass
        return {"clip_count": len(clips), "clips": clips}

    async def _run_notify(self, job_id: str) -> dict:
        job = self.store.get_job(job_id) or {}
        if not job.get("webhook_url"):
            raise _StageSkipped("No webhook_url configured on the job.")
        from ..delivery.webhook_notifier import get_webhook_notifier

        ok = await get_webhook_notifier().notify_job_complete(job)
        if not ok:
            raise RuntimeError("Webhook delivery failed")
        return {"delivered": True}


class _StageSkipped(Exception):
    """Raised inside a stage to mark it skipped (not failed) with a reason."""
