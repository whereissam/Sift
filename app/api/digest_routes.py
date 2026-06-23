"""P20 digest pipeline API: configure digests, run them, read synthesis output.

A *digest* is a named set of subscriptions + window + cadence + optional webhook.
The background runner generates them on schedule; these routes let a user
configure them, trigger a run synchronously, and read the latest cross-episode
synthesis. Also exposes on-demand cross-source synthesis for a single topic.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..core.digest_runner import run_digest
from ..core.digest_synthesizer import DigestSynthesizer
from ..core.job_store import get_job_store
from ..core.knowledge_budget import estimate_cost_usd, get_budget_tracker
from .auth import verify_api_key
from .ratelimit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Digests"], dependencies=[Depends(verify_api_key)])


# ===== request / response models =====


class CreateDigestRequest(BaseModel):
    name: str = Field(..., description="Display name for the digest.")
    subscription_ids: list[str] = Field(
        ..., min_length=1, description="Subscriptions whose episodes feed the digest."
    )
    window_days: int = Field(7, ge=1, le=90)
    schedule_hours: int = Field(24, ge=1, le=720)
    min_confidence: float = Field(0.6, ge=0.0, le=1.0)
    webhook_url: Optional[str] = None
    enabled: bool = True


class UpdateDigestRequest(BaseModel):
    name: Optional[str] = None
    subscription_ids: Optional[list[str]] = None
    window_days: Optional[int] = Field(None, ge=1, le=90)
    schedule_hours: Optional[int] = Field(None, ge=1, le=720)
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    webhook_url: Optional[str] = None
    enabled: Optional[bool] = None


class DigestConfigResponse(BaseModel):
    digest_id: str
    name: str
    subscription_ids: list[str]
    window_days: int
    schedule_hours: int
    min_confidence: float
    webhook_url: Optional[str] = None
    enabled: bool
    last_run_at: Optional[str] = None
    created_at: str


class DigestRunResponse(BaseModel):
    run_id: str
    digest_id: str
    status: str
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    episode_count: int
    claim_count: int
    synthesis: Optional[dict] = None
    markdown: Optional[str] = None
    model: Optional[str] = None
    tokens_used: int
    error: Optional[str] = None
    created_at: str


class DigestDetailResponse(BaseModel):
    config: DigestConfigResponse
    latest_run: Optional[DigestRunResponse] = None


class TopicSynthesisResponse(BaseModel):
    topic_id: str
    name: str
    claim_count: int
    success: bool
    synthesis: Optional[dict] = None
    model: Optional[str] = None
    tokens_used: int = 0
    error: Optional[str] = None


def _config_response(cfg: dict) -> DigestConfigResponse:
    return DigestConfigResponse(**{k: cfg[k] for k in DigestConfigResponse.model_fields if k in cfg})


def _run_response(run: dict) -> DigestRunResponse:
    return DigestRunResponse(**{k: run[k] for k in DigestRunResponse.model_fields if k in run})


# ===== config CRUD =====


@router.post("/digests", response_model=DigestConfigResponse, status_code=201)
async def create_digest(body: CreateDigestRequest):
    """Create a digest configuration."""
    store = get_job_store()
    digest_id = f"dg_{uuid4().hex[:12]}"
    cfg = store.create_digest_config(
        digest_id,
        name=body.name,
        subscription_ids=body.subscription_ids,
        window_days=body.window_days,
        schedule_hours=body.schedule_hours,
        min_confidence=body.min_confidence,
        webhook_url=body.webhook_url,
        enabled=body.enabled,
    )
    return _config_response(cfg)


@router.get("/digests", response_model=list[DigestConfigResponse])
async def list_digests(enabled_only: bool = Query(False)):
    store = get_job_store()
    return [_config_response(c) for c in store.list_digest_configs(enabled_only=enabled_only)]


@router.get("/digests/{digest_id}", response_model=DigestDetailResponse)
async def get_digest(digest_id: str):
    """Get a digest config plus its most recent run."""
    store = get_job_store()
    cfg = store.get_digest_config(digest_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Digest not found")
    latest = store.get_latest_digest_run(digest_id)
    return DigestDetailResponse(
        config=_config_response(cfg),
        latest_run=_run_response(latest) if latest else None,
    )


@router.patch("/digests/{digest_id}", response_model=DigestConfigResponse)
async def update_digest(digest_id: str, body: UpdateDigestRequest):
    store = get_job_store()
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    cfg = store.update_digest_config(digest_id, **updates)
    if not cfg:
        raise HTTPException(status_code=404, detail="Digest not found")
    return _config_response(cfg)


@router.delete("/digests/{digest_id}")
async def delete_digest(digest_id: str):
    store = get_job_store()
    if not store.delete_digest_config(digest_id):
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"deleted": True, "digest_id": digest_id}


# ===== runs =====


@router.post("/digests/{digest_id}/run", response_model=DigestRunResponse)
@limiter.limit("10/minute")
async def run_digest_now(request: Request, digest_id: str):
    """Generate a digest synchronously and return the run (config's webhook, if
    any, is fired)."""
    store = get_job_store()
    cfg = store.get_digest_config(digest_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Digest not found")
    run = await run_digest(cfg)
    return _run_response(run)


@router.get("/digests/{digest_id}/runs", response_model=list[DigestRunResponse])
async def list_digest_runs(digest_id: str, limit: int = Query(20, ge=1, le=100)):
    store = get_job_store()
    if not store.get_digest_config(digest_id):
        raise HTTPException(status_code=404, detail="Digest not found")
    return [_run_response(r) for r in store.list_digest_runs(digest_id, limit=limit)]


# ===== on-demand topic synthesis =====


@router.get("/topics/{topic_id}/synthesis", response_model=TopicSynthesisResponse)
@limiter.limit("10/minute")
async def topic_synthesis(
    request: Request, topic_id: str, min_confidence: float = Query(0.6, ge=0.0, le=1.0)
):
    """Cross-source synthesis for a single topic across the whole library.

    Pulls the claims linked to the topic (the `claim_topics` join) and runs the
    same synthesis engine — agreements / disagreements / narratives across every
    episode that touched the topic. Not persisted; computed on demand.
    """
    store = get_job_store()
    topic = store.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    claims = [
        c
        for c in store.get_claims_for_topic(topic_id, limit=500)
        if (c.get("confidence") or 0.0) >= min_confidence
    ]
    result = await DigestSynthesizer.from_settings().synthesize(
        claims, window_label=f"topic: {topic['name']}"
    )
    if result.tokens_used:
        get_budget_tracker().record(estimate_cost_usd(result.model, result.tokens_used))

    return TopicSynthesisResponse(
        topic_id=topic_id,
        name=topic["name"],
        claim_count=len(claims),
        success=result.success,
        synthesis=result.synthesis.model_dump() if result.synthesis else None,
        model=result.model,
        tokens_used=result.tokens_used,
        error=result.error,
    )
