"""Entity API surface (P18 Phase B).

Mounted under /api:
  GET /api/entities                   -> list/filter entities
  GET /api/entities/{id_or_slug}      -> read one entity (by entity_id or slug)
  GET /api/entities/{id_or_slug}/mentions  -> mentions for that entity

`id_or_slug` accepts either the stable hash-based `ent_<8>` PK or the
human-readable `type:kebab-name` slug. Slugs are mutable but the route
treats them as canonical pointers at read time — the merge path (when we
add it) will redirect a stale slug to the winner.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.job_store import get_job_store
from ..core.knowledge_schema import EntityType
from .auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Entities"], dependencies=[Depends(verify_api_key)])


# ---------- Response models ----------


class EntityResponse(BaseModel):
    entity_id: str
    slug: str
    name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    confidence: float
    created_at: Optional[str] = None


class EntityListResponse(BaseModel):
    entities: list[EntityResponse]
    count: int


class EntityMentionResponse(BaseModel):
    id: int
    entity_id: str
    episode_id: str
    claim_id: Optional[str] = None
    chunk_id: Optional[str] = None
    raw_text: str
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    timestamp: Optional[float] = None
    speaker: Optional[str] = None
    created_at: Optional[str] = None


class EntityMentionsResponse(BaseModel):
    entity_id: str
    mentions: list[EntityMentionResponse]
    count: int


# ---------- Helpers ----------


def _entity_to_response(row: dict) -> EntityResponse:
    return EntityResponse(
        entity_id=row["entity_id"],
        slug=row["slug"],
        name=row["name"],
        entity_type=EntityType(row["entity_type"]),
        aliases=row.get("aliases") or [],
        confidence=row.get("confidence", 1.0),
        created_at=row.get("created_at"),
    )


def _resolve_entity(id_or_slug: str) -> Optional[dict]:
    store = get_job_store()
    row = store.get_entity_by_id(id_or_slug)
    if row:
        return row
    return store.get_entity_by_slug(id_or_slug)


# ---------- Endpoints ----------


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    entity_type: Optional[EntityType] = Query(default=None),
    slug: Optional[str] = Query(default=None),
    since: Optional[str] = Query(
        default=None,
        description="ISO 8601 timestamp; only entities created at-or-after.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List canonical entities with optional filters."""
    rows = get_job_store().list_entities(
        entity_type=entity_type.value if entity_type else None,
        slug=slug,
        since=since,
        limit=limit,
        offset=offset,
    )
    return EntityListResponse(
        entities=[_entity_to_response(r) for r in rows],
        count=len(rows),
    )


@router.get("/entities/{id_or_slug}", response_model=EntityResponse)
async def get_entity(id_or_slug: str):
    """Read one entity by `entity_id` or `slug`."""
    row = _resolve_entity(id_or_slug)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _entity_to_response(row)


@router.get(
    "/entities/{id_or_slug}/mentions", response_model=EntityMentionsResponse
)
async def get_entity_mentions(
    id_or_slug: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List mentions of an entity across episodes."""
    row = _resolve_entity(id_or_slug)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity_id = row["entity_id"]
    rows = get_job_store().get_mentions_for_entity(
        entity_id, limit=limit, offset=offset
    )
    mentions = [EntityMentionResponse(**r) for r in rows]
    return EntityMentionsResponse(
        entity_id=entity_id, mentions=mentions, count=len(mentions)
    )
