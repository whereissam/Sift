"""P18 Phase C.3: background knowledge-extraction backfill worker.

Two triggers feed the same machinery (locked design decision #1):

  * **Background** — this worker ticks every ``knowledge_backfill_interval``
    seconds, pulls a priority-ordered batch of ``pending`` jobs, and extracts
    each under a claim-lock so a competing worker (or the on-demand route)
    never double-extracts.
  * **On-demand** — the knowledge route reuses ``process_job`` /
    ``persist_extraction_result`` / ``resolve_segments_for_job`` so an
    inline run shares the exact same persistence + budget accounting.

Cost guardrail (decision #4): each tick checks the per-UTC-day spend against
``knowledge_daily_budget_usd`` (hard stop) and
``knowledge_model_downgrade_threshold_usd`` (switch to a cheaper model). Both
default to ``None`` = unlimited.

The orchestration loop is deliberately thin; the testable unit is ``tick`` /
``process_job``, which take no time and can be driven directly with an injected
extractor factory.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from ..config import get_settings
from .job_store import get_job_store
from .knowledge_budget import estimate_cost_usd, get_budget_tracker
from .knowledge_extractor import KnowledgeExtractor
from .knowledge_schema import EXTRACTION_VERSION, ExtractionRunResult

logger = logging.getLogger(__name__)

# Factory signature: (downgrade: bool) -> KnowledgeExtractor
ExtractorFactory = Callable[[bool], KnowledgeExtractor]


# ===== Shared helpers (used by both the worker and the on-demand route) =====


def resolve_segments_for_job(
    job_id: str, job_store=None
) -> tuple[list[dict], Optional[str]]:
    """Return ``(segments, source_url)`` for a job, warm or cold.

    Tries the in-memory transcription store first (a job transcribed this
    process lifetime), then falls back to the persisted
    ``transcription_result.segments`` on the jobs row (cold inventory — the
    whole point of backfill). Returns ``([], None)`` when neither has usable
    segments.
    """
    # Warm path — imported lazily so core doesn't hard-depend on the api layer.
    try:
        from ..api.transcription_store import transcription_jobs

        job = transcription_jobs.get(job_id)
        if job and job.segments:
            segs = [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                for s in job.segments
            ]
            return segs, job.source_url
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("warm segment lookup failed for %s: %s", job_id, e)

    # Cold path — reconstruct from the persisted transcription_result.
    store = job_store or get_job_store()
    row = store.get_job(job_id)
    if row:
        tr = row.get("transcription_result")
        if isinstance(tr, dict):
            raw_segs = tr.get("segments") or []
            norm = [
                {
                    "start": s.get("start"),
                    "end": s.get("end"),
                    "text": s.get("text"),
                    "speaker": s.get("speaker"),
                }
                for s in raw_segs
                if s.get("text")
            ]
            if norm:
                return norm, row.get("source_url")
    return [], None


def persist_extraction_result(
    job_store, job_id: str, result: ExtractionRunResult
) -> None:
    """Persist a successful extraction (claims + entities + topics + predictions).

    Single transactional ``replace_claims_for_job`` so every knowledge object
    for the episode lands or rolls back together. Mirrors the route's Phase A→
    C.2 persistence exactly — factored here so the worker and the on-demand
    path can't drift.
    """
    claim_rows = [c.model_dump(mode="json") for c in result.claims]
    entity_rows = [e.model_dump(mode="json") for e in result.entities]
    mention_rows = [m.model_dump(mode="json") for m in result.mentions]
    topic_rows = [t.model_dump(mode="json") for t in result.topics]
    edge_rows = [edge.model_dump(mode="json") for edge in result.claim_topic_edges]
    prediction_rows = [p.model_dump(mode="json") for p in result.predictions]
    job_store.replace_claims_for_job(
        job_id,
        claim_rows,
        entities=entity_rows,
        mentions=mention_rows,
        topics=topic_rows,
        claim_topic_edges=edge_rows,
        predictions=prediction_rows,
    )


def quarantine_failures(job_store, job_id: str, result: ExtractionRunResult) -> None:
    """Persist per-chunk failures to the quarantine table (debug prompt drift)."""
    for f in result.failures:
        job_store.record_extraction_failure(
            episode_id=job_id,
            chunk_index=f.chunk_index,
            error=f.error,
            raw_output=f.raw_output,
            extraction_version=EXTRACTION_VERSION,
            model=result.model,
        )


class KnowledgeBackfillWorker:
    """Background worker that extracts knowledge for pending jobs under a lock."""

    def __init__(
        self,
        *,
        worker_id: Optional[str] = None,
        check_interval: Optional[int] = None,
        batch_size: Optional[int] = None,
        lock_ttl: Optional[int] = None,
        daily_budget_usd: Optional[float] = None,
        downgrade_threshold_usd: Optional[float] = None,
        extractor_factory: Optional[ExtractorFactory] = None,
    ) -> None:
        s = get_settings()
        self.worker_id = worker_id or f"backfill-{os.getpid()}"
        self._check_interval = check_interval or s.knowledge_backfill_interval
        self._batch_size = batch_size or s.knowledge_backfill_batch_size
        self._lock_ttl = lock_ttl or s.knowledge_lock_ttl_seconds
        # Budget knobs default to settings but stay overridable for tests.
        self._daily_budget = (
            daily_budget_usd
            if daily_budget_usd is not None
            else s.knowledge_daily_budget_usd
        )
        self._downgrade_threshold = (
            downgrade_threshold_usd
            if downgrade_threshold_usd is not None
            else s.knowledge_model_downgrade_threshold_usd
        )
        self._extractor_factory = extractor_factory
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _build_extractor(self, downgrade: bool) -> KnowledgeExtractor:
        if self._extractor_factory is not None:
            return self._extractor_factory(downgrade)
        return KnowledgeExtractor.from_settings(downgrade=downgrade)

    # ===== Lifecycle =====

    async def start(self) -> None:
        s = get_settings()
        if not s.knowledge_backfill_enabled:
            logger.info("Knowledge backfill worker is disabled")
            return
        if self._running:
            logger.warning("Knowledge backfill worker already running")
            return
        if s.knowledge_seed_on_startup:
            try:
                n = get_job_store().mark_jobs_pending_for_backfill()
                if n:
                    logger.info("Knowledge backfill: seeded %d job(s) as pending", n)
            except Exception as e:
                logger.error("Knowledge backfill seed failed: %s", e)
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Knowledge backfill worker started (interval=%ds, batch=%d, id=%s)",
            self._check_interval,
            self._batch_size,
            self.worker_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Knowledge backfill worker stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error("Knowledge backfill tick error: %s", e)
            await asyncio.sleep(self._check_interval)

    # ===== Core (testable) =====

    async def tick(self) -> int:
        """One backfill cycle. Returns the number of jobs processed."""
        store = get_job_store()
        # Reap crashed-worker locks so their jobs become claimable again.
        reaped = store.reap_stale_knowledge_locks(self._lock_ttl)
        if reaped:
            logger.info("Knowledge backfill: reaped %d stale lock(s)", reaped)

        tracker = get_budget_tracker()
        if tracker.over_global_budget(self._daily_budget):
            logger.info("Knowledge backfill: daily budget reached — skipping tick")
            return 0

        jobs = store.list_pending_knowledge_jobs(limit=self._batch_size)
        processed = 0
        for job in jobs:
            if tracker.over_global_budget(self._daily_budget):
                logger.info("Knowledge backfill: budget hit mid-batch — stopping")
                break
            outcome = await self.process_job(job)
            if outcome is not None:
                processed += 1
        return processed

    async def process_job(self, job: dict) -> Optional[bool]:
        """Extract knowledge for one job under a lock.

        Returns ``True`` on success, ``False`` on a handled failure, and
        ``None`` when the job was skipped (lock lost to another worker, or no
        provider configured so it was requeued).
        """
        job_id = job["job_id"]
        store = get_job_store()

        if not store.acquire_knowledge_lock(job_id, self.worker_id, self._lock_ttl):
            return None  # lost the race — another worker owns it

        try:
            segments, source_url = resolve_segments_for_job(job_id, store)
            if not segments:
                logger.warning(
                    "Knowledge backfill: job %s has no segments — marking failed",
                    job_id,
                )
                store.release_knowledge_lock(job_id, status="failed")
                return False

            tracker = get_budget_tracker()
            downgrade = tracker.should_downgrade(self._downgrade_threshold)
            extractor = self._build_extractor(downgrade)
            if not extractor.provider:
                # Transient: provider may be configured later — requeue, don't fail.
                store.release_knowledge_lock(job_id, status="pending")
                return None
            if downgrade:
                tracker.note_downgrade()

            result = await extractor.extract_claims(
                episode_id=job_id, segments=segments, source_url=source_url
            )

            quarantine_failures(store, job_id, result)
            tracker.record(estimate_cost_usd(result.model, result.tokens_used))

            if not result.success:
                store.release_knowledge_lock(job_id, status="failed")
                return False

            persist_extraction_result(store, job_id, result)
            store.release_knowledge_lock(job_id, status="ready", bump_version=True)
            logger.info(
                "Knowledge backfill: job %s extracted %d claim(s)%s",
                job_id,
                len(result.claims),
                " (downgraded)" if downgrade else "",
            )
            return True
        except Exception as e:
            logger.error("Knowledge backfill: job %s errored: %s", job_id, e)
            try:
                store.release_knowledge_lock(job_id, status="failed")
            except Exception:
                pass
            return False


# ===== Module singleton + lifecycle hooks (mirrors scheduler.py) =====

_worker: Optional[KnowledgeBackfillWorker] = None


def get_backfill_worker() -> KnowledgeBackfillWorker:
    global _worker
    if _worker is None:
        _worker = KnowledgeBackfillWorker()
    return _worker


async def start_backfill_worker() -> None:
    await get_backfill_worker().start()


async def stop_backfill_worker() -> None:
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None
