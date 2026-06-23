"""Tests for the P20 digest runner: claim gathering, run_digest, worker."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config import get_settings
from app.core import job_store as job_store_module
from app.core import subscription_store as sub_store_module
from app.core.digest_runner import DigestRunner, run_digest
from app.core.digest_runner_helpers import gather_claims_for_digest
from app.core.digest_schema import DigestRunResult, DigestSynthesis
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType
from app.core.knowledge_budget import get_budget_tracker
from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)
from app.core.subscription_store import (
    SubscriptionItemStatus,
    SubscriptionPlatform,
    SubscriptionStore,
    SubscriptionType,
)


@pytest.fixture(autouse=True)
def _reset_budget():
    get_budget_tracker().reset()
    yield
    get_budget_tracker().reset()


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    js = JobStore(db_path=tmp_path / "j.db")
    ss = SubscriptionStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(job_store_module, "_job_store", js)
    monkeypatch.setattr(sub_store_module, "_subscription_store", ss)
    return js, ss


def _episode_with_claims(js: JobStore, job_id: str, n: int, *, confidence=0.9):
    js.create_job(job_id, JobType.TRANSCRIBE)
    rows = []
    for i in range(n):
        cid = compute_claim_id(
            text=f"{job_id} claim {i}", episode_id=job_id, speaker=None,
            timestamp_start=float(i),
        )
        rows.append(
            Claim(
                claim_id=cid, episode_id=job_id, text=f"{job_id} claim {i}",
                timestamp_start=float(i), timestamp_end=float(i + 1),
                claim_type=ClaimType.FACT, confidence=confidence, evidence_excerpt="x",
                extraction_version=EXTRACTION_VERSION, schema_version=SCHEMA_VERSION,
            ).model_dump(mode="json")
        )
    js.replace_claims_for_job(job_id, rows)


def _subscription_with_episode(ss: SubscriptionStore, sub_id, item_id, job_id):
    ss.create_subscription(
        sub_id, sub_id, SubscriptionType.RSS, SubscriptionPlatform.PODCAST,
        source_url=f"http://{sub_id}",
    )
    ss.create_item(item_id, sub_id, f"c-{item_id}", f"http://{item_id}", title=item_id)
    ss.set_item_status(item_id, SubscriptionItemStatus.COMPLETED, job_id=job_id)


class FakeSynth:
    def __init__(self, *, success=True):
        self._success = success

    async def synthesize(self, claims, *, window_label="", max_claims=200):
        # Mirror the real synthesizer's degradation floor so empty/thin windows
        # produce a non-success result.
        if not self._success or len(claims) < 3:
            return DigestRunResult(success=False, error="degraded", claim_count=len(claims))
        return DigestRunResult(
            success=True,
            synthesis=DigestSynthesis(headline="cross!"),
            episode_count=1, claim_count=len(claims),
            tokens_used=250, model="gpt-4o", provider="openai",
        )


class TestGather:
    def test_gathers_and_dedups(self, stores):
        js, ss = stores
        _episode_with_claims(js, "job1", 3)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        cfg = js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                      window_days=30, min_confidence=0.5)
        claims, episodes = gather_claims_for_digest(cfg)
        assert len(claims) == 3
        assert episodes == 1

    def test_min_confidence_filters(self, stores):
        js, ss = stores
        _episode_with_claims(js, "job1", 3, confidence=0.3)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        cfg = js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                      window_days=30, min_confidence=0.6)
        claims, _ = gather_claims_for_digest(cfg)
        assert claims == []

    def test_window_excludes_old_episodes(self, stores):
        js, ss = stores
        _episode_with_claims(js, "job1", 3)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        # Force the item's download timestamp far in the past.
        ss.update_item("it1", downloaded_at=(datetime.utcnow() - timedelta(days=60)).isoformat())
        cfg = js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                      window_days=7, min_confidence=0.5)
        claims, episodes = gather_claims_for_digest(cfg)
        assert claims == [] and episodes == 0


class TestRunDigest:
    @pytest.mark.asyncio
    async def test_ok_run_persists_and_advances_clock(self, stores):
        js, ss = stores
        _episode_with_claims(js, "job1", 4)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        cfg = js.create_digest_config("d1", name="Weekly", subscription_ids=["sub1"],
                                      window_days=30, min_confidence=0.5)
        run = await run_digest(cfg, synthesizer=FakeSynth(), emit=False)
        assert run["status"] == "ok"
        assert run["claim_count"] == 4
        assert "cross!" in run["markdown"]
        assert js.get_digest_config("d1")["last_run_at"] is not None
        assert get_budget_tracker().spent_today() > 0

    @pytest.mark.asyncio
    async def test_empty_window_records_empty_run(self, stores):
        js, ss = stores
        cfg = js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                      window_days=7, min_confidence=0.5)
        run = await run_digest(cfg, synthesizer=FakeSynth(), emit=False)
        assert run["status"] == "empty"
        assert run["claim_count"] == 0

    @pytest.mark.asyncio
    async def test_over_budget_skips(self, stores, monkeypatch):
        js, ss = stores
        _episode_with_claims(js, "job1", 4)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        cfg = js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                      window_days=30, min_confidence=0.5)
        # Budget already exhausted for the day.
        monkeypatch.setattr(get_settings(), "knowledge_daily_budget_usd", 1.0)
        get_budget_tracker().record(5.0)
        run = await run_digest(cfg, synthesizer=FakeSynth(), emit=False)
        assert run["status"] == "skipped"
        assert "budget" in run["error"].lower()


class TestWorker:
    @pytest.mark.asyncio
    async def test_tick_processes_due_digests(self, stores, monkeypatch):
        js, ss = stores
        _episode_with_claims(js, "job1", 4)
        _subscription_with_episode(ss, "sub1", "it1", "job1")
        js.create_digest_config("d1", name="A", subscription_ids=["sub1"],
                                window_days=30, min_confidence=0.5)
        # Inject the fake synthesizer through from_settings.
        monkeypatch.setattr(
            "app.core.digest_runner.DigestSynthesizer.from_settings",
            classmethod(lambda cls: FakeSynth()),
        )
        worker = DigestRunner()
        processed = await worker.tick()
        assert processed == 1
        assert js.get_latest_digest_run("d1")["status"] == "ok"

    @pytest.mark.asyncio
    async def test_start_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "digest_enabled", False)
        worker = DigestRunner()
        await worker.start()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, monkeypatch, stores):
        monkeypatch.setattr(get_settings(), "digest_enabled", True)

        async def noop(self):
            return 0

        monkeypatch.setattr(DigestRunner, "tick", noop)
        worker = DigestRunner()
        worker._check_interval = 0.001
        await worker.start()
        assert worker._running is True
        await worker.stop()
        assert worker._running is False
