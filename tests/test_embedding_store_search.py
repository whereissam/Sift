"""Tests for embedding_store search / cache / normalize helpers (Phase B)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.core import embedding_store
from app.core.embedding_store import (
    DEFAULT_TEXT_MODEL,
    EmbeddingStore,
    clear_embedding_cache,
    embed,
    normalize_for_embedding,
)
from app.core.job_store import JobStore


class _FixedEncoder:
    """Deterministic encoder that returns seeded vectors per string."""

    def __init__(self, mapping: dict[str, list[float]]):
        self._mapping = mapping
        self.calls: list[list[str]] = []

    def encode(self, texts, convert_to_numpy: bool = True):
        self.calls.append(list(texts))
        vecs = [self._mapping[t] for t in texts]
        return np.asarray(vecs, dtype=np.float32)


@pytest.fixture
def store(tmp_path: Path) -> EmbeddingStore:
    # Use the JobStore to initialize the embeddings table schema.
    job_store = JobStore(db_path=tmp_path / "jobs.db")
    return EmbeddingStore(db_path=str(job_store.db_path))


class TestNormalize:
    def test_lowercases_and_trims(self):
        assert normalize_for_embedding("  Vitalik  ") == "vitalik"

    def test_collapses_whitespace(self):
        assert normalize_for_embedding("  A\t\tB \n C ") == "a b c"

    def test_empty_is_empty(self):
        assert normalize_for_embedding("") == ""
        assert normalize_for_embedding(None) == ""  # type: ignore[arg-type]


class TestQueryTopK:
    def test_returns_exact_match_on_top(self, store: EmbeddingStore):
        store.upsert(
            object_type="entity",
            object_id="ent_a",
            model="m",
            vector=[1.0, 0.0, 0.0],
        )
        store.upsert(
            object_type="entity",
            object_id="ent_b",
            model="m",
            vector=[0.0, 1.0, 0.0],
        )
        top = store.query_topk(
            object_type="entity", model="m", vector=[1.0, 0.0, 0.0], k=2
        )
        assert top[0][0] == "ent_a"
        assert top[0][1] == pytest.approx(1.0, abs=1e-5)
        assert top[1][0] == "ent_b"

    def test_filter_object_ids_scopes_candidates(self, store: EmbeddingStore):
        store.upsert(
            object_type="entity", object_id="a", model="m", vector=[1.0, 0.0]
        )
        store.upsert(
            object_type="entity", object_id="b", model="m", vector=[0.9, 0.1]
        )
        store.upsert(
            object_type="entity", object_id="c", model="m", vector=[0.8, 0.2]
        )
        top = store.query_topk(
            object_type="entity",
            model="m",
            vector=[1.0, 0.0],
            k=5,
            filter_object_ids=["b", "c"],
        )
        ids = {r[0] for r in top}
        assert ids == {"b", "c"}

    def test_zero_norm_query_returns_empty(self, store: EmbeddingStore):
        store.upsert(
            object_type="entity", object_id="a", model="m", vector=[1.0, 0.0]
        )
        assert store.query_topk(
            object_type="entity", model="m", vector=[0.0, 0.0]
        ) == []

    def test_mismatched_dim_rows_are_skipped(self, store: EmbeddingStore):
        store.upsert(
            object_type="entity",
            object_id="ok",
            model="m",
            vector=[1.0, 0.0, 0.0],
        )
        store.upsert(
            object_type="entity",
            object_id="stale",
            model="m",
            vector=[1.0, 0.0],  # wrong dim
        )
        top = store.query_topk(
            object_type="entity", model="m", vector=[1.0, 0.0, 0.0], k=5
        )
        assert {r[0] for r in top} == {"ok"}


class TestEmbedCache:
    def test_hit_does_not_re_encode(self, monkeypatch: pytest.MonkeyPatch):
        clear_embedding_cache()
        enc = _FixedEncoder({"hello": [1.0, 0.0]})
        monkeypatch.setattr(embedding_store, "_load_model", lambda name: enc)

        first = embed(["hello"], model=DEFAULT_TEXT_MODEL)
        second = embed(["hello"], model=DEFAULT_TEXT_MODEL)
        assert first == second
        # Only the first call should have triggered an encode pass.
        assert len(enc.calls) == 1

    def test_miss_batches_into_one_call(self, monkeypatch: pytest.MonkeyPatch):
        clear_embedding_cache()
        enc = _FixedEncoder(
            {
                "one": [1.0, 0.0],
                "two": [0.0, 1.0],
                "three": [0.5, 0.5],
            }
        )
        monkeypatch.setattr(embedding_store, "_load_model", lambda name: enc)

        out = embed(["one", "two", "three"], model=DEFAULT_TEXT_MODEL)
        assert len(out) == 3
        # One encode call for all three misses.
        assert len(enc.calls) == 1
        assert enc.calls[0] == ["one", "two", "three"]

    def test_mixed_hits_and_misses(self, monkeypatch: pytest.MonkeyPatch):
        clear_embedding_cache()
        enc = _FixedEncoder(
            {
                "a": [1.0, 0.0],
                "b": [0.0, 1.0],
            }
        )
        monkeypatch.setattr(embedding_store, "_load_model", lambda name: enc)

        embed(["a"], model=DEFAULT_TEXT_MODEL)
        # Now "a" is cached; only "b" should go to the encoder on this call.
        embed(["a", "b"], model=DEFAULT_TEXT_MODEL)
        # Two encode calls total, second only handles "b".
        assert len(enc.calls) == 2
        assert enc.calls[1] == ["b"]

    def test_normalized_key_collapses_case(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        clear_embedding_cache()
        enc = _FixedEncoder({"vitalik": [1.0, 0.0]})
        monkeypatch.setattr(embedding_store, "_load_model", lambda name: enc)

        embed(["VITALIK"], model=DEFAULT_TEXT_MODEL)
        embed(["  Vitalik  "], model=DEFAULT_TEXT_MODEL)
        # One call — both inputs normalize to "vitalik"
        assert len(enc.calls) == 1
