"""KOL + speaker-mapping API for the prediction scorecard (docs/kol-scorecard.md).

Mounted under /api:
  GET    /api/kols                                   -> KOLs with their handles
  POST   /api/kols                                   -> create a KOL / add handles
  DELETE /api/kols/{entity_id}/handles/{platform}/{handle}
  GET    /api/episodes/{episode_id}/speakers         -> speaker labels + assigned KOL
  PUT    /api/episodes/{episode_id}/speakers/{speaker}
  DELETE /api/episodes/{episode_id}/speakers/{speaker}

A prediction can only be marked `verified` once its speaker label is
assigned to a KOL here (see `POST /api/predictions/{claim_id}/review`).
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..knowledge.knowledge_schema import EntityType, compute_entity_id, slugify_entity_name
from ..store import get_job_store
from ..store._kols import HandleTakenError
from .auth import verify_api_key

router = APIRouter(tags=["KOLs"], dependencies=[Depends(verify_api_key)])

Platform = Literal["x", "youtube", "podcast"]


class Handle(BaseModel):
    platform: Platform
    handle: str = Field(min_length=1, max_length=300)


class KolResponse(BaseModel):
    entity_id: str
    slug: str
    name: str
    aliases: list[str] = []
    handles: list[Handle] = []


class KolListResponse(BaseModel):
    kols: list[KolResponse]
    count: int


class CreateKolBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    handles: list[Handle] = []


class EpisodeSpeaker(BaseModel):
    speaker: str
    claim_count: int
    entity_id: Optional[str] = None
    kol_name: Optional[str] = None
    confirmed_by: Optional[str] = None


class EpisodeSpeakersResponse(BaseModel):
    episode_id: str
    speakers: list[EpisodeSpeaker]


class AssignSpeakerBody(BaseModel):
    entity_id: str
    confirmed_by: Optional[str] = Field(
        default=None, description="Who made the assignment (user or agent id)."
    )


@router.get("/kols", response_model=KolListResponse)
async def list_kols():
    kols = get_job_store().list_kols()
    return KolListResponse(kols=kols, count=len(kols))


@router.post("/kols", response_model=KolResponse)
async def create_kol(body: CreateKolBody):
    """Create a KOL, or add handles to the existing person with this name."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be blank")
    try:
        return get_job_store().upsert_kol(
            entity_id=compute_entity_id(name=name, entity_type=EntityType.PERSON),
            name=name,
            slug=f"{EntityType.PERSON.value}:{slugify_entity_name(name)}",
            handles=[(h.platform, h.handle) for h in body.handles],
        )
    except HandleTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/kols/{entity_id}/handles/{platform}/{handle}", status_code=204)
async def remove_kol_handle(entity_id: str, platform: Platform, handle: str):
    if not get_job_store().remove_kol_handle(entity_id, platform, handle):
        raise HTTPException(status_code=404, detail="Handle not found for this KOL")


@router.get("/episodes/{episode_id}/speakers", response_model=EpisodeSpeakersResponse)
async def list_episode_speakers(episode_id: str):
    return EpisodeSpeakersResponse(
        episode_id=episode_id,
        speakers=get_job_store().list_episode_speakers(episode_id),
    )


@router.put("/episodes/{episode_id}/speakers/{speaker}", response_model=EpisodeSpeaker)
async def assign_episode_speaker(episode_id: str, speaker: str, body: AssignSpeakerBody):
    store = get_job_store()
    if not store.get_kol(body.entity_id):
        raise HTTPException(status_code=404, detail="KOL not found")
    current = {s["speaker"]: s for s in store.list_episode_speakers(episode_id)}
    if speaker not in current:
        raise HTTPException(
            status_code=404, detail=f"No claims by speaker {speaker!r} in this episode"
        )
    store.set_episode_speaker(episode_id, speaker, body.entity_id, confirmed_by=body.confirmed_by)
    updated = {s["speaker"]: s for s in store.list_episode_speakers(episode_id)}
    return updated[speaker]


@router.delete("/episodes/{episode_id}/speakers/{speaker}", status_code=204)
async def clear_episode_speaker(episode_id: str, speaker: str):
    if not get_job_store().clear_episode_speaker(episode_id, speaker):
        raise HTTPException(status_code=404, detail="Speaker is not assigned")
