"""Scorecard step 2: due dates, price targets and the price checker.

The price feed is faked, so nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import store as job_store_module
from app.api.prediction_routes import router as prediction_router
from app.knowledge import prediction_checker
from app.knowledge.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)
from app.knowledge.prediction_checker import PredictionChecker, PriceFeedError
from app.store import JobStore, JobType

EPISODE = "ep-1"
MADE = datetime(2026, 6, 2, tzinfo=timezone.utc)


class FakeFeed:
    """Daily prices from a dict {day offset from MADE: price}."""

    def __init__(self, prices: dict[int, float] | None = None, fail: bool = False):
        self.prices = prices or {}
        self.fail = fail
        self.calls: list[tuple[str, datetime, datetime]] = []

    async def history(self, coin_id, start, end):
        self.calls.append((coin_id, start, end))
        if self.fail:
            raise PriceFeedError("rate limited")
        points = [(MADE + timedelta(days=d), p) for d, p in sorted(self.prices.items())]
        return [(t, p) for t, p in points if start <= t <= end]


def _claim(text: str, ts: float) -> dict:
    return Claim(
        claim_id=compute_claim_id(text=text, episode_id=EPISODE, speaker="S0", timestamp_start=ts),
        episode_id=EPISODE, text=text, speaker="S0",
        timestamp_start=ts, timestamp_end=ts + 3,
        claim_type=ClaimType.PREDICTION, confidence=0.9, evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION, schema_version=SCHEMA_VERSION,
    ).model_dump(mode="json")


def _extract(store: JobStore, claims_and_horizons: list[tuple[dict, str | None]]) -> None:
    store.replace_claims_for_job(
        EPISODE,
        [c for c, _ in claims_and_horizons],
        predictions=[{"claim_id": c["claim_id"], "target_horizon": h} for c, h in claims_and_horizons],
    )


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    store = JobStore(db_path=tmp_path / "checker.db")
    monkeypatch.setattr(job_store_module, "_job_store", store)
    store.create_job(EPISODE, JobType.DOWNLOAD, source_url="https://x.com/i/spaces/1abc")
    store.update_job(EPISODE, content_info={"title": "Crypto Space", "published_at": MADE.isoformat()})
    return store


def _verify(store: JobStore, claim_id: str) -> None:
    store.set_prediction_review(claim_id, status="verified", reviewed_by="test")


async def _run(feed: FakeFeed, now: datetime):
    return await PredictionChecker(feed, now=now).run()


class TestParsing:
    async def test_parses_due_date_and_target_from_text(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        summary = await _run(FakeFeed(), MADE + timedelta(days=1))

        assert (summary.due_dates_parsed, summary.targets_parsed) == (1, 1)
        p = store.get_prediction_by_claim_id(eth["claim_id"])
        assert (p["due_at"], p["due_source"]) == ("2026-09-30", "parsed")
        t = store.get_prediction_target(eth["claim_id"])
        assert (t["asset"], t["comparator"], t["value"], t["source"]) == ("ETH", ">=", 6000, "parsed")

    async def test_unverified_calls_are_parsed_but_never_priced(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        feed = FakeFeed({10: 7000})
        await _run(feed, MADE + timedelta(days=20))
        assert feed.calls == []
        assert store.get_prediction_by_claim_id(eth["claim_id"])["resolution"] == "pending"

    async def test_manual_target_and_cleared_due_are_left_alone(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        store.set_prediction_target(eth["claim_id"], asset="ETH", coin_id="ethereum",
                                    comparator=">=", value=5000, source="manual")
        store.set_prediction_due(eth["claim_id"], None, source="manual")
        await _run(FakeFeed(), MADE + timedelta(days=1))
        assert store.get_prediction_target(eth["claim_id"])["value"] == 5000
        assert store.get_prediction_by_claim_id(eth["claim_id"])["due_at"] is None


class TestResolution:
    async def test_target_hit_before_due_resolves_true_early(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        _verify(store, eth["claim_id"])
        summary = await _run(FakeFeed({0: 3800, 30: 5200, 45: 6120, 50: 5900}),
                             MADE + timedelta(days=60))

        assert summary.resolved_true == 1
        p = store.get_prediction_by_claim_id(eth["claim_id"])
        assert (p["resolution"], p["resolved_by"]) == ("true", "price-checker")
        assert "$6,120" in p["resolution_note"] and "2026-07-17" in p["resolution_note"]
        t = store.get_prediction_target(eth["claim_id"])
        assert t["baseline"] == 3800
        assert t["evidence"]["extreme"] == 6120

    async def test_due_date_passed_without_hit_resolves_false(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        _verify(store, eth["claim_id"])
        # A spike *after* the due date must not count.
        feed = FakeFeed({0: 3800, 60: 4180, 100: 4000, 130: 7000})
        summary = await _run(feed, MADE + timedelta(days=140))

        assert summary.resolved_false == 1
        p = store.get_prediction_by_claim_id(eth["claim_id"])
        assert p["resolution"] == "false"
        assert "peaked at $4,180" in p["resolution_note"]
        assert feed.calls[0][2] == datetime(2026, 10, 1, tzinfo=timezone.utc)  # window ends at due

    async def test_still_open_call_stays_pending_with_evidence(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        _verify(store, eth["claim_id"])
        summary = await _run(FakeFeed({0: 3800, 20: 4500}), MADE + timedelta(days=30))

        assert (summary.checked, summary.resolved_true, summary.resolved_false) == (1, 0, 0)
        assert store.get_prediction_by_claim_id(eth["claim_id"])["resolution"] == "pending"
        assert store.get_prediction_target(eth["claim_id"])["evidence"]["extreme"] == 4500

    async def test_below_target_uses_the_minimum(self, store):
        sol = _claim("SOL drops to $80 within 3 months", 1)
        _extract(store, [(sol, "within 3 months")])
        _verify(store, sol["claim_id"])
        await _run(FakeFeed({0: 150, 40: 79.5, 60: 120}), MADE + timedelta(days=70))
        p = store.get_prediction_by_claim_id(sol["claim_id"])
        assert p["resolution"] == "true"
        assert "SOL ≤ $80.00" in p["resolution_note"]

    async def test_no_due_date_can_only_resolve_true(self, store):
        btc = _claim("BTC to 200k", 1)
        _extract(store, [(btc, None)])
        _verify(store, btc["claim_id"])
        await _run(FakeFeed({0: 100_000, 400: 150_000}), MADE + timedelta(days=500))
        assert store.get_prediction_by_claim_id(btc["claim_id"])["resolution"] == "pending"

    async def test_feed_errors_are_reported_not_raised(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        _verify(store, eth["claim_id"])
        summary = await _run(FakeFeed(fail=True), MADE + timedelta(days=30))
        assert summary.errors and "rate limited" in summary.errors[0]

    async def test_resolved_calls_are_not_rechecked(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        _verify(store, eth["claim_id"])
        await _run(FakeFeed({0: 3800, 10: 6500}), MADE + timedelta(days=20))
        feed = FakeFeed({0: 3800, 10: 6500})
        await _run(feed, MADE + timedelta(days=21))
        assert feed.calls == []


class TestReExtraction:
    async def test_targets_and_due_dates_survive_and_orphans_are_dropped(self, store):
        eth = _claim("ETH flips 6k by end of Q3", 1)
        sol = _claim("SOL drops to $80 within 3 months", 2)
        _extract(store, [(eth, "end of Q3"), (sol, "within 3 months")])
        await _run(FakeFeed(), MADE + timedelta(days=1))
        store.set_prediction_target(eth["claim_id"], asset="ETH", coin_id="ethereum",
                                    comparator=">=", value=5500, source="manual")

        _extract(store, [(eth, "end of Q3")])  # sol's claim disappears

        assert store.get_prediction_target(eth["claim_id"])["value"] == 5500
        assert store.get_prediction_by_claim_id(eth["claim_id"])["due_at"] == "2026-09-30"
        assert store.get_prediction_target(sol["claim_id"]) is None


class TestApi:
    @pytest.fixture
    def http(self, store, monkeypatch):
        app = FastAPI()
        app.include_router(prediction_router, prefix="/api")
        feed = FakeFeed({0: 3800, 45: 6120})
        monkeypatch.setattr(prediction_checker, "CoinGeckoFeed", lambda *a, **k: feed)
        eth = _claim("ETH flips 6k by end of Q3", 1)
        _extract(store, [(eth, "end of Q3")])
        return TestClient(app), eth["claim_id"]

    def test_set_and_clear_target(self, http):
        client, cid = http
        r = client.put(f"/api/predictions/{cid}/target",
                       json={"asset": "eth", "comparator": ">=", "value": 5000})
        assert r.status_code == 200
        assert r.json()["target"] == {
            "asset": "ETH", "coin_id": "ethereum", "metric": "price", "comparator": ">=",
            "value": 5000.0, "baseline": None, "evidence": None, "source": "manual",
        }
        assert client.delete(f"/api/predictions/{cid}/target").status_code == 204
        assert client.delete(f"/api/predictions/{cid}/target").status_code == 404

    def test_target_validation(self, http):
        client, cid = http
        assert client.put(f"/api/predictions/{cid}/target",
                          json={"asset": "PEPE", "value": 1}).status_code == 422
        assert client.put(f"/api/predictions/{cid}/target",
                          json={"asset": "ETH", "value": -5}).status_code == 422
        assert client.put("/api/predictions/nope/target",
                          json={"asset": "ETH", "value": 5}).status_code == 404

    def test_set_and_clear_due(self, http):
        client, cid = http
        r = client.put(f"/api/predictions/{cid}/due", json={"due_at": "2026-12-31"})
        assert (r.json()["due_at"], r.json()["due_source"]) == ("2026-12-31", "manual")
        r = client.put(f"/api/predictions/{cid}/due", json={"due_at": None})
        assert (r.json()["due_at"], r.json()["due_source"]) == (None, "manual")

    def test_check_endpoint_parses_and_resolves(self, http, store):
        client, cid = http
        store.set_prediction_review(cid, status="verified")
        r = client.post("/api/predictions/check")
        assert r.status_code == 200
        body = r.json()
        assert (body["targets_parsed"], body["resolved_true"]) == (1, 1)
        listed = client.get("/api/predictions").json()["predictions"][0]
        assert listed["resolution"] == "true"
        assert listed["target"]["asset"] == "ETH"
        assert json.dumps(listed)
