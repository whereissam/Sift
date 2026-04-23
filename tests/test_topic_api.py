"""Tests for app/api/topic_routes.py (P18 Phase C.1)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.topic_routes import router as topic_router
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = JobStore(db_path=tmp_path / "topics_api.db")
    monkeypatch.setattr(job_store_module, "_job_store", store)

    now = datetime.utcnow().isoformat()
    store.upsert_topic(
        {
            "topic_id": "top_aaaaaaaa",
            "name": "Bitcoin Price",
            "description": "Bitcoin spot price trends",
            "aliases": ["BTC price"],
            "confidence": 0.9,
            "created_at": now,
        }
    )
    store.upsert_topic(
        {
            "topic_id": "top_bbbbbbbb",
            "name": "AI Safety",
            "description": "Discussions about AI alignment risks",
            "aliases": [],
            "confidence": 0.85,
            "created_at": now,
        }
    )

    # Seed a claim and a join-table edge so the /claims endpoint has data
    claim = Claim(
        claim_id=compute_claim_id(
            text="BTC broke 100k",
            episode_id="ep-1",
            speaker=None,
            timestamp_start=1.0,
        ),
        episode_id="ep-1",
        text="BTC broke 100k",
        timestamp_start=1.0,
        timestamp_end=2.0,
        claim_type=ClaimType.FACT,
        confidence=0.9,
        evidence_excerpt="BTC broke 100k",
        topic_ids=["top_aaaaaaaa"],
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    store.replace_claims_for_job(
        "ep-1",
        [claim.model_dump(mode="json")],
        claim_topic_edges=[
            {
                "claim_id": claim.claim_id,
                "topic_id": "top_aaaaaaaa",
                "confidence": 0.9,
            }
        ],
    )

    app = FastAPI()
    app.include_router(topic_router, prefix="/api")
    yield TestClient(app)


class TestList:
    def test_lists_all_topics(self, client: TestClient):
        r = client.get("/api/topics")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert {t["name"] for t in body["topics"]} == {
            "Bitcoin Price",
            "AI Safety",
        }

    def test_limit_works(self, client: TestClient):
        r = client.get("/api/topics", params={"limit": 1})
        assert r.status_code == 200
        assert len(r.json()["topics"]) == 1


class TestGet:
    def test_by_id(self, client: TestClient):
        r = client.get("/api/topics/top_aaaaaaaa")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Bitcoin Price"
        assert body["description"] == "Bitcoin spot price trends"

    def test_unknown_returns_404(self, client: TestClient):
        r = client.get("/api/topics/top_nope")
        assert r.status_code == 404


class TestClaims:
    def test_reads_from_join(self, client: TestClient):
        """Source of truth is the claim_topics join, not the JSON cache."""
        r = client.get("/api/topics/top_aaaaaaaa/claims")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["topic_id"] == "top_aaaaaaaa"
        assert body["claims"][0]["text"] == "BTC broke 100k"
        assert "top_aaaaaaaa" in body["claims"][0]["topic_ids"]

    def test_empty_topic_returns_empty_list(self, client: TestClient):
        r = client.get("/api/topics/top_bbbbbbbb/claims")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_unknown_topic_returns_404(self, client: TestClient):
        r = client.get("/api/topics/top_nope/claims")
        assert r.status_code == 404
