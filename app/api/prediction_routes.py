"""Prediction API surface (P18 Phase C.2).

Mounted under /api:
  GET    /api/predictions                       -> list predictions (filter by resolution/since)
  GET    /api/predictions/{claim_id}            -> read one prediction
  POST   /api/predictions/{claim_id}/resolve    -> set resolution (true/false/unresolvable)
  DELETE /api/predictions/{claim_id}/resolve    -> revert to pending
  GET    /api/predictions/review-queue          -> predictions awaiting human review
  POST   /api/predictions/{claim_id}/review     -> verify / reject / back to unreviewed
  PUT    /api/predictions/{claim_id}/target     -> set the price target by hand
  DELETE /api/predictions/{claim_id}/target     -> remove the price target
  PUT    /api/predictions/{claim_id}/due        -> set / clear the due date by hand
  POST   /api/predictions/check                 -> parse + price-check now (see prediction_checker)

Predictions are stored in their own table keyed by `claim_id` (FK to
claims). The `/resolve` endpoints are operator-driven; re-extraction
of the underlying episode never overwrites resolution state — see
`JobStore._upsert_prediction_row` for the corresponding ON CONFLICT
discipline on the storage side.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..store import get_job_store
from datetime import date

from ..knowledge.knowledge_schema import Resolution
from ..knowledge.prediction_checker import PredictionChecker
from ..knowledge.prediction_targets import coin_id_for
from .auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Predictions"], dependencies=[Depends(verify_api_key)])


# ---------- Response models ----------

# Human review of a prediction's quote + speaker before it is published
# (KOL scorecard). Separate from `resolution`: review asks "did they say
# this?", resolution asks "were they right?".
ReviewStatus = Literal["unreviewed", "verified", "rejected"]


class TargetResponse(BaseModel):
    asset: str
    coin_id: str
    metric: str = "price"
    comparator: Literal[">=", "<="]
    value: float
    baseline: Optional[float] = None
    evidence: Optional[dict] = None
    source: Literal["parsed", "manual"]


class PredictionResponse(BaseModel):
    claim_id: str
    target_horizon: Optional[str] = None
    conditions: Optional[str] = None
    falsifiable_by: Optional[str] = None
    resolution: Resolution
    resolution_note: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    review_status: ReviewStatus = "unreviewed"
    review_note: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    due_at: Optional[str] = None
    due_source: Optional[Literal["parsed", "manual"]] = None
    target: Optional[TargetResponse] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PredictionListResponse(BaseModel):
    predictions: list[PredictionResponse]
    count: int


class ResolvePredictionBody(BaseModel):
    resolution: Resolution = Field(
        description="New lifecycle state. Use the DELETE endpoint to revert to pending instead."
    )
    note: Optional[str] = Field(
        default=None, description="Operator note attached to the resolution."
    )
    resolved_by: Optional[str] = Field(
        default=None,
        description="Identifier of the user/agent recording the resolution.",
    )


class ReviewQueueItem(PredictionResponse):
    episode_id: str
    episode_title: Optional[str] = None
    source_url: Optional[str] = None
    text: str
    evidence_excerpt: Optional[str] = None
    speaker: Optional[str] = None
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None
    confidence: Optional[float] = None
    kol_entity_id: Optional[str] = Field(
        default=None, description="KOL behind the speaker label; null until assigned."
    )
    kol_name: Optional[str] = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    count: int


class ReviewPredictionBody(BaseModel):
    status: ReviewStatus
    note: Optional[str] = Field(default=None, description="Why it was rejected, etc.")
    reviewed_by: Optional[str] = None


class SetTargetBody(BaseModel):
    asset: str = Field(description="Ticker, e.g. BTC, ETH, SOL.")
    comparator: Literal[">=", "<="] = ">="
    value: float = Field(gt=0, description="USD price.")


class SetDueBody(BaseModel):
    due_at: Optional[date] = Field(description="Last day the call can come true; null clears it.")


class CheckSummaryResponse(BaseModel):
    due_dates_parsed: int
    targets_parsed: int
    checked: int
    resolved_true: int
    resolved_false: int
    already_met: int = Field(
        description="Verified calls whose target was already met when made; left for review."
    )
    errors: list[str]


# ---------- Helpers ----------


def _row_to_response(row: dict, targets: Optional[dict] = None) -> PredictionResponse:
    """`targets` is a batch from get_prediction_targets; without it the
    target is looked up for this one row."""
    if targets is None:
        target = get_job_store().get_prediction_target(row["claim_id"])
    else:
        target = targets.get(row["claim_id"])
    return PredictionResponse(
        claim_id=row["claim_id"],
        target_horizon=row.get("target_horizon"),
        conditions=row.get("conditions"),
        falsifiable_by=row.get("falsifiable_by"),
        resolution=Resolution(row.get("resolution") or "pending"),
        resolution_note=row.get("resolution_note"),
        resolved_at=row.get("resolved_at"),
        resolved_by=row.get("resolved_by"),
        review_status=row.get("review_status") or "unreviewed",
        review_note=row.get("review_note"),
        reviewed_at=row.get("reviewed_at"),
        reviewed_by=row.get("reviewed_by"),
        due_at=row.get("due_at"),
        due_source=row.get("due_source"),
        target=target,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ---------- Endpoints ----------


@router.get("/predictions", response_model=PredictionListResponse)
async def list_predictions(
    resolution: Optional[Resolution] = Query(
        default=None,
        description="Filter by lifecycle state (pending/true/false/unresolvable).",
    ),
    since: Optional[str] = Query(
        default=None,
        description="ISO 8601 timestamp; only predictions created at-or-after.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List predictions, most recent first."""
    store = get_job_store()
    rows = store.list_predictions(
        resolution=resolution.value if resolution else None,
        since=since,
        limit=limit,
        offset=offset,
    )
    targets = store.get_prediction_targets([r["claim_id"] for r in rows])
    return PredictionListResponse(
        predictions=[_row_to_response(r, targets) for r in rows],
        count=len(rows),
    )


# Declared before /predictions/{claim_id} so the path param can't swallow it.
@router.get("/predictions/review-queue", response_model=ReviewQueueResponse)
async def review_queue(
    status: ReviewStatus = Query(default="unreviewed"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Predictions with their quote, speaker and source, oldest first."""
    store = get_job_store()
    rows = store.list_review_queue(status=status, limit=limit, offset=offset)
    targets = store.get_prediction_targets([r["claim_id"] for r in rows])
    items = [
        ReviewQueueItem(**_row_to_response(r, targets).model_dump(), **{
            k: r.get(k) for k in (
                "episode_id", "episode_title", "source_url", "text", "evidence_excerpt",
                "speaker", "timestamp_start", "timestamp_end", "confidence",
                "kol_entity_id", "kol_name",
            )
        })
        for r in rows
    ]
    return ReviewQueueResponse(items=items, count=len(items))


@router.post("/predictions/{claim_id}/review", response_model=PredictionResponse)
async def review_prediction(claim_id: str, body: ReviewPredictionBody):
    """Record whether the quote and speaker attribution are correct.

    `verified` requires the claim's speaker label to be assigned to a KOL
    first (PUT /episodes/{episode_id}/speakers/{speaker}): a verified call
    is one we are willing to publish under someone's name.
    """
    store = get_job_store()
    if not store.get_prediction_by_claim_id(claim_id):
        raise HTTPException(status_code=404, detail="Prediction not found")
    if body.status == "verified":
        claim = store.get_claim(claim_id)
        if not claim or not store.get_speaker_kol(claim["episode_id"], claim.get("speaker")):
            raise HTTPException(
                status_code=409,
                detail="Assign this claim's speaker to a KOL before verifying it.",
            )
    updated = store.set_prediction_review(
        claim_id, status=body.status, note=body.note, reviewed_by=body.reviewed_by
    )
    return _row_to_response(updated)


@router.post("/predictions/check", response_model=CheckSummaryResponse)
async def check_predictions():
    """Parse due dates / price targets and price-check verified calls now.

    The background checker does the same every `prediction_checker_interval`
    seconds; this is for "I just verified a batch, resolve what you can".
    """
    summary = await PredictionChecker().run()
    return CheckSummaryResponse(**summary.__dict__)


@router.put("/predictions/{claim_id}/target", response_model=PredictionResponse)
async def set_prediction_target(claim_id: str, body: SetTargetBody):
    """Set the price target by hand. A manual target is never replaced by
    the parser."""
    store = get_job_store()
    row = store.get_prediction_by_claim_id(claim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prediction not found")
    coin_id = coin_id_for(body.asset)
    if not coin_id:
        raise HTTPException(status_code=422, detail=f"Unknown asset {body.asset!r}")
    store.set_prediction_target(
        claim_id, asset=body.asset.strip().upper(), coin_id=coin_id,
        comparator=body.comparator, value=body.value, source="manual",
    )
    return _row_to_response(row)


@router.delete("/predictions/{claim_id}/target", status_code=204)
async def clear_prediction_target(claim_id: str):
    """Remove the target. The parser may set a new one on its next run
    unless a manual target is set instead."""
    if not get_job_store().clear_prediction_target(claim_id):
        raise HTTPException(status_code=404, detail="No target for this prediction")


@router.put("/predictions/{claim_id}/due", response_model=PredictionResponse)
async def set_prediction_due(claim_id: str, body: SetDueBody):
    store = get_job_store()
    due = body.due_at.isoformat() if body.due_at else None
    if not store.set_prediction_due(claim_id, due, source="manual"):
        raise HTTPException(status_code=404, detail="Prediction not found")
    return _row_to_response(store.get_prediction_by_claim_id(claim_id))


@router.get("/predictions/{claim_id}", response_model=PredictionResponse)
async def get_prediction(claim_id: str):
    """Read one prediction by `claim_id`."""
    row = get_job_store().get_prediction_by_claim_id(claim_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return _row_to_response(row)


@router.post(
    "/predictions/{claim_id}/resolve", response_model=PredictionResponse
)
async def resolve_prediction(claim_id: str, body: ResolvePredictionBody):
    """Set the lifecycle resolution on a prediction.

    Use `Resolution.UNRESOLVABLE` for predictions that became
    unresolvable (event cancelled, conditions never met, too vague to
    falsify) — distinct from `pending` so accuracy dashboards can drop
    them instead of treating them as still-open. To revert to pending
    use the DELETE endpoint.
    """
    if body.resolution == Resolution.PENDING:
        # Reverting via POST is a footgun — operators end up clearing
        # resolution metadata they didn't mean to. Force them through
        # the DELETE endpoint, which exists for exactly this.
        raise HTTPException(
            status_code=400,
            detail="Use DELETE /predictions/{claim_id}/resolve to revert to pending.",
        )
    updated = get_job_store().resolve_prediction(
        claim_id,
        resolution=body.resolution.value,
        note=body.note,
        resolved_by=body.resolved_by,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return _row_to_response(updated)


@router.delete(
    "/predictions/{claim_id}/resolve", response_model=PredictionResponse
)
async def revert_prediction(claim_id: str):
    """Revert a prediction back to `pending`, clearing resolution metadata."""
    updated = get_job_store().resolve_prediction(
        claim_id, resolution="pending"
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return _row_to_response(updated)
