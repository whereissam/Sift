"""Prediction API surface (P18 Phase C.2).

Mounted under /api:
  GET    /api/predictions                       -> list predictions (filter by resolution/since)
  GET    /api/predictions/{claim_id}            -> read one prediction
  POST   /api/predictions/{claim_id}/resolve    -> set resolution (true/false/unresolvable)
  DELETE /api/predictions/{claim_id}/resolve    -> revert to pending

Predictions are stored in their own table keyed by `claim_id` (FK to
claims). The `/resolve` endpoints are operator-driven; re-extraction
of the underlying episode never overwrites resolution state — see
`JobStore._upsert_prediction_row` for the corresponding ON CONFLICT
discipline on the storage side.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.job_store import get_job_store
from ..core.knowledge_schema import Resolution
from .auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Predictions"], dependencies=[Depends(verify_api_key)])


# ---------- Response models ----------


class PredictionResponse(BaseModel):
    claim_id: str
    target_horizon: Optional[str] = None
    conditions: Optional[str] = None
    falsifiable_by: Optional[str] = None
    resolution: Resolution
    resolution_note: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
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


# ---------- Helpers ----------


def _row_to_response(row: dict) -> PredictionResponse:
    return PredictionResponse(
        claim_id=row["claim_id"],
        target_horizon=row.get("target_horizon"),
        conditions=row.get("conditions"),
        falsifiable_by=row.get("falsifiable_by"),
        resolution=Resolution(row.get("resolution") or "pending"),
        resolution_note=row.get("resolution_note"),
        resolved_at=row.get("resolved_at"),
        resolved_by=row.get("resolved_by"),
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
    rows = get_job_store().list_predictions(
        resolution=resolution.value if resolution else None,
        since=since,
        limit=limit,
        offset=offset,
    )
    return PredictionListResponse(
        predictions=[_row_to_response(r) for r in rows],
        count=len(rows),
    )


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
