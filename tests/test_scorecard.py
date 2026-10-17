"""KOL scorecard step 3: scoring, the weekly digest, and what may reach them."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import store as job_store_module
from app.api.scorecard_routes import router as scorecard_router
from app.knowledge.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    EntityType,
    compute_claim_id,
    compute_entity_id,
)
from app.knowledge.scorecard import (
    boldness,
    build_digest,
    build_leaderboard,
    wilson_lower_bound,
)
from app.store import JobStore, JobType

START = datetime(2026, 10, 12, tzinfo=timezone.utc)
END = datetime(2026, 10, 19, tzinfo=timezone.utc)
_seq = iter(range(10_000))


def call(kol="cobie", resolution="pending", *, made_at="2026-10-13T10:00:00+00:00",
         resolved_at=None, target=None, text=None, note=None, due_at=None, handle=True):
    n = next(_seq)
    return {
        "claim_id": f"c{n}", "kol_entity_id": f"ent_{kol}", "kol_name": kol.title(),
        "kol_x_handle": kol if handle else None, "resolution": resolution,
        "resolution_note": note, "resolved_at": resolved_at, "made_at": made_at,
        "due_at": due_at, "text": text or f"call {n}", "episode_id": "ep-1",
        "timestamp_start": 41.0, "source_url": "https://youtube.com/watch?v=abc",
        "target": target,
    }


def eth_target(value=6000, baseline=4000, comparator=">="):
    return {"asset": "ETH", "comparator": comparator, "value": value, "baseline": baseline}


# ---------- scoring ----------


class TestScoring:
    def test_wilson_punishes_small_samples(self):
        assert wilson_lower_bound(0, 0) == 0.0
        assert wilson_lower_bound(2, 2) < wilson_lower_bound(40, 60)
        assert wilson_lower_bound(40, 60) == pytest.approx(0.54, abs=0.01)

    def test_boldness_follows_the_called_direction(self):
        assert boldness(eth_target(6000, 4000)) == pytest.approx(0.5)
        assert boldness(eth_target(3000, 4000, "<=")) == pytest.approx(0.25)
        assert boldness(eth_target(3000, 4000)) == 0.0  # "ETH >= 3000" when it is 4000
        assert boldness({"comparator": ">=", "value": 1, "baseline": None}) is None
        assert boldness(None) is None

    def test_leaderboard_needs_min_resolved_and_ranks_by_score(self):
        calls = (
            [call("lucky", "true") for _ in range(2)]
            + [call("steady", "true") for _ in range(40)] + [call("steady", "false") for _ in range(20)]
            + [call("ok", "true") for _ in range(3)] + [call("ok", "false") for _ in range(2)]
        )
        board = build_leaderboard(calls, min_resolved=5)
        assert [s.handle for s in board] == ["steady", "ok"]  # lucky has only 2
        assert board[0].hit_rate == pytest.approx(2 / 3)

    def test_bold_hits_vagueness_and_open_calls(self):
        calls = [
            call("k", "true", target=eth_target(6000, 4000)),  # +50%: bold
            call("k", "true", target=eth_target(4200, 4000)),  # +5%: not bold
            call("k", "true"), call("k", "false"), call("k", "false"),
            call("k", "unresolvable"), call("k", "pending"),
        ]
        [score] = build_leaderboard(calls, min_resolved=5)
        assert (score.resolved, score.hits, score.bold_hits) == (5, 3, 1)
        assert score.too_vague == 1 and score.too_vague_rate == pytest.approx(1 / 6)
        assert score.open_calls == 1
        assert score.label == "@k"


# ---------- digest ----------


class TestDigest:
    def test_sections_and_links(self):
        calls = [
            call("cobie", "false", resolved_at="2026-10-14T00:00:00+00:00",
                 made_at="2026-06-02T00:00:00+00:00", text="ETH flips 6k by Q3",
                 note="ETH ≥ $6,000 by 2026-09-30: peaked at $4,180"),
            call("hsaka", "pending", text="SOL 300 by March",
                 target={"asset": "SOL", "comparator": ">=", "value": 300, "baseline": 150},
                 due_at="2027-03-31"),
        ]
        md, stats = build_digest(calls, [], start=START, end=END)
        assert md.startswith("# Crypto Calls Weekly — 2026-10-12 to 2026-10-18")
        assert "❌ **@cobie**: “ETH flips 6k by Q3” · said 2026-06-02" in md
        assert "peaked at $4,180" in md
        assert "[▶ 0:41](https://youtube.com/watch?v=abc&t=41s)" in md
        assert "**@hsaka**: “SOL 300 by March” · SOL ≥ $300 (+100% from $150) · due 2027-03-31" in md
        assert "_No KOL has 5 resolved calls yet._" in md
        assert "AI-assisted, human-reviewed" in md
        assert (stats["came_due"], stats["resolved_false"], stats["new_calls"]) == (1, 1, 1)

    def test_calls_outside_the_window_are_left_out(self):
        old = call("cobie", made_at="2026-09-01T00:00:00+00:00", text="old call")
        md, stats = build_digest([old], [], start=START, end=END)
        assert "old call" not in md and stats["new_calls"] == 0
        assert "Boldest" not in md  # empty sections are omitted

    def test_flip_flop_needs_the_same_kol(self):
        a = call("cobie", made_at="2026-09-03T00:00:00+00:00", text="alt season is dead")
        b = call("cobie", made_at="2026-10-15T00:00:00+00:00", text="alt season starts now")
        other = call("hsaka", made_at="2026-10-15T00:00:00+00:00", text="someone else")
        contradictions = [
            {"claim_id_a": b["claim_id"], "claim_id_b": a["claim_id"]},
            {"claim_id_a": a["claim_id"], "claim_id_b": other["claim_id"]},
        ]
        md, stats = build_digest([a, b, other], contradictions, start=START, end=END)
        assert stats["flip_flops"] == 1
        assert "**@cobie** said “alt season is dead” (2026-09-03" in md
        assert "→ “alt season starts now” (2026-10-15" in md

    def test_consensus_and_contrarian(self):
        bull = {"asset": "ETH", "comparator": ">=", "value": 6000, "baseline": 4000}
        bear = {"asset": "ETH", "comparator": "<=", "value": 3000, "baseline": 4000}
        calls = [call(k, target=bull) for k in ("a", "b", "c")] + [call("d", target=bear)]
        md, _ = build_digest(calls, [], start=START, end=END)
        assert "- 3 of 4 KOLs bullish on ETH; contrarian: **@d**" in md

    def test_no_consensus_line_for_split_or_tiny_samples(self):
        bull = {"asset": "ETH", "comparator": ">=", "value": 6000, "baseline": 4000}
        bear = {"asset": "ETH", "comparator": "<=", "value": 3000, "baseline": 4000}
        md, _ = build_digest([call("a", target=bull), call("b", target=bear)], [],
                             start=START, end=END)
        assert "Consensus" not in md

    def test_correction_link_and_name_without_handle(self):
        c = call("vitalik", handle=False, text="ETH 10k")
        md, _ = build_digest([c], [], start=START, end=END,
                             corrections_url="https://example.com/fix")
        assert "**Vitalik**: “ETH 10k”" in md
        assert "[Request a correction](https://example.com/fix)" in md
        md, _ = build_digest([c], [], start=START, end=END)
        assert "Spotted a mistake? Tell us and we'll fix it." in md


# ---------- store + API ----------

EPISODE = "ep-1"


def _claim(text, speaker, ts):
    return Claim(
        claim_id=compute_claim_id(text=text, episode_id=EPISODE, speaker=speaker, timestamp_start=ts),
        episode_id=EPISODE, text=text, speaker=speaker, timestamp_start=ts, timestamp_end=ts + 2,
        claim_type=ClaimType.PREDICTION, confidence=0.9, evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION, schema_version=SCHEMA_VERSION,
    ).model_dump(mode="json")


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> JobStore:
    store = JobStore(db_path=tmp_path / "scorecard.db")
    monkeypatch.setattr(job_store_module, "_job_store", store)
    store.create_job(EPISODE, JobType.DOWNLOAD, source_url="https://x.com/i/spaces/1abc")
    store.update_job(EPISODE, content_info={"title": "Space", "published_at": "2026-10-13T12:00:00"})
    verified = _claim("ETH flips 6k by Q3", "S0", 10)
    unverified = _claim("BTC 200k", "S0", 20)
    unassigned = _claim("SOL 300", "S1", 30)
    claims = [verified, unverified, unassigned]
    store.replace_claims_for_job(EPISODE, claims, predictions=[{"claim_id": c["claim_id"]} for c in claims])
    kol = store.upsert_kol(
        entity_id=compute_entity_id(name="Cobie", entity_type=EntityType.PERSON),
        name="Cobie", slug="person:cobie", handles=[("x", "cobie")],
    )
    store.set_episode_speaker(EPISODE, "S0", kol["entity_id"])
    store.set_prediction_review(verified["claim_id"], status="verified")
    store.set_prediction_review(unassigned["claim_id"], status="verified")  # speaker S1 unassigned
    store.set_prediction_target(verified["claim_id"], asset="ETH", coin_id="ethereum",
                                comparator=">=", value=6000, source="parsed")
    store.record_target_check(verified["claim_id"], baseline=4000)
    return store


class TestStoreAndApi:
    def test_only_verified_and_assigned_calls_reach_the_scorecard(self, store):
        calls = store.list_scorecard_calls()
        assert [c["text"] for c in calls] == ["ETH flips 6k by Q3"]
        c = calls[0]
        assert (c["kol_name"], c["kol_x_handle"]) == ("Cobie", "cobie")
        assert c["made_at"] == "2026-10-13T12:00:00"
        assert c["source_url"] == "https://x.com/i/spaces/1abc"
        assert c["target"]["baseline"] == 4000

    def test_digest_and_leaderboard_endpoints(self, store):
        app = FastAPI()
        app.include_router(scorecard_router, prefix="/api")
        http = TestClient(app)

        r = http.get("/api/scorecard/digest", params={"start": "2026-10-12", "end": "2026-10-18"})
        assert r.status_code == 200
        body = r.json()
        assert body["stats"]["new_calls"] == 1
        assert "**@cobie**: “ETH flips 6k by Q3” · ETH ≥ $6,000 (+50% from $4,000)" in body["markdown"]
        assert "BTC 200k" not in body["markdown"] and "SOL 300" not in body["markdown"]

        md = http.get("/api/scorecard/digest",
                      params={"start": "2026-10-12", "end": "2026-10-18", "format": "md"})
        assert md.headers["content-type"].startswith("text/markdown")
        assert md.text == body["markdown"]

        board = http.get("/api/scorecard/leaderboard", params={"min_resolved": 1}).json()
        assert board["count"] == 0  # nothing resolved yet

    def test_digest_validation(self, store):
        app = FastAPI()
        app.include_router(scorecard_router, prefix="/api")
        http = TestClient(app)
        assert http.get("/api/scorecard/digest",
                        params={"start": "2026-10-19", "end": "2026-10-12"}).status_code == 422
        assert http.get("/api/scorecard/digest",
                        params={"corrections_url": "javascript:alert(1)"}).status_code == 422
