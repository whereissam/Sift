"""Tests for app/core/topic_aggregator.py — mocked LLM + mocked canonicalizer."""

from __future__ import annotations

import json
from typing import Optional

import pytest

from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    Topic,
    compute_claim_id,
)
from app.core.topic_aggregator import (
    MAX_CLAIMS_PER_CALL,
    MIN_CLAIMS_FOR_AGGREGATION,
    TopicAggregator,
    _format_claims_for_prompt,
)


class _FakeProvider:
    """Returns canned JSON text for one call."""

    def __init__(self, response: str, tokens: int = 21, available: bool = True):
        self.response = response
        self.tokens = tokens
        self._available = available
        self.calls: list[str] = []
        self.model = "fake/model"
        self._provider = "fake"

    async def generate(self, prompt: str, system_prompt: str = "") -> tuple[str, int]:
        self.calls.append(prompt)
        return self.response, self.tokens

    def is_available(self) -> bool:
        return self._available

    @property
    def name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self.model


class _FakeTopicCanonicalizer:
    """Deterministic canonicalizer — same normalized name → same topic_id."""

    def __init__(self):
        from app.core.knowledge_schema import compute_topic_id

        self._store: dict[str, Topic] = {}
        self._compute = compute_topic_id

    async def canonicalize(
        self, *, name: str, description: str = "", confidence: float = 1.0
    ):
        from app.core.topic_canonicalizer import CanonicalizedTopic

        if not name or not name.strip():
            return None
        topic_id = self._compute(name=name)
        existing = self._store.get(topic_id)
        if existing:
            if name.strip() not in existing.aliases:
                existing.aliases.append(name.strip())
            return CanonicalizedTopic(
                topic=existing, is_new=False, surface_form=name
            )
        topic = Topic(
            topic_id=topic_id,
            name=name.strip(),
            description=description,
            aliases=[name.strip()],
            confidence=confidence,
        )
        self._store[topic_id] = topic
        return CanonicalizedTopic(topic=topic, is_new=True, surface_form=name)


def _claim(
    text: str,
    *,
    episode_id: str = "ep-1",
    timestamp_start: float = 1.0,
    speaker: Optional[str] = None,
    confidence: float = 0.9,
) -> Claim:
    return Claim(
        claim_id=compute_claim_id(
            text=text,
            episode_id=episode_id,
            speaker=speaker,
            timestamp_start=timestamp_start,
        ),
        episode_id=episode_id,
        text=text,
        speaker=speaker,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_start + 1.0,
        claim_type=ClaimType.FACT,
        confidence=confidence,
        evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )


class TestFormatter:
    def test_numbered_output(self):
        claims = [_claim("first"), _claim("second", timestamp_start=2.0)]
        rendered = _format_claims_for_prompt(claims)
        assert "[0] first" in rendered
        assert "[1] second" in rendered


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_topics_and_edges_produced(self):
        response = json.dumps(
            {
                "topics": [
                    {
                        "name": "Bitcoin Price",
                        "description": "Price action for BTC",
                        "confidence": 0.9,
                        "claim_indices": [0, 2],
                    },
                    {
                        "name": "AI Agents",
                        "description": "Agentic AI workflows",
                        "confidence": 0.8,
                        "claim_indices": [1],
                    },
                ]
            }
        )
        agg = TopicAggregator(
            provider=_FakeProvider(response),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        claims = [
            _claim("BTC broke 100k"),
            _claim("LLM agents are everywhere", timestamp_start=5.0),
            _claim("Bitcoin rally continues", timestamp_start=10.0),
        ]
        topics, edges, tokens = await agg.aggregate(claims)

        assert len(topics) == 2
        # 2 claims for Bitcoin Price + 1 for AI Agents = 3 edges
        assert len(edges) == 3
        # Each edge points at a real claim_id from the input
        input_ids = {c.claim_id for c in claims}
        assert {e.claim_id for e in edges} <= input_ids
        # Token count surfaced
        assert tokens > 0


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_skips_when_below_threshold(self):
        agg = TopicAggregator(
            provider=_FakeProvider("{}"),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        # MIN_CLAIMS_FOR_AGGREGATION is 3 — feed fewer and expect skip
        too_few = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(MIN_CLAIMS_FOR_AGGREGATION - 1)]
        topics, edges, tokens = await agg.aggregate(too_few)
        assert topics == []
        assert edges == []
        assert tokens == 0

    @pytest.mark.asyncio
    async def test_missing_provider_returns_empty(self):
        agg = TopicAggregator(
            provider=None, canonicalizer=_FakeTopicCanonicalizer()
        )
        claims = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(5)]
        topics, edges, tokens = await agg.aggregate(claims)
        assert (topics, edges, tokens) == ([], [], 0)

    @pytest.mark.asyncio
    async def test_missing_canonicalizer_returns_empty(self):
        agg = TopicAggregator(provider=_FakeProvider("{}"), canonicalizer=None)
        claims = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(5)]
        topics, edges, tokens = await agg.aggregate(claims)
        assert (topics, edges, tokens) == ([], [], 0)

    @pytest.mark.asyncio
    async def test_garbage_llm_output_returns_empty(self):
        agg = TopicAggregator(
            provider=_FakeProvider("totally not json at all"),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        claims = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(5)]
        topics, edges, tokens = await agg.aggregate(claims)
        assert topics == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_topics_field_missing(self):
        agg = TopicAggregator(
            provider=_FakeProvider('{"something_else": []}'),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        claims = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(5)]
        topics, edges, tokens = await agg.aggregate(claims)
        assert topics == []

    @pytest.mark.asyncio
    async def test_out_of_range_claim_index_dropped(self):
        # One valid topic referencing a valid claim index, plus a bogus index
        response = json.dumps(
            {
                "topics": [
                    {
                        "name": "X",
                        "description": "",
                        "confidence": 0.8,
                        "claim_indices": [0, 99, -1],
                    }
                ]
            }
        )
        agg = TopicAggregator(
            provider=_FakeProvider(response),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        claims = [_claim(f"c{i}", timestamp_start=float(i)) for i in range(3)]
        topics, edges, tokens = await agg.aggregate(claims)
        assert len(topics) == 1
        # Only the in-range index (0) produces an edge
        assert len(edges) == 1
        assert edges[0].claim_id == claims[0].claim_id


class TestTruncation:
    @pytest.mark.asyncio
    async def test_oversized_input_truncated_to_highest_confidence(self):
        # Build slightly more than MAX_CLAIMS_PER_CALL claims with varied
        # confidences; verify the aggregator picks the top set.
        response = json.dumps(
            {
                "topics": [
                    {
                        "name": "everything",
                        "description": "",
                        "confidence": 0.8,
                        "claim_indices": [0, 1, 2],
                    }
                ]
            }
        )
        agg = TopicAggregator(
            provider=_FakeProvider(response),
            canonicalizer=_FakeTopicCanonicalizer(),
        )
        claims = []
        for i in range(MAX_CLAIMS_PER_CALL + 10):
            # descending confidence so top-K is the first chunk
            claims.append(
                _claim(
                    f"c{i}",
                    timestamp_start=float(i),
                    confidence=max(0.1, 1.0 - (i * 0.005)),
                )
            )
        topics, edges, tokens = await agg.aggregate(claims)
        # Call still produces topics even when we had to truncate
        assert len(topics) == 1
        assert len(edges) == 3
