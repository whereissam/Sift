"""Tests for the P20 digest API (app/api/digest_routes.py).

CRUD over configs, run-now (with run_digest stubbed — the pipeline itself is
covered in test_digest_runner.py), and on-demand topic synthesis.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.digest_routes import router as digest_router
from app.core import job_store as job_store_module
from app.core.digest_schema import DigestRunResult, DigestSynthesis
from app.core.job_store import JobStore


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    s = JobStore(db_path=tmp_path / "api.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    return s


@pytest.fixture
def client(store: JobStore) -> TestClient:
    app = FastAPI()
    app.include_router(digest_router)
    return TestClient(app)


class TestConfigCRUD:
    def test_create_then_get(self, client: TestClient):
        r = client.post("/digests", json={"name": "Crypto", "subscription_ids": ["s1", "s2"]})
        assert r.status_code == 201
        digest_id = r.json()["digest_id"]

        g = client.get(f"/digests/{digest_id}")
        assert g.status_code == 200
        assert g.json()["config"]["name"] == "Crypto"
        assert g.json()["latest_run"] is None

    def test_create_requires_subscription(self, client: TestClient):
        r = client.post("/digests", json={"name": "X", "subscription_ids": []})
        assert r.status_code == 422  # min_length=1

    def test_list(self, client: TestClient):
        client.post("/digests", json={"name": "A", "subscription_ids": ["s1"]})
        client.post("/digests", json={"name": "B", "subscription_ids": ["s2"]})
        assert len(client.get("/digests").json()) == 2

    def test_patch(self, client: TestClient):
        digest_id = client.post("/digests", json={"name": "A", "subscription_ids": ["s1"]}).json()["digest_id"]
        r = client.patch(f"/digests/{digest_id}", json={"window_days": 30, "enabled": False})
        assert r.json()["window_days"] == 30
        assert r.json()["enabled"] is False

    def test_delete(self, client: TestClient):
        digest_id = client.post("/digests", json={"name": "A", "subscription_ids": ["s1"]}).json()["digest_id"]
        assert client.delete(f"/digests/{digest_id}").json()["deleted"] is True
        assert client.get(f"/digests/{digest_id}").status_code == 404

    def test_get_unknown_404(self, client: TestClient):
        assert client.get("/digests/ghost").status_code == 404


class TestRunNow:
    def test_run_now_returns_run(self, client: TestClient, store: JobStore, monkeypatch):
        digest_id = client.post("/digests", json={"name": "A", "subscription_ids": ["s1"]}).json()["digest_id"]

        async def fake_run(cfg, **kwargs):
            return store.save_digest_run(
                "r1", cfg["digest_id"], status="ok", claim_count=7, markdown="# d"
            )

        monkeypatch.setattr("app.api.digest_routes.run_digest", fake_run)
        r = client.post(f"/digests/{digest_id}/run")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["claim_count"] == 7

    def test_run_unknown_404(self, client: TestClient):
        assert client.post("/digests/ghost/run").status_code == 404

    def test_list_runs(self, client: TestClient, store: JobStore):
        digest_id = client.post("/digests", json={"name": "A", "subscription_ids": ["s1"]}).json()["digest_id"]
        store.save_digest_run("r1", digest_id, status="ok")
        r = client.get(f"/digests/{digest_id}/runs")
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestTopicSynthesis:
    def test_unknown_topic_404(self, client: TestClient):
        assert client.get("/topics/ghost/synthesis").status_code == 404

    def test_topic_synthesis_success(self, client: TestClient, store: JobStore, monkeypatch):
        # Seed a topic + a couple of claims linked to it.
        store.upsert_topic({"topic_id": "t1", "name": "Bitcoin", "description": "btc"})
        from app.core.knowledge_schema import (
            EXTRACTION_VERSION,
            SCHEMA_VERSION,
            Claim,
            ClaimType,
            compute_claim_id,
        )
        from app.core.job_store._enums import JobType

        store.create_job("e1", JobType.TRANSCRIBE)
        claims = []
        for i in range(3):
            cid = compute_claim_id(text=f"c{i}", episode_id="e1", speaker=None, timestamp_start=float(i))
            claims.append(Claim(
                claim_id=cid, episode_id="e1", text=f"c{i}", timestamp_start=float(i),
                timestamp_end=float(i + 1), claim_type=ClaimType.FACT, confidence=0.9,
                evidence_excerpt="x", topic_ids=["t1"],
                extraction_version=EXTRACTION_VERSION, schema_version=SCHEMA_VERSION,
            ).model_dump(mode="json"))
        edges = [{"claim_id": c["claim_id"], "topic_id": "t1", "confidence": 0.9} for c in claims]
        store.replace_claims_for_job("e1", claims, topics=[{"topic_id": "t1", "name": "Bitcoin", "description": "btc"}], claim_topic_edges=edges)

        class FakeSynth:
            async def synthesize(self, claims, *, window_label="", max_claims=200):
                return DigestRunResult(
                    success=True, synthesis=DigestSynthesis(headline="topic takeaway"),
                    claim_count=len(claims), tokens_used=100, model="gpt-4o", provider="openai",
                )

        monkeypatch.setattr(
            "app.api.digest_routes.DigestSynthesizer.from_settings",
            classmethod(lambda cls: FakeSynth()),
        )
        r = client.get("/topics/t1/synthesis?min_confidence=0.5")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["name"] == "Bitcoin"
        assert body["synthesis"]["headline"] == "topic takeaway"
        assert body["claim_count"] == 3
