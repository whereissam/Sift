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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..core.job_store import get_job_store
from ..core.knowledge_extractor import KnowledgeExtractor
from ..core.knowledge_schema import EXTRACTION_VERSION, ClaimType
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
    claim_count: int
    claims: list[ClaimResponse]


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
    for f in result.failures:
        job_store.record_extraction_failure(
            episode_id=job_id,
            chunk_index=f.chunk_index,
            error=f.error,
            raw_output=f.raw_output,
            extraction_version=EXTRACTION_VERSION,
            model=result.model,
        )

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
    claim_rows = [c.model_dump(mode="json") for c in result.claims]
    entity_rows = [e.model_dump(mode="json") for e in result.entities]
    mention_rows = [m.model_dump(mode="json") for m in result.mentions]
    job_store.replace_claims_for_job(
        job_id,
        claim_rows,
        entities=entity_rows,
        mentions=mention_rows,
    )
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


@router.get("/jobs/{job_id}/knowledge", response_model=JobKnowledgeResponse)
async def get_job_knowledge(
    job_id: str,
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Filter floor (default 0.5)."
    ),
):
    """Return all extracted claims for an episode.

    Default `min_confidence` is 0.5 (API surface threshold). Use 0.1 to see
    everything we stored, 0.7+ for digest-grade precision.
    """
    job_store = get_job_store()
    status = job_store.get_knowledge_status(job_id) or "none"
    rows = job_store.get_claims_for_job(job_id, min_confidence=min_confidence)
    return JobKnowledgeResponse(
        job_id=job_id,
        knowledge_status=status,
        claim_count=len(rows),
        claims=[_row_to_claim_response(r) for r in rows],
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
