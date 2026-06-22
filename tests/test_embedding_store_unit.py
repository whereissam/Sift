"""Unit coverage for embedding_store's pure / DB paths that don't need the model.

The sentence-transformers model load is intentionally untested here (it would
download ~80MB); these cover the storage round-trip, cosine ranking, the cosine
helper, and the singleton/empty-input edges.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import job_store as job_store_module
from app.core.embedding_store import (
    EmbeddingStore,
    embed,
    get_embedding_store,
    normalize_for_embedding,
)
from app.core.job_store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    # Creates the `embeddings` table the EmbeddingStore reads/writes.
    return JobStore(db_path=tmp_path / "emb.db")


@pytest.fixture
def emb(store: JobStore) -> EmbeddingStore:
    return EmbeddingStore(db_path=str(store.db_path))


class TestNormalize:
    def test_empty(self):
        assert normalize_for_embedding("") == ""

    def test_collapses_and_lowercases(self):
        assert normalize_for_embedding("  Hello   World  ") == "hello world"


class TestEmbedEdge:
    def test_empty_batch_short_circuits(self):
        # No model load — empty input returns [] before touching the model.
        assert embed([]) == []


class TestStorageRoundTrip:
    def test_upsert_then_get(self, emb: EmbeddingStore):
        emb.upsert(object_type="entity", object_id="e1", model="m", vector=[1.0, 0.0, 0.0])
        got = emb.get(object_type="entity", object_id="e1", model="m")
        assert got == pytest.approx([1.0, 0.0, 0.0])

    def test_upsert_overwrites(self, emb: EmbeddingStore):
        emb.upsert(object_type="entity", object_id="e1", model="m", vector=[1.0, 0.0])
        emb.upsert(object_type="entity", object_id="e1", model="m", vector=[0.0, 1.0])
        assert emb.get(object_type="entity", object_id="e1", model="m") == pytest.approx([0.0, 1.0])

    def test_get_missing_returns_none(self, emb: EmbeddingStore):
        assert emb.get(object_type="entity", object_id="nope", model="m") is None


class TestQueryTopk:
    def test_ranks_by_cosine(self, emb: EmbeddingStore):
        emb.upsert(object_type="entity", object_id="near", model="m", vector=[1.0, 0.1])
        emb.upsert(object_type="entity", object_id="far", model="m", vector=[-1.0, 0.0])
        results = emb.query_topk(object_type="entity", model="m", vector=[1.0, 0.0], k=2)
        assert [oid for oid, _ in results] == ["near", "far"]
        assert results[0][1] > results[1][1]

    def test_zero_query_returns_empty(self, emb: EmbeddingStore):
        emb.upsert(object_type="entity", object_id="e1", model="m", vector=[1.0, 0.0])
        assert emb.query_topk(object_type="entity", model="m", vector=[0.0, 0.0]) == []

    def test_dim_mismatch_skipped(self, emb: EmbeddingStore):
        # A stale row of a different dimension must not crash the search.
        emb.upsert(object_type="entity", object_id="ok", model="m", vector=[1.0, 0.0])
        emb.upsert(object_type="entity", object_id="stale", model="m", vector=[1.0, 0.0, 0.0])
        results = emb.query_topk(object_type="entity", model="m", vector=[1.0, 0.0], k=5)
        assert [oid for oid, _ in results] == ["ok"]

    def test_filter_object_ids_scopes_candidates(self, emb: EmbeddingStore):
        emb.upsert(object_type="entity", object_id="a", model="m", vector=[1.0, 0.0])
        emb.upsert(object_type="entity", object_id="b", model="m", vector=[1.0, 0.0])
        results = emb.query_topk(
            object_type="entity", model="m", vector=[1.0, 0.0], k=5,
            filter_object_ids=["b"],
        )
        assert [oid for oid, _ in results] == ["b"]


class TestCosineHelper:
    def test_identical_is_one(self):
        assert EmbeddingStore.cosine([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

    def test_orthogonal_is_zero(self):
        assert EmbeddingStore.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_norm_is_zero(self):
        assert EmbeddingStore.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            EmbeddingStore.cosine([1.0], [1.0, 2.0])


class TestSingletonAndDefault:
    def test_get_embedding_store_is_singleton(self, monkeypatch, store: JobStore):
        monkeypatch.setattr(job_store_module, "_job_store", store)
        # Reset module singleton so the default db_path path runs.
        import app.core.embedding_store as es

        monkeypatch.setattr(es, "_default_store", None)
        a = get_embedding_store()
        b = get_embedding_store()
        assert a is b
        # Default db_path resolved off the job store.
        assert a.db_path == str(store.db_path)
