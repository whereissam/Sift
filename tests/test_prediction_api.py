"""Tests for app/api/prediction_routes.py (P18 Phase C.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.prediction_routes import router as prediction_router
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)


def _seed_prediction_claim(
    store: JobStore,
    *,
    text: str = "BTC will hit 200k",
    timestamp_start: float = 1.0,
) -> str:
    claim = Claim(
        claim_id=compute_claim_id(
            text=text,
            episode_id="ep-1",
            speaker=None,
            timestamp_start=timestamp_start,
        ),
        episode_id="ep-1",
        text=text,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_start + 1.0,
        claim_type=ClaimType.PREDICTION,
        confidence=0.9,
        evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    store.replace_claims_for_job("ep-1", [claim.model_dump(mode="json")])
    return claim.claim_id


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = JobStore(db_path=tmp_path / "predictions_api.db")
    monkeypatch.setattr(job_store_module, "_job_store", store)

    cid_pending = _seed_prediction_claim(store, text="A", timestamp_start=1.0)
    cid_resolved = _seed_prediction_claim(store, text="B", timestamp_start=2.0)
    # Re-extract appended a claim — but replace_claims_for_job cleared
    # the first one. Re-seed both in a single call so they coexist.
    claim_a = Claim(
        claim_id=cid_pending,
        episode_id="ep-1",
        text="A",
        timestamp_start=1.0,
        timestamp_end=2.0,
        claim_type=ClaimType.PREDICTION,
        confidence=0.9,
        evidence_excerpt="A",
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    claim_b = Claim(
        claim_id=cid_resolved,
        episode_id="ep-1",
        text="B",
        timestamp_start=2.0,
        timestamp_end=3.0,
        claim_type=ClaimType.PREDICTION,
        confidence=0.9,
        evidence_excerpt="B",
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    store.replace_claims_for_job(
        "ep-1",
        [claim_a.model_dump(mode="json"), claim_b.model_dump(mode="json")],
    )

    store.upsert_prediction(
        {
            "claim_id": cid_pending,
            "target_horizon": "next quarter",
            "falsifiable_by": "spot price > $5k",
        }
    )
    store.upsert_prediction(
        {
            "claim_id": cid_resolved,
            "target_horizon": "end of year",
        }
    )
    store.resolve_prediction(
        cid_resolved,
        resolution="true",
        note="confirmed via news",
        resolved_by="user-1",
    )

    app = FastAPI()
    app.include_router(prediction_router, prefix="/api")
    yield TestClient(app), cid_pending, cid_resolved


class TestList:
    def test_lists_all_predictions(self, client):
        c, _, _ = client
        r = c.get("/api/predictions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2

    def test_filter_by_resolution_pending(self, client):
        c, cid_pending, _ = client
        r = c.get("/api/predictions", params={"resolution": "pending"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["predictions"][0]["claim_id"] == cid_pending

    def test_filter_by_resolution_true(self, client):
        c, _, cid_resolved = client
        r = c.get("/api/predictions", params={"resolution": "true"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["predictions"][0]["claim_id"] == cid_resolved
        assert body["predictions"][0]["resolution_note"] == "confirmed via news"


class TestGet:
    def test_by_claim_id(self, client):
        c, cid_pending, _ = client
        r = c.get(f"/api/predictions/{cid_pending}")
        assert r.status_code == 200
        body = r.json()
        assert body["target_horizon"] == "next quarter"
        assert body["resolution"] == "pending"

    def test_unknown_returns_404(self, client):
        c, _, _ = client
        r = c.get("/api/predictions/nope")
        assert r.status_code == 404


class TestResolve:
    def test_resolve_records_metadata(self, client):
        c, cid_pending, _ = client
        r = c.post(
            f"/api/predictions/{cid_pending}/resolve",
            json={
                "resolution": "false",
                "note": "did not happen",
                "resolved_by": "user-2",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "false"
        assert body["resolution_note"] == "did not happen"
        assert body["resolved_by"] == "user-2"
        assert body["resolved_at"] is not None

    def test_resolve_pending_via_post_rejected(self, client):
        c, cid_pending, _ = client
        # POST with resolution=pending is a footgun — operators end up
        # accidentally clearing resolution metadata. Force them through
        # the DELETE endpoint.
        r = c.post(
            f"/api/predictions/{cid_pending}/resolve",
            json={"resolution": "pending"},
        )
        assert r.status_code == 400

    def test_resolve_unknown_returns_404(self, client):
        c, _, _ = client
        r = c.post(
            "/api/predictions/nope/resolve",
            json={"resolution": "true"},
        )
        assert r.status_code == 404


class TestRevert:
    def test_delete_reverts_to_pending(self, client):
        c, _, cid_resolved = client
        r = c.delete(f"/api/predictions/{cid_resolved}/resolve")
        assert r.status_code == 200
        body = r.json()
        assert body["resolution"] == "pending"
        # Reverting wipes resolution metadata — clean slate for a re-resolve.
        assert body["resolution_note"] is None
        assert body["resolved_at"] is None
        assert body["resolved_by"] is None

    def test_delete_unknown_returns_404(self, client):
        c, _, _ = client
        r = c.delete("/api/predictions/nope/resolve")
        assert r.status_code == 404
