"""Tests for app/api/entity_routes.py (P18 Phase B).

Uses a FastAPI TestClient wired against a throwaway JobStore so the
routes exercise the same SQL path production does, but with a clean DB
per test.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.entity_routes import router as entity_router
from app.core import job_store as job_store_module
from app.core.job_store import JobStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = JobStore(db_path=tmp_path / "entities_api.db")
    monkeypatch.setattr(job_store_module, "_job_store", store)

    now = datetime.utcnow().isoformat()
    store.upsert_entity(
        {
            "entity_id": "ent_aaaaaaaa",
            "slug": "person:vitalik-buterin",
            "name": "Vitalik Buterin",
            "entity_type": "person",
            "aliases": ["Vitalik"],
            "confidence": 0.95,
            "created_at": now,
        }
    )
    store.upsert_entity(
        {
            "entity_id": "ent_bbbbbbbb",
            "slug": "company:openai",
            "name": "OpenAI",
            "entity_type": "company",
            "aliases": ["OpenAI Inc."],
            "confidence": 0.9,
            "created_at": now,
        }
    )
    store.add_entity_mention(
        {
            "entity_id": "ent_aaaaaaaa",
            "episode_id": "ep-1",
            "claim_id": None,
            "chunk_id": "ep-1:chunk:0",
            "raw_text": "Vitalik",
            "start_char": 10,
            "end_char": 17,
            "timestamp": 12.5,
            "speaker": "Host A",
        }
    )

    app = FastAPI()
    app.include_router(entity_router, prefix="/api")
    yield TestClient(app)


class TestList:
    def test_lists_all(self, client: TestClient):
        r = client.get("/api/entities")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert {e["slug"] for e in body["entities"]} == {
            "person:vitalik-buterin",
            "company:openai",
        }

    def test_filter_by_type(self, client: TestClient):
        r = client.get("/api/entities", params={"entity_type": "company"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["entities"][0]["name"] == "OpenAI"

    def test_filter_by_slug(self, client: TestClient):
        r = client.get(
            "/api/entities", params={"slug": "person:vitalik-buterin"}
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1


class TestGet:
    def test_by_entity_id(self, client: TestClient):
        r = client.get("/api/entities/ent_aaaaaaaa")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Vitalik Buterin"
        assert body["entity_type"] == "person"
        assert "Vitalik" in body["aliases"]

    def test_by_slug(self, client: TestClient):
        r = client.get("/api/entities/person:vitalik-buterin")
        assert r.status_code == 200
        assert r.json()["entity_id"] == "ent_aaaaaaaa"

    def test_unknown_returns_404(self, client: TestClient):
        r = client.get("/api/entities/ent_does_not_exist")
        assert r.status_code == 404


class TestMentions:
    def test_lists_mentions(self, client: TestClient):
        r = client.get("/api/entities/ent_aaaaaaaa/mentions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        m = body["mentions"][0]
        assert m["raw_text"] == "Vitalik"
        assert m["start_char"] == 10
        assert m["end_char"] == 17

    def test_mentions_by_slug(self, client: TestClient):
        r = client.get("/api/entities/person:vitalik-buterin/mentions")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_mentions_unknown_returns_404(self, client: TestClient):
        r = client.get("/api/entities/ent_nope/mentions")
        assert r.status_code == 404
