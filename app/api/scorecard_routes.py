"""KOL scorecard: leaderboard + weekly digest (docs/kol-scorecard.md, step 3).

Mounted under /api:
  GET /api/scorecard/leaderboard   -> ranked KOLs (min. N resolved calls)
  GET /api/scorecard/digest        -> weekly digest as JSON {markdown, stats},
                                      or raw markdown with ?format=md

Only verified calls whose speaker is assigned to a KOL are ever included.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..knowledge.scorecard import MIN_RESOLVED, build_digest, build_leaderboard
from ..store import get_job_store
from .auth import verify_api_key

router = APIRouter(tags=["Scorecard"], dependencies=[Depends(verify_api_key)])


class KolScoreResponse(BaseModel):
    entity_id: str
    name: str
    handle: Optional[str] = None
    label: str
    resolved: int
    hits: int
    hit_rate: Optional[float] = None
    score: float
    bold_hits: int
    too_vague: int
    too_vague_rate: Optional[float] = None
    open_calls: int


class LeaderboardResponse(BaseModel):
    kols: list[KolScoreResponse]
    count: int
    min_resolved: int


class DigestResponse(BaseModel):
    markdown: str
    stats: dict


@router.get("/scorecard/leaderboard", response_model=LeaderboardResponse)
async def leaderboard(min_resolved: int = Query(default=MIN_RESOLVED, ge=1, le=100)):
    scores = build_leaderboard(get_job_store().list_scorecard_calls(), min_resolved=min_resolved)
    return LeaderboardResponse(
        kols=[s.to_dict() for s in scores], count=len(scores), min_resolved=min_resolved
    )


@router.get("/scorecard/digest", response_model=DigestResponse)
async def digest(
    start: Optional[date] = Query(default=None, description="First day (UTC). Default: 7 days before `end`."),
    end: Optional[date] = Query(default=None, description="Last day, inclusive (UTC). Default: today."),
    title: str = Query(default="Crypto Calls Weekly", max_length=120),
    min_resolved: int = Query(default=MIN_RESOLVED, ge=1, le=100),
    corrections_url: Optional[str] = Query(default=None, max_length=500),
    format: Literal["json", "md"] = Query(default="json"),
):
    last_day = end or datetime.now(timezone.utc).date()
    first_day = start or last_day - timedelta(days=6)
    if first_day > last_day:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    if corrections_url and not corrections_url.startswith(("https://", "http://", "mailto:")):
        raise HTTPException(status_code=422, detail="corrections_url must be an http(s) or mailto link")

    store = get_job_store()
    calls = store.list_scorecard_calls()
    contradictions = store.list_contradictions_between([c["claim_id"] for c in calls])
    markdown, stats = build_digest(
        calls,
        contradictions,
        start=datetime.combine(first_day, time.min, tzinfo=timezone.utc),
        end=datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=timezone.utc),
        title=title,
        min_resolved=min_resolved,
        corrections_url=corrections_url,
    )
    if format == "md":
        return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")
    return DigestResponse(markdown=markdown, stats=stats)
