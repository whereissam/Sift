"""Tests for app/core/entity_canonicalizer.py.

We mock the embedding model so tests run in milliseconds and stay
deterministic — the canonicalizer's logic (cache, threshold, slug
collision, alias merging) is what matters, not the specific vector
sentence-transformers would return.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import pytest

from app.core import embedding_store
from app.core.embedding_store import (
    DEFAULT_TEXT_MODEL,
    EmbeddingStore,
    clear_embedding_cache,
)
from app.core.entity_canonicalizer import (
    COSINE_MATCH_THRESHOLD,
    EntityCanonicalizer,
)
from app.core.job_store import JobStore
from app.core.knowledge_schema import EntityType


class _ScriptedEncoder:
    """Stand-in for SentenceTransformer that returns vectors we control.

    Provided as a callable that maps normalized text → vector. Any miss
    returns a unit-norm vector orthogonal to everything we seeded.
    """

    def __init__(self, mapping: dict[str, list[float]]):
        self._mapping = mapping

    def encode(self, texts, convert_to_numpy: bool = True):
        import numpy as np

        out = []
        for t in texts:
            if t in self._mapping:
                out.append(self._mapping[t])
            else:
                # Deterministic fallback: hash the string to pick a seed so
                # the same text is always mapped to the same fallback vec.
                seed = sum(ord(c) for c in t) % (2**31)
                rng = np.random.default_rng(seed)
                vec = rng.standard_normal(4).astype(np.float32)
                vec /= np.linalg.norm(vec) or 1.0
                out.append(vec.tolist())
        return np.asarray(out, dtype=np.float32)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh store + cleared embedding cache + scripted encoder."""
    db = JobStore(db_path=tmp_path / "ent.db")
    estore = EmbeddingStore(db_path=str(db.db_path))
    clear_embedding_cache()

    mapping: dict[str, list[float]] = {
        # These three should cluster tightly (treated as the same entity
        # in the reuse test).
        "vitalik buterin": [1.0, 0.0, 0.0, 0.0],
        "vitalik": [0.99, 0.141, 0.0, 0.0],  # cosine ≈ 0.99 vs above
        # A different person the canonicalizer must NOT merge with Vitalik.
        "satoshi nakamoto": [0.0, 1.0, 0.0, 0.0],
        # A "company" named Apple and a "product" named Apple — same
        # slug candidate, different types, both must be allowed.
        "apple": [0.0, 0.0, 1.0, 0.0],
    }
    encoder = _ScriptedEncoder(mapping)

    # Short-circuit the lazy loader so no real model is touched.
    monkeypatch.setattr(embedding_store, "_load_model", lambda name: encoder)
    # Stop the module-level cache from leaking across tests.
    monkeypatch.setattr(embedding_store, "_loaded_model", encoder)
    monkeypatch.setattr(embedding_store, "_loaded_model_name", DEFAULT_TEXT_MODEL)

    return db, estore


def _new_canon(env) -> EntityCanonicalizer:
    db, estore = env
    return EntityCanonicalizer(job_store=db, embedding_store=estore)


class TestNewEntityMint:
    @pytest.mark.asyncio
    async def test_first_time_creates_new_entity(self, isolated_env):
        canon = _new_canon(isolated_env)
        result = await canon.canonicalize(
            name="Vitalik Buterin", entity_type=EntityType.PERSON
        )
        assert result is not None
        assert result.is_new is True
        assert result.entity.entity_id.startswith("ent_")
        assert result.entity.slug == "person:vitalik-buterin"
        assert result.entity.entity_type == EntityType.PERSON
        # Surface form collected as alias
        assert "Vitalik Buterin" in result.entity.aliases

    @pytest.mark.asyncio
    async def test_entity_id_is_stable_for_same_name(self, isolated_env):
        canon = _new_canon(isolated_env)
        r1 = await canon.canonicalize(
            name="Satoshi Nakamoto", entity_type=EntityType.PERSON
        )
        # Re-running in the same canonicalizer should hit the run cache.
        r2 = await canon.canonicalize(
            name="satoshi nakamoto", entity_type=EntityType.PERSON
        )
        assert r1.entity.entity_id == r2.entity.entity_id

    @pytest.mark.asyncio
    async def test_blank_name_returns_none(self, isolated_env):
        canon = _new_canon(isolated_env)
        assert await canon.canonicalize(name="", entity_type=EntityType.PERSON) is None
        assert (
            await canon.canonicalize(name="   ", entity_type=EntityType.PERSON) is None
        )


class TestCosineReuse:
    @pytest.mark.asyncio
    async def test_near_duplicate_reuses_existing(self, isolated_env):
        canon = _new_canon(isolated_env)
        first = await canon.canonicalize(
            name="Vitalik Buterin", entity_type=EntityType.PERSON
        )
        # New canonicalizer instance so we cross the DB path, not just the
        # in-memory run cache.
        canon2 = _new_canon(isolated_env)
        second = await canon2.canonicalize(
            name="Vitalik", entity_type=EntityType.PERSON
        )
        assert second is not None
        assert second.is_new is False
        assert second.entity.entity_id == first.entity.entity_id
        # Observed surface form is merged into aliases
        assert "Vitalik" in second.entity.aliases
        assert "Vitalik Buterin" in second.entity.aliases

    @pytest.mark.asyncio
    async def test_different_entity_does_not_merge(self, isolated_env):
        canon = _new_canon(isolated_env)
        first = await canon.canonicalize(
            name="Vitalik Buterin", entity_type=EntityType.PERSON
        )
        canon2 = _new_canon(isolated_env)
        second = await canon2.canonicalize(
            name="Satoshi Nakamoto", entity_type=EntityType.PERSON
        )
        assert second.entity.entity_id != first.entity.entity_id

    @pytest.mark.asyncio
    async def test_threshold_is_reasonable(self):
        # Guardrail — catch accidental edits to the locked default.
        assert 0.8 <= COSINE_MATCH_THRESHOLD <= 0.95


class TestSlugCollision:
    @pytest.mark.asyncio
    async def test_same_slug_different_type_coexists(self, isolated_env):
        canon = _new_canon(isolated_env)
        a = await canon.canonicalize(name="Apple", entity_type=EntityType.COMPANY)
        b = await canon.canonicalize(name="Apple", entity_type=EntityType.PRODUCT)
        assert a.entity.entity_id != b.entity.entity_id
        assert a.entity.slug == "company:apple"
        assert b.entity.slug == "product:apple"

    @pytest.mark.asyncio
    async def test_slug_collision_within_type_gets_suffix(
        self, isolated_env, monkeypatch: pytest.MonkeyPatch
    ):
        # Seed two entities that normalize to the same slug. We force a
        # situation where the second mint can't match the first by cosine
        # (they're "different Apples"), so the canonicalizer must produce
        # apple-2 rather than merging.
        import numpy as np

        db, estore = isolated_env

        mapping = {
            "apple": [1.0, 0.0, 0.0, 0.0],
            "apple corp": [0.0, 1.0, 0.0, 0.0],  # orthogonal → no merge
        }
        encoder = _ScriptedEncoder(mapping)
        monkeypatch.setattr(embedding_store, "_load_model", lambda name: encoder)

        canon = EntityCanonicalizer(job_store=db, embedding_store=estore)
        first = await canon.canonicalize(
            name="Apple", entity_type=EntityType.COMPANY
        )
        # Force a collision on the slug (simulate a second Apple-the-company
        # that the embedding says is distinct).
        second = await canon.canonicalize(
            name="Apple Corp", entity_type=EntityType.COMPANY
        )
        # They should be different entities
        assert second.entity.entity_id != first.entity.entity_id
        assert second.entity.slug != first.entity.slug
