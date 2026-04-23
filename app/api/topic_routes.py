"""Topic API surface (P18 Phase C.1).

Mounted under /api:
  GET /api/topics                  -> list/filter topics
  GET /api/topics/{topic_id}       -> read one topic
  GET /api/topics/{topic_id}/claims -> claims linked to a topic

The join table (`claim_topics`) is the source of truth for claim↔topic
links. `claims.topic_ids` JSON is a denormalized cache for per-claim
render; `GET /api/topics/{id}/claims` always reads from the join so
reverse queries stay correct even if the cache ever drifts.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.job_store import get_job_store
from ..core.knowledge_schema import ClaimType
from .auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Topics"], dependencies=[Depends(verify_api_key)])


# ---------- Response models ----------


class TopicResponse(BaseModel):
    topic_id: str
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    confidence: float
    created_at: Optional[str] = None


class TopicListResponse(BaseModel):
    topics: list[TopicResponse]
    count: int


class TopicClaimResponse(BaseModel):
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


class TopicClaimsResponse(BaseModel):
    topic_id: str
    claims: list[TopicClaimResponse]
    count: int


# ---------- Helpers ----------


def _topic_to_response(row: dict) -> TopicResponse:
    return TopicResponse(
        topic_id=row["topic_id"],
        name=row["name"],
        description=row.get("description") or "",
        aliases=row.get("aliases") or [],
        confidence=row.get("confidence", 1.0),
        created_at=row.get("created_at"),
    )


def _claim_row_to_response(row: dict) -> TopicClaimResponse:
    return TopicClaimResponse(
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
    )


# ---------- Endpoints ----------


@router.get("/topics", response_model=TopicListResponse)
async def list_topics(
    since: Optional[str] = Query(
        default=None,
        description="ISO 8601 timestamp; only topics created at-or-after.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List canonical topics, most recent first."""
    rows = get_job_store().list_topics(since=since, limit=limit, offset=offset)
    return TopicListResponse(
        topics=[_topic_to_response(r) for r in rows], count=len(rows)
    )


@router.get("/topics/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: str):
    """Read one topic by stable `top_<hash>` ID."""
    row = get_job_store().get_topic_by_id(topic_id)
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")
    return _topic_to_response(row)


@router.get("/topics/{topic_id}/claims", response_model=TopicClaimsResponse)
async def get_topic_claims(
    topic_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Return claims linked to a topic via the join table.

    Reads from `claim_topics` (source of truth) and joins back to the
    full claim row so callers don't need to chain two queries.
    """
    store = get_job_store()
    if not store.get_topic_by_id(topic_id):
        raise HTTPException(status_code=404, detail="Topic not found")
    rows = store.get_claims_for_topic(topic_id, limit=limit, offset=offset)
    return TopicClaimsResponse(
        topic_id=topic_id,
        claims=[_claim_row_to_response(r) for r in rows],
        count=len(rows),
    )
