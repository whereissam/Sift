"""Tests for app/core/topic_canonicalizer.py and topic_normalization.py.

Embedding model is mocked so every assertion runs in milliseconds. What
we care about is the canonicalizer's logic: normalization, cache, reuse
threshold (0.90), description-merge-on-reuse, and new-topic mint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import embedding_store
from app.core.embedding_store import (
    DEFAULT_TEXT_MODEL,
    EmbeddingStore,
    clear_embedding_cache,
)
from app.core.job_store import JobStore
from app.core.topic_canonicalizer import (
    COSINE_MATCH_THRESHOLD,
    TopicCanonicalizer,
)
from app.core.topic_normalization import (
    TICKER_MAP,
    _collapse_last_word_plural,
    normalize_topic_for_match,
)


class _ScriptedEncoder:
    """Encoder that returns vectors we control. Default → hash-based fallback."""

    def __init__(self, mapping: dict[str, list[float]]):
        self._mapping = mapping

    def encode(self, texts, convert_to_numpy: bool = True):
        import numpy as np

        out = []
        for t in texts:
            if t in self._mapping:
                out.append(self._mapping[t])
            else:
                seed = sum(ord(c) for c in t) % (2**31)
                rng = np.random.default_rng(seed)
                vec = rng.standard_normal(4).astype(np.float32)
                vec /= np.linalg.norm(vec) or 1.0
                out.append(vec.tolist())
        return np.asarray(out, dtype=np.float32)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = JobStore(db_path=tmp_path / "topics.db")
    estore = EmbeddingStore(db_path=str(db.db_path))
    clear_embedding_cache()

    mapping: dict[str, list[float]] = {
        # Two near-duplicates that should merge at 0.90.
        # Keys match the *fully normalized* embed text (the canonicalizer
        # runs normalize_topic_for_match on the name, joins with
        # description, then normalize_for_embedding lowercases the
        # whole string before encoding).
        "bitcoin price: bitcoin spot price trends": [1.0, 0.0, 0.0, 0.0],
        "bitcoin price action: recent price action for bitcoin": [0.95, 0.312, 0.0, 0.0],
        # An unrelated topic that must NOT merge with bitcoin price
        "ai safety: discussions about ai alignment risks": [0.0, 1.0, 0.0, 0.0],
    }
    encoder = _ScriptedEncoder(mapping)
    monkeypatch.setattr(embedding_store, "_load_model", lambda name: encoder)
    monkeypatch.setattr(embedding_store, "_loaded_model", encoder)
    monkeypatch.setattr(embedding_store, "_loaded_model_name", DEFAULT_TEXT_MODEL)

    return db, estore


def _canon(env) -> TopicCanonicalizer:
    db, estore = env
    return TopicCanonicalizer(job_store=db, embedding_store=estore)


class TestNormalization:
    def test_lowercases_and_collapses_whitespace(self):
        assert normalize_topic_for_match("  Bitcoin  Price  ") == "bitcoin price"

    def test_ticker_expansion_applied(self):
        assert normalize_topic_for_match("BTC prices") == "bitcoin price"

    def test_ticker_expansion_per_token_only(self):
        # "sol" as a token → "solana"; not substring-expanded inside a word.
        assert normalize_topic_for_match("SOL ecosystem") == "solana ecosystem"
        assert normalize_topic_for_match("solution") == "solution"

    def test_multiple_tickers_expand(self):
        assert normalize_topic_for_match("ETH vs BTC") == "ethereum vs bitcoin"

    def test_ticker_map_has_expected_entries(self):
        assert TICKER_MAP["btc"] == "bitcoin"
        assert TICKER_MAP["eth"] == "ethereum"
        assert TICKER_MAP["llm"] == "large language model"

    # Conservative plural tests
    def test_plural_collapsed_when_safe(self):
        assert _collapse_last_word_plural("ai agents") == "ai agent"
        assert _collapse_last_word_plural("bitcoin prices") == "bitcoin price"

    def test_short_words_not_collapsed(self):
        # "gas" is < 5 chars — leave alone
        assert _collapse_last_word_plural("gas") == "gas"
        # "news" is 4 chars — leave alone
        assert _collapse_last_word_plural("news") == "news"

    def test_ss_ending_not_collapsed(self):
        assert _collapse_last_word_plural("business") == "business"

    def test_us_ending_not_collapsed(self):
        # plural-looking but not a plural
        assert _collapse_last_word_plural("bonus") == "bonus"

    def test_ies_ending_not_collapsed(self):
        # -ies would need y-restore (cities → city, not citie)
        assert _collapse_last_word_plural("stories") == "stories"
        assert _collapse_last_word_plural("cities") == "cities"

    def test_only_last_word_affected(self):
        # "markets" last-word plural collapse should work
        assert _collapse_last_word_plural("crypto markets") == "crypto market"
        # But the first word in a multi-word phrase is left alone
        assert _collapse_last_word_plural("prices rise") == "prices rise"


class TestNewTopicMint:
    @pytest.mark.asyncio
    async def test_first_time_creates_new_topic(self, isolated_env):
        canon = _canon(isolated_env)
        result = await canon.canonicalize(
            name="Bitcoin Price",
            description="Bitcoin spot price trends",
        )
        assert result is not None
        assert result.is_new is True
        assert result.topic.topic_id.startswith("top_")
        assert len(result.topic.topic_id) == len("top_") + 8
        assert result.topic.name == "Bitcoin Price"
        assert result.topic.description == "Bitcoin spot price trends"
        assert "Bitcoin Price" in result.topic.aliases

    @pytest.mark.asyncio
    async def test_topic_id_stable_across_variants(self, isolated_env):
        """Ticker expansion + plural collapse → same topic_id for surface variants."""
        canon = _canon(isolated_env)
        r1 = await canon.canonicalize(name="BTC prices", description="")
        # Second canonicalizer / fresh run — must produce the same id via the
        # normalization pipeline.
        canon2 = _canon(isolated_env)
        r2 = await canon2.canonicalize(name="Bitcoin price", description="")
        assert r1.topic.topic_id == r2.topic.topic_id

    @pytest.mark.asyncio
    async def test_blank_name_returns_none(self, isolated_env):
        canon = _canon(isolated_env)
        assert await canon.canonicalize(name="") is None
        assert await canon.canonicalize(name="   ") is None


class TestCosineReuse:
    @pytest.mark.asyncio
    async def test_near_duplicate_reuses_existing(self, isolated_env):
        canon = _canon(isolated_env)
        first = await canon.canonicalize(
            name="Bitcoin Price", description="Bitcoin spot price trends"
        )
        # Fresh instance so we exercise the DB read path, not just run cache.
        canon2 = _canon(isolated_env)
        second = await canon2.canonicalize(
            name="Bitcoin price action",
            description="Recent price action for Bitcoin",
        )
        assert second is not None
        assert second.is_new is False
        assert second.topic.topic_id == first.topic.topic_id

    @pytest.mark.asyncio
    async def test_unrelated_topic_not_merged(self, isolated_env):
        canon = _canon(isolated_env)
        first = await canon.canonicalize(
            name="Bitcoin Price", description="Bitcoin spot price trends"
        )
        canon2 = _canon(isolated_env)
        second = await canon2.canonicalize(
            name="AI Safety",
            description="Discussions about AI alignment risks",
        )
        assert second.topic.topic_id != first.topic.topic_id

    @pytest.mark.asyncio
    async def test_threshold_is_higher_than_entities(self):
        # Guardrail — locking the 0.90 choice.
        assert COSINE_MATCH_THRESHOLD == 0.90
        # And strictly higher than the entity canonicalizer's 0.85.
        from app.core.entity_canonicalizer import (
            COSINE_MATCH_THRESHOLD as ENTITY_THRESHOLD,
        )

        assert COSINE_MATCH_THRESHOLD > ENTITY_THRESHOLD
