"""Tests for the P20 digest store (configs + runs + due-selection)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.job_store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "digest.db")


class TestConfigCRUD:
    def test_create_and_get(self, store: JobStore):
        cfg = store.create_digest_config(
            "d1", name="Crypto", subscription_ids=["s1", "s2"], window_days=14
        )
        assert cfg["digest_id"] == "d1"
        assert cfg["subscription_ids"] == ["s1", "s2"]
        assert cfg["window_days"] == 14
        assert cfg["enabled"] is True

    def test_list(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        store.create_digest_config("d2", name="B", subscription_ids=["s2"], enabled=False)
        assert len(store.list_digest_configs()) == 2
        assert {c["digest_id"] for c in store.list_digest_configs(enabled_only=True)} == {"d1"}

    def test_update_subscription_ids_roundtrip(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        updated = store.update_digest_config("d1", subscription_ids=["s1", "s2", "s3"])
        assert updated["subscription_ids"] == ["s1", "s2", "s3"]

    def test_update_unknown_returns_none(self, store: JobStore):
        assert store.update_digest_config("ghost", name="x") is None

    def test_delete_cascades_runs(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        store.save_digest_run("r1", "d1", status="ok")
        assert store.delete_digest_config("d1") is True
        assert store.get_digest_config("d1") is None
        assert store.get_digest_run("r1") is None


class TestDueSelection:
    def test_never_run_is_due(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        assert [c["digest_id"] for c in store.list_due_digests()] == ["d1"]

    def test_recently_run_not_due(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"], schedule_hours=24)
        store.set_digest_last_run("d1")
        assert store.list_due_digests() == []

    def test_elapsed_schedule_is_due(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"], schedule_hours=24)
        old = (datetime.utcnow() - timedelta(hours=48)).isoformat()
        store.update_digest_config("d1", last_run_at=old)
        assert [c["digest_id"] for c in store.list_due_digests()] == ["d1"]

    def test_disabled_never_due(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"], enabled=False)
        assert store.list_due_digests() == []


class TestRuns:
    def test_save_and_latest(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        store.save_digest_run("r1", "d1", status="ok", claim_count=5,
                              synthesis_json='{"headline": "x"}', markdown="# x")
        latest = store.get_latest_digest_run("d1")
        assert latest["run_id"] == "r1"
        assert latest["claim_count"] == 5
        assert latest["synthesis"] == {"headline": "x"}

    def test_list_orders_newest_first(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        store.save_digest_run("r1", "d1", status="ok")
        store.save_digest_run("r2", "d1", status="empty")
        runs = store.list_digest_runs("d1")
        assert [r["run_id"] for r in runs] == ["r2", "r1"]

    def test_latest_none_when_no_runs(self, store: JobStore):
        store.create_digest_config("d1", name="A", subscription_ids=["s1"])
        assert store.get_latest_digest_run("d1") is None
