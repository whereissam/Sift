"""/v1 ingestion API (migration Slice 3).

Unified async ingestion: submit a source with an outputs list, poll the
job, address results by asset. Legacy /api endpoints stay untouched;
this router is additive and versioned.
"""

import hashlib
import json
import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sift_core.asset_identity import canonical_source_for_job
from sift_core.fetch.downloader import DownloaderFactory
from ..pipeline.ingestion_service import (
    find_cached_transcript,
    run_ingestion_job,
)
from ..store import JobStatus as StoreStatus, JobType, get_job_store
from .auth import verify_api_key
from .ratelimit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["ingestion"], dependencies=[Depends(verify_api_key)])

# Single-key auth today; per-key principals arrive with Slice 4.
_PRINCIPAL = "default"
_ENDPOINT = "POST /v1/ingestions"

_STAGE_BY_STATUS = {
    StoreStatus.PENDING.value: "queued",
    StoreStatus.DOWNLOADING.value: "downloading",
    StoreStatus.CONVERTING.value: "converting",
    StoreStatus.TRANSCRIBING.value: "transcribing",
    StoreStatus.COMPLETED.value: "completed",
    StoreStatus.FAILED.value: "failed",
}


class IngestionSource(BaseModel):
    type: Literal["url"] = "url"
    url: str = Field(..., max_length=2048)


class IngestionProcessing(BaseModel):
    language: Optional[str] = Field(default=None, description="ISO code or None for auto")
    diarization: bool = False
    model: str = Field(default="base", description="Whisper model size")


class IngestionRequest(BaseModel):
    source: IngestionSource
    outputs: list[Literal["media", "transcript", "speakers", "claims"]] = Field(
        default=["transcript"], min_length=1
    )
    processing: IngestionProcessing = Field(default_factory=IngestionProcessing)


class IngestionAccepted(BaseModel):
    job_id: str
    status: str
    asset_id: Optional[str] = None
    cached: bool = False


def _request_hash(body: IngestionRequest) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _accepted_payload(job: dict, cached: bool) -> dict:
    return IngestionAccepted(
        job_id=job["job_id"],
        status=_STAGE_BY_STATUS.get(job["status"], job["status"]),
        asset_id=job.get("asset_id"),
        cached=cached,
    ).model_dump()


@router.post("/ingestions", status_code=202, response_model=IngestionAccepted)
@limiter.limit("10/minute")
async def create_ingestion(
    request: Request,
    body: IngestionRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Submit a source for ingestion. Returns 202 with a job to poll;
    returns the cached result immediately when the asset already has a
    satisfying transcript artifact."""
    url = body.source.url
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are supported")
    if not DownloaderFactory.detect_platform(url):
        raise HTTPException(status_code=400, detail="Unsupported source URL")

    store = get_job_store()
    request_hash = _request_hash(body)

    if idempotency_key:
        existing = store.get_idempotency_record(_PRINCIPAL, _ENDPOINT, idempotency_key)
        if existing:
            if existing["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different request body",
                )
            job = store.get_job(existing["job_id"])
            if job:
                # Replay: same key, same body → the original submission.
                return JSONResponse(status_code=200, content=_accepted_payload(job, cached=True))

    outputs = list(dict.fromkeys(body.outputs))  # dedupe, preserve order
    want_transcript = "transcript" in outputs or "speakers" in outputs
    job_id = str(uuid.uuid4())

    job = store.create_job(
        job_id,
        JobType.TRANSCRIBE if want_transcript else JobType.DOWNLOAD,
        source_url=url,
        model_size=body.processing.model if want_transcript else None,
        language=body.processing.language,
        transcription_format="json" if want_transcript else None,
        output_format=None if want_transcript else "m4a",
        requested_outputs=outputs
        + (["speakers"] if body.processing.diarization and "speakers" not in outputs else []),
    )

    if idempotency_key:
        store.record_idempotency_key(
            _PRINCIPAL, _ENDPOINT, idempotency_key, request_hash, job_id
        )

    # Cache hit: the canonical source already has a satisfying transcript.
    source = canonical_source_for_job(url)
    cached_asset = find_cached_transcript(store, source, job["requested_outputs"] or outputs)
    if cached_asset:
        job = store.set_status(job_id, StoreStatus.COMPLETED)
        return JSONResponse(status_code=200, content=_accepted_payload(job, cached=True))

    background_tasks.add_task(run_ingestion_job, job_id)
    return _accepted_payload(job, cached=False)


@router.get("/ingestions/{job_id}")
async def get_ingestion(job_id: str):
    """Ingestion job status with stage-based progress in media seconds."""
    store = get_job_store()
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    stage = _STAGE_BY_STATUS.get(job["status"], job["status"])
    # Knowledge extraction runs after transcription completes; surface it
    # as its own stage while it's active.
    if stage == "completed" and job.get("knowledge_status") == "running":
        stage = "extracting"

    duration = None
    content_info = job.get("content_info")
    if isinstance(content_info, dict):
        duration = content_info.get("duration_seconds")
    if duration is None:
        blob = job.get("transcription_result")
        if isinstance(blob, dict):
            duration = blob.get("duration_seconds")

    fraction = job.get("progress") or 0.0
    if duration:
        progress = {
            "completed": round(fraction * duration),
            "total": round(duration),
            "unit": "media_seconds",
        }
    else:
        progress = {"completed": fraction, "total": 1.0, "unit": "fraction"}

    return {
        "job_id": job["job_id"],
        "status": _STAGE_BY_STATUS.get(job["status"], job["status"]),
        "stage": stage,
        "progress": progress,
        "asset_id": job.get("asset_id"),
        "requested_outputs": job.get("requested_outputs"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str):
    """Asset with its latest transcript artifact summary."""
    store = get_job_store()
    asset = store.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    latest = store.get_latest_transcript_artifact(asset_id)
    if latest:
        latest = {
            **latest,
            "segment_count": len(store.get_transcript_segments(latest["artifact_id"])),
        }
    return {
        **asset,
        "latest_transcript_artifact": latest,
        "job_count": len(store.get_asset_jobs(asset_id)),
    }


@router.get("/assets/{asset_id}/artifacts")
async def list_asset_artifacts(asset_id: str):
    """All transcript artifacts for an asset, oldest first."""
    store = get_job_store()
    if not store.get_asset(asset_id):
        raise HTTPException(status_code=404, detail="Asset not found")
    artifacts = store.get_transcript_artifacts(asset_id)
    return {
        "asset_id": asset_id,
        "artifacts": [
            {
                **a,
                "segment_count": len(store.get_transcript_segments(a["artifact_id"])),
            }
            for a in artifacts
        ],
    }
