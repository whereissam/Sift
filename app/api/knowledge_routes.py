"""API endpoints for the canonical knowledge layer (P18, Phase A).

Surface (mounted under /api):
  POST /api/jobs/{job_id}/extract-knowledge  -> trigger extraction (or re-extract)
  GET  /api/jobs/{job_id}/knowledge          -> fetch claims for an episode
  GET  /api/claims                           -> library-wide filtered claim query

The default `min_confidence` per surface is documented per-endpoint:
  - GET /jobs/{job_id}/knowledge -> 0.5
  - GET /api/claims              -> 0.5
The storage floor (0.1) is enforced inside the extractor; everything above
that is persisted, surfaces filter at query time.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.job_store import get_job_store
from ..core.knowledge_backfill import (
    get_backfill_worker,
    persist_extraction_result,
    quarantine_failures,
    resolve_segments_for_job,
)
from ..core.knowledge_budget import get_budget_tracker
from ..core.knowledge_extractor import KnowledgeExtractor
from ..core.knowledge_schema import ClaimType
from .auth import verify_api_key
from .ratelimit import limiter
from .schemas import JobStatus
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Knowledge"], dependencies=[Depends(verify_api_key)])

# ---------- Response models ----------


class ClaimResponse(BaseModel):
    claim_id: str
    episode_id: str
    text: str
    speaker: Optional[str] = None
    timestamp_start: float
    timestamp_end: float
    claim_type: ClaimType
    confidence: float
    evidence_excerpt: str
    entity_ids: list[str] = Field(default_factory=list)
    topic_ids: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    extraction_version: int
    schema_version: int
    created_at: Optional[str] = None


class JobKnowledgeResponse(BaseModel):
    job_id: str
    knowledge_status: str
    # Phase C.3 run-state for the on-demand path: ready | running | pending | none.
    # 'running'/'pending' come back with HTTP 202 so clients know to poll.
    run_state: str
    claim_count: int
    claims: list[ClaimResponse]


class EnqueueResponse(BaseModel):
    job_id: str
    enqueued: bool
    knowledge_status: str


class BackfillStatusResponse(BaseModel):
    counts: dict[str, int]
    pending: int
    spent_today_usd: float
    downgrades_today: int
    daily_budget_usd: Optional[float] = None
    downgrade_threshold_usd: Optional[float] = None


class ExtractKnowledgeResponse(BaseModel):
    job_id: str
    success: bool
    claim_count: int
    chunks_processed: int
    chunks_failed: int
    tokens_used: int
    model: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None


class ClaimsListResponse(BaseModel):
    claims: list[ClaimResponse]
    count: int


# ---------- Helpers ----------


def _row_to_claim_response(row: dict) -> ClaimResponse:
    # JobStore._claim_row_to_dict already deserialized entity_ids/topic_ids
    return ClaimResponse(
        claim_id=row["claim_id"],
        episode_id=row["episode_id"],
        text=row["text"],
        speaker=row.get("speaker"),
        timestamp_start=row["timestamp_start"],
        timestamp_end=row["timestamp_end"],
        claim_type=ClaimType(row["claim_type"]),
        confidence=row["confidence"],
        evidence_excerpt=row["evidence_excerpt"],
        entity_ids=row.get("entity_ids") or [],
        topic_ids=row.get("topic_ids") or [],
        source_url=row.get("source_url"),
        extraction_version=row["extraction_version"],
        schema_version=row["schema_version"],
        created_at=row.get("created_at"),
    )


def _segments_for_job(job_id: str) -> tuple[list[dict], Optional[str]]:
    """Pull (segments, source_url) from the in-memory transcription store.

    Returns ([], None) when the job doesn't exist or has no segments — the
    caller decides how to react (404 vs. empty result).
    """
    job = transcription_jobs.get(job_id)
    if not job or not job.segments:
        return [], None
    segments = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "speaker": s.speaker,
        }
        for s in job.segments
    ]
    return segments, job.source_url


# ---------- Endpoints ----------


@router.post(
    "/jobs/{job_id}/extract-knowledge", response_model=ExtractKnowledgeResponse
)
@limiter.limit("5/minute")
async def extract_knowledge(request: Request, job_id: str):
    """Run claims extraction over an episode and persist the results.

    Idempotent: re-running on the same episode upserts by claim_id, so the same
    claim isn't duplicated. Confidence below the storage floor (0.1) is dropped.
    """
    job = transcription_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {job.status.value})",
        )

    segments, source_url = _segments_for_job(job_id)
    if not segments:
        raise HTTPException(
            status_code=400,
            detail="Transcription has no segments — re-run with segment output.",
        )

    extractor = KnowledgeExtractor.from_settings()
    if not extractor.provider:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured for the `extract` task.",
        )

    job_store = get_job_store()
    job_store.set_knowledge_status(job_id, "extracting")

    result = await extractor.extract_claims(
        episode_id=job_id, segments=segments, source_url=source_url
    )

    # Always persist per-chunk failures to the quarantine table — useful for
    # both partial-success and total-failure runs to debug prompt drift.
    quarantine_failures(job_store, job_id, result)

    # Account spend so the synchronous path counts against the same daily
    # budget the backfill worker respects.
    from ..core.knowledge_budget import estimate_cost_usd

    get_budget_tracker().record(estimate_cost_usd(result.model, result.tokens_used))

    if not result.success:
        # Every chunk failed — do NOT overwrite existing claims with this
        # run's empty result. Mark the run failed and bail.
        job_store.set_knowledge_status(job_id, "failed")
        return ExtractKnowledgeResponse(
            job_id=job_id,
            success=False,
            claim_count=0,
            chunks_processed=result.chunks_processed,
            chunks_failed=result.chunks_failed,
            tokens_used=result.tokens_used,
            model=result.model,
            provider=result.provider,
            error=result.error,
        )

    # Atomically replace prior claims for this episode so re-extraction with
    # a new extraction_version reflects only the latest pass. claim_id is
    # stable so repeated runs at the same version don't churn. Single
    # transaction means a concurrent reader never sees a window of zero
    # claims and a crash mid-write doesn't lose them.
    #
    # Phase B: entities and mentions ride in the same transaction so a
    # partial write can never leave the episode with orphan mentions
    # pointing at vanished claims (or vice versa).
    #
    # Phase C.1: topics and claim_topic edges also ride in the same tx.
    # The join table (`claim_topics`) is the source of truth for claim↔
    # topic links; `claims.topic_ids` JSON is a denormalized cache that
    # the extractor already populated to match the edges — the store
    # writes both from the same dict, so they can't drift.
    #
    # Phase C.2: predictions (lifecycle rows for prediction-type claims)
    # also land in the same tx. Re-extraction refines the lifecycle
    # *input* fields (target_horizon/conditions/falsifiable_by) but
    # never overwrites operator-set resolution state — that contract
    # is enforced inside `_upsert_prediction_row`'s ON CONFLICT clause.
    #
    # The whole persist is factored into `persist_extraction_result` so the
    # synchronous route and the Phase C.3 backfill worker write byte-identical
    # transactions and can never drift.
    persist_extraction_result(job_store, job_id, result)
    job_store.set_knowledge_status(job_id, "complete")

    return ExtractKnowledgeResponse(
        job_id=job_id,
        success=True,
        claim_count=len(result.claims),
        chunks_processed=result.chunks_processed,
        chunks_failed=result.chunks_failed,
        tokens_used=result.tokens_used,
        model=result.model,
        provider=result.provider,
        error=result.error,
    )


# Map legacy synchronous-route status values onto the Phase C.3 run-state
# vocabulary so the on-demand response speaks one language.
_RUN_STATE_FROM_STATUS = {
    "complete": "ready",
    "ready": "ready",
    "extracting": "running",
    "running": "running",
    "pending": "pending",
    "failed": "failed",
    "none": "none",
}


def _knowledge_response(
    job_store, job_id: str, min_confidence: float
) -> JobKnowledgeResponse:
    status = job_store.get_knowledge_status(job_id) or "none"
    rows = job_store.get_claims_for_job(job_id, min_confidence=min_confidence)
    return JobKnowledgeResponse(
        job_id=job_id,
        knowledge_status=status,
        run_state=_RUN_STATE_FROM_STATUS.get(status, status),
        claim_count=len(rows),
        claims=[_row_to_claim_response(r) for r in rows],
    )


@router.get("/jobs/{job_id}/knowledge", response_model=JobKnowledgeResponse)
async def get_job_knowledge(
    response: Response,
    job_id: str,
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Filter floor (default 0.5)."
    ),
):
    """Return extracted claims for an episode — with on-demand backfill.

    Phase C.3 behavior:
      * ``ready``/``complete`` → return cached claims (HTTP 200).
      * ``running``/``extracting`` → in-progress; returns HTTP 202, poll again.
      * ``pending`` → run inline when the transcript is small enough
        (``knowledge_inline_max_segments``); otherwise enqueue for the
        background worker and return HTTP 202.
      * ``none`` → nothing queued; returns cached (typically empty) at 200.

    Default `min_confidence` is 0.5 (API surface threshold). Use 0.1 to see
    everything stored, 0.7+ for digest-grade precision.
    """
    job_store = get_job_store()
    status = job_store.get_knowledge_status(job_id) or "none"

    if status in ("running", "extracting"):
        response.status_code = 202
        return _knowledge_response(job_store, job_id, min_confidence)

    if status == "pending":
        segments, _ = resolve_segments_for_job(job_id, job_store)
        settings = get_settings()
        small_enough = 0 < len(segments) <= settings.knowledge_inline_max_segments
        provider_ready = KnowledgeExtractor.is_available()
        if small_enough and provider_ready:
            # Run inline through the worker so persistence + budget accounting
            # are identical to the background path. process_job handles its own
            # lock; a concurrent worker racing us simply loses the lock and the
            # other side wins — no double extraction.
            await get_backfill_worker().process_job(job_store.get_job(job_id))
        else:
            # Too big (or no provider yet) — leave it queued for the worker.
            response.status_code = 202

    return _knowledge_response(job_store, job_id, min_confidence)


@router.post("/jobs/{job_id}/knowledge/enqueue", response_model=EnqueueResponse)
async def enqueue_knowledge(job_id: str):
    """Idempotently queue a job for background knowledge extraction.

    No-op when the job is already pending/running/ready (returns
    ``enqueued=false``). Only ``none``/``failed`` jobs flip to ``pending``.
    """
    job_store = get_job_store()
    if job_store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    enqueued = job_store.enqueue_knowledge_job(job_id)
    return EnqueueResponse(
        job_id=job_id,
        enqueued=enqueued,
        knowledge_status=job_store.get_knowledge_status(job_id) or "none",
    )


@router.get("/knowledge/backfill-status", response_model=BackfillStatusResponse)
async def backfill_status():
    """Operational stats for the knowledge backfill pipeline.

    Status counts (legacy aliases folded in), today's estimated spend, and the
    number of model downgrades applied today.
    """
    job_store = get_job_store()
    settings = get_settings()
    tracker = get_budget_tracker()
    counts = job_store.get_knowledge_status_counts()
    return BackfillStatusResponse(
        counts=counts,
        pending=job_store.count_pending_knowledge_jobs(),
        spent_today_usd=round(tracker.spent_today(), 6),
        downgrades_today=tracker.downgrades_today(),
        daily_budget_usd=settings.knowledge_daily_budget_usd,
        downgrade_threshold_usd=settings.knowledge_model_downgrade_threshold_usd,
    )


@router.get("/claims", response_model=ClaimsListResponse)
async def list_claims(
    claim_type: Optional[ClaimType] = Query(default=None),
    speaker: Optional[str] = Query(default=None),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0),
    since: Optional[str] = Query(
        default=None, description="ISO 8601 timestamp; only return claims created at-or-after."
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Library-wide filtered claim query."""
    rows = get_job_store().query_claims(
        claim_type=claim_type.value if claim_type else None,
        speaker=speaker,
        min_confidence=min_confidence,
        since=since,
        limit=limit,
        offset=offset,
    )
    return ClaimsListResponse(
        claims=[_row_to_claim_response(r) for r in rows],
        count=len(rows),
    )
