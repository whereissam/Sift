"""Tests for the annotations mixin on JobStore."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.job_store import JobStore, JobType


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    s = JobStore(db_path=tmp_path / "jobs.db")
    # Annotations FK ``jobs(job_id)``; tests need a parent row.
    s.create_job("j1", JobType.TRANSCRIBE)
    return s


def _create(store: JobStore, **overrides) -> dict:
    base = dict(
        annotation_id="a1",
        job_id="j1",
        user_id="u1",
        content="hello",
    )
    base.update(overrides)
    return store.create_annotation(**base)


class TestCreateAndGet:
    def test_round_trip(self, store: JobStore):
        a = _create(store, segment_start=1.0, segment_end=2.0, user_name="Alice")
        got = store.get_annotation("a1")
        assert got["id"] == "a1"
        assert got["content"] == "hello"
        assert got["segment_start"] == 1.0
        assert got["segment_end"] == 2.0
        assert got["user_name"] == "Alice"
        assert got["parent_id"] is None
        assert a["created_at"] == got["created_at"]

    def test_get_unknown_returns_none(self, store: JobStore):
        assert store.get_annotation("nope") is None


class TestGetForJob:
    def test_returns_only_top_level_excluding_replies(self, store: JobStore):
        # Top-level annotation
        _create(store, annotation_id="a1", content="parent", segment_start=1.0, segment_end=2.0)
        # Reply (has parent_id) should NOT appear in top-level list
        _create(store, annotation_id="r1", content="reply", parent_id="a1")
        rows = store.get_annotations_for_job("j1")
        assert [r["id"] for r in rows] == ["a1"]

    def test_orders_by_segment_start_then_created(self, store: JobStore):
        _create(store, annotation_id="a2", segment_start=5.0, segment_end=6.0)
        time.sleep(0.01)
        _create(store, annotation_id="a1", segment_start=1.0, segment_end=2.0)
        time.sleep(0.01)
        _create(store, annotation_id="a3", segment_start=5.0, segment_end=7.0)
        rows = store.get_annotations_for_job("j1")
        # a1 first (lowest start), then a2 (same start as a3 but older)
        assert [r["id"] for r in rows] == ["a1", "a2", "a3"]

    def test_time_range_filter(self, store: JobStore):
        _create(store, annotation_id="a1", segment_start=0.0, segment_end=10.0)
        _create(store, annotation_id="a2", segment_start=20.0, segment_end=30.0)
        rows = store.get_annotations_for_job("j1", segment_start=5.0, segment_end=8.0)
        # a1 overlaps the requested 5-8 range; a2 doesn't
        assert [r["id"] for r in rows] == ["a1"]

    def test_time_range_includes_unanchored_annotations(self, store: JobStore):
        # Annotations without segment_start are returned in any time-range
        # query — they're whole-episode notes.
        _create(store, annotation_id="anchor", segment_start=0.0, segment_end=1.0)
        _create(store, annotation_id="floating")  # no segment_start/end
        rows = store.get_annotations_for_job("j1", segment_start=100.0, segment_end=200.0)
        assert {r["id"] for r in rows} == {"floating"}


class TestReplies:
    def test_replies_ordered_oldest_first(self, store: JobStore):
        _create(store, annotation_id="a1")
        _create(store, annotation_id="r1", content="r1", parent_id="a1")
        time.sleep(0.01)
        _create(store, annotation_id="r2", content="r2", parent_id="a1")
        replies = store.get_annotation_replies("a1")
        assert [r["id"] for r in replies] == ["r1", "r2"]

    def test_get_with_replies(self, store: JobStore):
        _create(store, annotation_id="a1")
        _create(store, annotation_id="r1", content="r1", parent_id="a1")
        thread = store.get_annotation_with_replies("a1")
        assert thread["id"] == "a1"
        assert len(thread["replies"]) == 1
        assert thread["replies"][0]["id"] == "r1"

    def test_get_with_replies_unknown_returns_none(self, store: JobStore):
        assert store.get_annotation_with_replies("nope") is None


class TestUpdate:
    def test_update_content_and_returns_row(self, store: JobStore):
        _create(store)
        updated = store.update_annotation("a1", "new content")
        assert updated["content"] == "new content"
        # updated_at advanced
        assert updated["updated_at"] >= updated["created_at"]

    def test_update_unknown_returns_none(self, store: JobStore):
        assert store.update_annotation("nope", "x") is None


class TestDelete:
    def test_delete_returns_true_and_cascades_replies(self, store: JobStore):
        _create(store, annotation_id="a1")
        _create(store, annotation_id="r1", parent_id="a1")
        assert store.delete_annotation("a1") is True
        # Both annotation and its reply are gone
        assert store.get_annotation("a1") is None
        assert store.get_annotation("r1") is None

    def test_delete_unknown_returns_false(self, store: JobStore):
        assert store.delete_annotation("nope") is False
