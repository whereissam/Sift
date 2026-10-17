"""KOL scorecard step 1: KOLs, speaker mapping, prediction review.

See docs/kol-scorecard.md. Store and API are tested against a real on-disk
SQLite DB, like the rest of the knowledge-layer tests.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import store as job_store_module
from app.api.kol_routes import router as kol_router
from app.api.prediction_routes import router as prediction_router
from app.knowledge.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    EntityType,
    compute_claim_id,
    compute_entity_id,
)
from app.store import JobStore
from app.store._kols import HandleTakenError, normalize_handle

EPISODE = "ep-1"


def _claim(text: str, speaker: str | None, ts: float) -> dict:
    return Claim(
        claim_id=compute_claim_id(
            text=text, episode_id=EPISODE, speaker=speaker, timestamp_start=ts
        ),
        episode_id=EPISODE,
        text=text,
        speaker=speaker,
        timestamp_start=ts,
        timestamp_end=ts + 4,
        claim_type=ClaimType.PREDICTION,
        confidence=0.9,
        evidence_excerpt=f"...{text}...",
        source_url="https://x.com/i/spaces/1abc",
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    ).model_dump(mode="json")


def _extract(store: JobStore, claims: list[dict]) -> None:
    """What a (re-)extraction run writes: claims plus their predictions."""
    store.replace_claims_for_job(
        EPISODE,
        claims,
        predictions=[{"claim_id": c["claim_id"], "target_horizon": "Q3"} for c in claims],
    )


def _kol(store: JobStore, name: str, handles=()) -> dict:
    return store.upsert_kol(
        entity_id=compute_entity_id(name=name, entity_type=EntityType.PERSON),
        name=name,
        slug=f"person:{name.lower().replace(' ', '-')}",
        handles=list(handles),
    )


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "kol.db")


@pytest.fixture
def seeded(store: JobStore):
    a = _claim("ETH flips 6k by end of Q3", "SPEAKER_00", 41.0)
    b = _claim("SOL ETF approved before October", "SPEAKER_01", 125.0)
    _extract(store, [a, b])
    return store, a, b


@pytest.fixture
def client(seeded, monkeypatch: pytest.MonkeyPatch):
    store, a, b = seeded
    monkeypatch.setattr(job_store_module, "_job_store", store)
    app = FastAPI()
    app.include_router(kol_router, prefix="/api")
    app.include_router(prediction_router, prefix="/api")
    return TestClient(app), store, a, b


# ---------- store ----------


class TestKolStore:
    def test_handles_are_normalized(self):
        assert normalize_handle("x", " @Cobie ") == "cobie"
        assert normalize_handle("podcast", "https://feeds.example/Show") == (
            "https://feeds.example/Show"
        )

    def test_upsert_creates_person_and_is_idempotent(self, store):
        kol = _kol(store, "Cobie", [("x", "@Cobie")])
        again = _kol(store, "Cobie", [("x", "cobie"), ("youtube", "@UpOnly")])
        assert again["entity_id"] == kol["entity_id"]
        assert again["handles"] == [
            {"platform": "x", "handle": "cobie"},
            {"platform": "youtube", "handle": "uponly"},
        ]
        assert store.get_entity_by_id(kol["entity_id"])["entity_type"] == "person"

    def test_handle_owned_by_someone_else_is_refused(self, store):
        _kol(store, "Cobie", [("x", "cobie")])
        with pytest.raises(HandleTakenError):
            _kol(store, "Impostor", [("x", "@COBIE")])
        assert store.get_kol(
            compute_entity_id(name="Impostor", entity_type=EntityType.PERSON)
        ) is None

    def test_slug_collision_gets_a_suffix(self, store):
        store.upsert_entity({
            "entity_id": "ent_other", "slug": "person:cobie", "name": "Other",
            "entity_type": "person",
        })
        assert _kol(store, "Cobie")["slug"] == "person:cobie-2"

    def test_episode_speakers_lists_labels_with_assignment(self, seeded):
        store, _, _ = seeded
        kol = _kol(store, "Cobie")
        store.set_episode_speaker(EPISODE, "SPEAKER_00", kol["entity_id"], confirmed_by="sam")
        speakers = {s["speaker"]: s for s in store.list_episode_speakers(EPISODE)}
        assert speakers["SPEAKER_00"]["kol_name"] == "Cobie"
        assert speakers["SPEAKER_01"]["entity_id"] is None
        assert [k["name"] for k in store.list_kols()] == ["Cobie"]


class TestReviewStore:
    def test_new_predictions_start_unreviewed(self, seeded):
        store, a, _ = seeded
        assert store.get_prediction_by_claim_id(a["claim_id"])["review_status"] == "unreviewed"

    def test_review_round_trip_clears_metadata(self, seeded):
        store, a, _ = seeded
        row = store.set_prediction_review(a["claim_id"], status="rejected", note="misheard",
                                          reviewed_by="sam")
        assert (row["review_status"], row["review_note"], row["reviewed_by"]) == (
            "rejected", "misheard", "sam")
        assert row["reviewed_at"]
        row = store.set_prediction_review(a["claim_id"], status="unreviewed")
        assert (row["review_note"], row["reviewed_at"], row["reviewed_by"]) == (None, None, None)

    def test_unknown_prediction_returns_none(self, store):
        assert store.set_prediction_review("nope", status="verified") is None

    def test_queue_joins_quote_speaker_and_episode(self, seeded):
        store, a, b = seeded
        kol = _kol(store, "Cobie")
        store.set_episode_speaker(EPISODE, "SPEAKER_00", kol["entity_id"])
        items = store.list_review_queue()
        assert [i["claim_id"] for i in items] == [a["claim_id"], b["claim_id"]]
        first = items[0]
        assert first["text"] == "ETH flips 6k by end of Q3"
        assert first["kol_name"] == "Cobie"
        assert first["source_url"] == "https://x.com/i/spaces/1abc"
        assert items[1]["kol_entity_id"] is None

    def test_operator_state_survives_re_extraction(self, seeded):
        """Re-extracting an episode used to wipe resolution; review must not reset either."""
        store, a, b = seeded
        store.set_prediction_review(a["claim_id"], status="verified", reviewed_by="sam")
        store.resolve_prediction(a["claim_id"], resolution="false", note="ETH 4.1k")
        c = _claim("BTC 200k next year", "SPEAKER_00", 300.0)
        _extract(store, [a, c])  # b dropped, c new, a unchanged

        kept = store.get_prediction_by_claim_id(a["claim_id"])
        assert (kept["review_status"], kept["reviewed_by"]) == ("verified", "sam")
        assert (kept["resolution"], kept["resolution_note"]) == ("false", "ETH 4.1k")
        assert store.get_prediction_by_claim_id(c["claim_id"])["review_status"] == "unreviewed"
        assert store.get_prediction_by_claim_id(b["claim_id"]) is None

    def test_migration_adds_review_columns_to_old_database(self, tmp_path):
        db = tmp_path / "old.db"
        JobStore(db_path=db)
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE predictions")
        conn.execute("""
            CREATE TABLE predictions (
                claim_id TEXT PRIMARY KEY, target_horizon TEXT, conditions TEXT,
                falsifiable_by TEXT, resolution TEXT NOT NULL DEFAULT 'pending',
                resolution_note TEXT, resolved_at TEXT, resolved_by TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)
        """)
        conn.execute("INSERT INTO predictions (claim_id, created_at, updated_at) "
                     "VALUES ('old', 't', 't')")
        conn.commit()
        conn.close()

        store = JobStore(db_path=db)
        assert store.get_prediction_by_claim_id("old")["review_status"] == "unreviewed"


# ---------- API ----------


class TestKolApi:
    def test_create_list_and_remove_handle(self, client):
        http, *_ = client
        r = http.post("/api/kols", json={"name": "Cobie", "handles": [
            {"platform": "x", "handle": "@cobie"}]})
        assert r.status_code == 200
        kol = r.json()
        assert kol["handles"] == [{"platform": "x", "handle": "cobie"}]
        assert http.get("/api/kols").json()["count"] == 1
        assert http.delete(f"/api/kols/{kol['entity_id']}/handles/x/cobie").status_code == 204
        assert http.delete(f"/api/kols/{kol['entity_id']}/handles/x/cobie").status_code == 404

    def test_handle_conflict_is_409(self, client):
        http, *_ = client
        http.post("/api/kols", json={"name": "Cobie", "handles": [
            {"platform": "x", "handle": "cobie"}]})
        r = http.post("/api/kols", json={"name": "Impostor", "handles": [
            {"platform": "x", "handle": "Cobie"}]})
        assert r.status_code == 409

    def test_blank_name_and_unknown_platform_rejected(self, client):
        http, *_ = client
        assert http.post("/api/kols", json={"name": "   "}).status_code == 422
        assert http.post("/api/kols", json={"name": "A", "handles": [
            {"platform": "myspace", "handle": "a"}]}).status_code == 422

    def test_assign_and_clear_speaker(self, client):
        http, *_ = client
        kol = http.post("/api/kols", json={"name": "Cobie"}).json()
        r = http.put(f"/api/episodes/{EPISODE}/speakers/SPEAKER_00",
                     json={"entity_id": kol["entity_id"], "confirmed_by": "sam"})
        assert r.status_code == 200
        assert r.json()["kol_name"] == "Cobie"
        speakers = http.get(f"/api/episodes/{EPISODE}/speakers").json()["speakers"]
        assert {s["speaker"] for s in speakers} == {"SPEAKER_00", "SPEAKER_01"}
        assert http.delete(f"/api/episodes/{EPISODE}/speakers/SPEAKER_00").status_code == 204

    def test_assign_unknown_speaker_or_kol_is_404(self, client):
        http, *_ = client
        kol = http.post("/api/kols", json={"name": "Cobie"}).json()
        assert http.put(f"/api/episodes/{EPISODE}/speakers/NOBODY",
                        json={"entity_id": kol["entity_id"]}).status_code == 404
        assert http.put(f"/api/episodes/{EPISODE}/speakers/SPEAKER_00",
                        json={"entity_id": "ent_missing"}).status_code == 404


class TestReviewApi:
    def test_queue_route_is_not_swallowed_by_claim_id(self, client):
        http, _, a, b = client
        body = http.get("/api/predictions/review-queue").json()
        assert body["count"] == 2
        assert body["items"][0]["claim_id"] == a["claim_id"]
        assert body["items"][0]["speaker"] == "SPEAKER_00"

    def test_verify_requires_assigned_speaker(self, client):
        http, _, a, _ = client
        url = f"/api/predictions/{a['claim_id']}/review"
        assert http.post(url, json={"status": "verified"}).status_code == 409

        kol = http.post("/api/kols", json={"name": "Cobie"}).json()
        http.put(f"/api/episodes/{EPISODE}/speakers/SPEAKER_00",
                 json={"entity_id": kol["entity_id"]})
        r = http.post(url, json={"status": "verified", "reviewed_by": "sam"})
        assert r.status_code == 200
        assert r.json()["review_status"] == "verified"

        queue = http.get("/api/predictions/review-queue").json()["items"]
        assert a["claim_id"] not in [i["claim_id"] for i in queue]
        verified = http.get("/api/predictions/review-queue?status=verified").json()["items"]
        assert verified[0]["kol_name"] == "Cobie"

    def test_reject_needs_no_speaker(self, client):
        http, _, _, b = client
        r = http.post(f"/api/predictions/{b['claim_id']}/review",
                      json={"status": "rejected", "note": "not a prediction"})
        assert r.status_code == 200
        assert r.json()["review_note"] == "not a prediction"

    def test_review_unknown_prediction_is_404(self, client):
        http, *_ = client
        assert http.post("/api/predictions/nope/review",
                         json={"status": "rejected"}).status_code == 404

    def test_prediction_payload_carries_review_fields(self, client):
        http, _, a, _ = client
        body = http.get(f"/api/predictions/{a['claim_id']}").json()
        assert body["review_status"] == "unreviewed"
        assert json.dumps(body)  # serializable as-is
