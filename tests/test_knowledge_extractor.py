"""Tests for the knowledge extractor (P18 Phase A + B) — mocked LLM."""

from __future__ import annotations

import json
from typing import Optional

import pytest

from app.core.knowledge_extractor import (
    KnowledgeExtractor,
    STORAGE_CONFIDENCE_FLOOR,
    _chunk_segments,
    _format_segments_for_prompt,
    _parse_llm_json,
)
from app.core.knowledge_schema import ClaimType, Entity, EntityType


class _FakeCanonicalizer:
    """Deterministic canonicalizer for extractor tests.

    Assigns a stable `ent_fake_<n>` id per (normalized_name, type) and
    returns the same entity on every lookup so the extractor can be
    tested without embedding/DB round-trips.
    """

    def __init__(self):
        self._entities: dict[tuple[str, str], Entity] = {}
        self.calls: list[tuple[str, str]] = []

    async def canonicalize(self, *, name: str, entity_type, confidence: float = 1.0):
        from app.core.entity_canonicalizer import CanonicalizedEntity
        from app.core.knowledge_schema import normalize_entity_name

        etype = (
            entity_type
            if isinstance(entity_type, EntityType)
            else EntityType(entity_type)
        )
        key = (normalize_entity_name(name), etype.value)
        if not key[0]:
            return None
        if key in self._entities:
            entity = self._entities[key]
            if name.strip() and name.strip() not in entity.aliases:
                entity.aliases.append(name.strip())
            return CanonicalizedEntity(
                entity=entity, is_new=False, surface_form=name
            )
        entity_id = f"ent_fake_{len(self._entities):04d}"
        entity = Entity(
            entity_id=entity_id,
            slug=f"{etype.value}:{key[0].replace(' ', '-')}",
            name=name.strip(),
            entity_type=etype,
            aliases=[name.strip()],
            confidence=confidence,
        )
        self._entities[key] = entity
        self.calls.append(key)
        return CanonicalizedEntity(
            entity=entity, is_new=True, surface_form=name
        )


class _FakeProvider:
    """Stand-in for LiteLLMProvider that returns canned JSON responses."""

    def __init__(self, response: str, available: bool = True, tokens: int = 42):
        self.response = response
        self._available = available
        self.tokens = tokens
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


def _segs(*pairs: tuple[float, float, str, str | None]) -> list[dict]:
    return [
        {"start": s, "end": e, "text": t, "speaker": sp}
        for s, e, t, sp in pairs
    ]


# ---------- prompt formatting & JSON parsing ----------


def test_format_segments_with_speakers():
    segs = _segs(
        (1.0, 3.0, "Hello there.", "Host"),
        (3.5, 5.0, "Hi back.", None),
    )
    rendered = _format_segments_for_prompt(segs)
    assert "[1.0-3.0] (Host): Hello there." in rendered
    assert "[3.5-5.0]: Hi back." in rendered


def test_format_skips_empty_segments():
    segs = _segs((1.0, 2.0, "", "Host"), (2.0, 3.0, "real", "Host"))
    rendered = _format_segments_for_prompt(segs)
    assert rendered.count("[1.0-2.0]") == 0
    assert "[2.0-3.0]" in rendered


def test_parse_llm_json_strips_markdown_fence():
    raw = '```json\n{"claims": []}\n```'
    assert _parse_llm_json(raw) == {"claims": []}


def test_parse_llm_json_extracts_first_block_from_prose():
    raw = 'Here you go:\n{"claims": [{"text": "x"}]}\nLet me know.'
    parsed = _parse_llm_json(raw)
    assert parsed["claims"][0]["text"] == "x"


def test_parse_llm_json_raises_on_garbage():
    with pytest.raises(json.JSONDecodeError):
        _parse_llm_json("not json at all, no braces here")


# ---------- chunking ----------


def test_chunking_keeps_short_transcript_in_one_chunk():
    segs = _segs(*[(float(i), float(i + 1), f"word{i}", None) for i in range(5)])
    chunks = _chunk_segments(segs)
    assert len(chunks) == 1
    assert chunks[0] == segs


def test_chunking_splits_long_transcripts():
    # Each segment carries 100 words; ~22 segs comfortably exceed the 2250
    # word/3000 token target, forcing at least one split.
    segs = []
    for i in range(30):
        text = " ".join([f"w{j}" for j in range(100)])
        segs.append(
            {"start": float(i), "end": float(i + 1), "text": text, "speaker": None}
        )
    chunks = _chunk_segments(segs)
    assert len(chunks) >= 2


# ---------- end-to-end (mocked LLM) ----------


@pytest.mark.asyncio
async def test_extract_claims_happy_path():
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "ETH may outperform BTC in the next 6 months",
                    "speaker": "Host A",
                    "timestamp_start": 12.5,
                    "timestamp_end": 18.0,
                    "claim_type": "prediction",
                    "confidence": 0.85,
                    "evidence_excerpt": "I think ETH outperforms BTC by EOY",
                }
            ]
        }
    )
    extractor = KnowledgeExtractor(provider=_FakeProvider(response))

    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs(
            (10.0, 20.0, "Some discussion about ETH and BTC.", "Host A")
        ),
        source_url="https://x.com/space/1",
    )

    assert result.success is True
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.episode_id == "ep-1"
    assert claim.claim_type == ClaimType.PREDICTION
    assert claim.confidence == 0.85
    assert claim.source_url == "https://x.com/space/1"
    assert result.tokens_used == 42


@pytest.mark.asyncio
async def test_extract_drops_below_storage_floor():
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "weak signal",
                    "speaker": None,
                    "timestamp_start": 1.0,
                    "timestamp_end": 2.0,
                    "claim_type": "opinion",
                    "confidence": STORAGE_CONFIDENCE_FLOOR / 2,
                    "evidence_excerpt": "...",
                },
                {
                    "text": "strong signal",
                    "speaker": None,
                    "timestamp_start": 3.0,
                    "timestamp_end": 4.0,
                    "claim_type": "opinion",
                    "confidence": 0.9,
                    "evidence_excerpt": "...",
                },
            ]
        }
    )
    extractor = KnowledgeExtractor(provider=_FakeProvider(response))
    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs((1.0, 4.0, "lots of words here", None)),
    )
    assert len(result.claims) == 1
    assert result.claims[0].text == "strong signal"


@pytest.mark.asyncio
async def test_extract_all_chunks_failing_returns_failure():
    """When every chunk throws, success=False so the route doesn't wipe data."""
    extractor = KnowledgeExtractor(provider=_FakeProvider("totally not json"))
    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs((1.0, 4.0, "x", None)),
    )
    assert result.success is False
    assert result.claims == []
    assert result.chunks_failed >= 1
    assert result.error is not None
    # And the failure carries the raw output so quarantine has something to debug
    assert len(result.failures) == 1
    assert result.failures[0].chunk_index == 0
    assert "totally not json" in (result.failures[0].raw_output or "")


@pytest.mark.asyncio
async def test_extract_partial_failure_succeeds_overall():
    """When at least one chunk succeeds, the whole run is success=True so the
    successful chunks' claims still get persisted."""

    class _FlakyProvider(_FakeProvider):
        def __init__(self):
            super().__init__("")
            self._n = 0

        async def generate(self, prompt, system_prompt=""):
            self._n += 1
            if self._n == 1:
                # First chunk: returns a valid claim
                return (
                    json.dumps(
                        {
                            "claims": [
                                {
                                    "text": "first",
                                    "speaker": None,
                                    "timestamp_start": 0.0,
                                    "timestamp_end": 1.0,
                                    "claim_type": "fact",
                                    "confidence": 0.9,
                                    "evidence_excerpt": "...",
                                }
                            ]
                        }
                    ),
                    10,
                )
            # Subsequent chunks: garbage
            return "broken", 0

    long_segs = []
    for i in range(40):
        text = " ".join([f"w{j}" for j in range(100)])
        long_segs.append(
            {"start": float(i), "end": float(i + 1), "text": text, "speaker": None}
        )

    extractor = KnowledgeExtractor(provider=_FlakyProvider())
    result = await extractor.extract_claims(episode_id="ep-1", segments=long_segs)
    assert result.success is True
    assert len(result.claims) == 1
    assert result.chunks_failed >= 1
    assert len(result.failures) == result.chunks_failed


@pytest.mark.asyncio
async def test_extract_skips_invalid_claim_shapes():
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "ok",
                    "timestamp_start": 0.0,
                    "timestamp_end": 1.0,
                    "claim_type": "fact",
                    "confidence": 0.9,
                    "evidence_excerpt": "...",
                },
                {
                    # Missing required fields → ClaimDraft validation fails,
                    # this one is skipped silently.
                    "text": "broken",
                },
            ]
        }
    )
    extractor = KnowledgeExtractor(provider=_FakeProvider(response))
    result = await extractor.extract_claims(
        episode_id="ep-1", segments=_segs((0.0, 1.0, "x", None))
    )
    assert len(result.claims) == 1
    assert result.claims[0].text == "ok"


@pytest.mark.asyncio
async def test_extract_no_provider_returns_failure():
    extractor = KnowledgeExtractor(provider=None)
    result = await extractor.extract_claims(
        episode_id="ep-1", segments=_segs((1.0, 2.0, "x", None))
    )
    assert result.success is False
    assert "No LLM provider" in (result.error or "")


@pytest.mark.asyncio
async def test_extract_empty_segments_short_circuits():
    extractor = KnowledgeExtractor(provider=_FakeProvider("{}"))
    result = await extractor.extract_claims(episode_id="ep-1", segments=[])
    assert result.success is True
    assert result.claims == []


@pytest.mark.asyncio
async def test_extract_dedupes_overlapping_chunks():
    """Same claim_id from two chunks should collapse to one record.

    We force a split by feeding many segments and have the fake provider
    return the same claim every chunk. The extractor should keep only one
    (the highest-confidence copy).
    """
    same_claim = {
        "text": "ETH outperforms",
        "speaker": "Host",
        "timestamp_start": 1.0,
        "timestamp_end": 2.0,
        "claim_type": "prediction",
        "confidence": 0.7,
        "evidence_excerpt": "...",
    }
    response = json.dumps({"claims": [same_claim]})
    extractor = KnowledgeExtractor(provider=_FakeProvider(response))

    long_segs = []
    for i in range(40):
        text = " ".join([f"w{j}" for j in range(100)])
        long_segs.append(
            {"start": float(i), "end": float(i + 1), "text": text, "speaker": "Host"}
        )

    result = await extractor.extract_claims(episode_id="ep-1", segments=long_segs)
    # Multiple chunks were processed
    assert result.chunks_processed >= 2
    # …but after dedup we keep just one claim
    assert len(result.claims) == 1


# ---------- Phase B: entities + mentions ----------


@pytest.mark.asyncio
async def test_extract_populates_entity_ids_on_claims():
    """Entities returned alongside claims should resolve into claim.entity_ids."""
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "ETH may outperform BTC",
                    "speaker": "Host A",
                    "timestamp_start": 1.0,
                    "timestamp_end": 2.0,
                    "claim_type": "prediction",
                    "confidence": 0.9,
                    "evidence_excerpt": "ETH may outperform BTC",
                    "entity_refs": ["ETH", "BTC"],
                }
            ],
            "entities": [
                {"name": "ETH", "entity_type": "ticker", "confidence": 0.95},
                {"name": "BTC", "entity_type": "ticker", "confidence": 0.95},
            ],
        }
    )
    extractor = KnowledgeExtractor(
        provider=_FakeProvider(response),
        canonicalizer=_FakeCanonicalizer(),
    )
    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs((1.0, 2.0, "ETH may outperform BTC soon.", "Host A")),
    )
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert len(claim.entity_ids) == 2
    # The canonicalizer mints `ent_fake_xxxx` ids
    assert all(eid.startswith("ent_fake_") for eid in claim.entity_ids)
    # Entities + mentions surface in the run result too
    assert len(result.entities) == 2
    assert len(result.mentions) >= 2  # one mention per claim-entity pair


@pytest.mark.asyncio
async def test_extract_entity_without_claim_still_persists():
    """An entity in the LLM response with no claim pointing at it should still
    appear in result.entities and get a chunk-level mention."""
    response = json.dumps(
        {
            "claims": [],
            "entities": [
                {"name": "OpenAI", "entity_type": "company", "confidence": 0.8},
            ],
        }
    )
    canon = _FakeCanonicalizer()
    extractor = KnowledgeExtractor(
        provider=_FakeProvider(response), canonicalizer=canon
    )
    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs((1.0, 2.0, "OpenAI released a new model.", None)),
    )
    assert len(result.entities) == 1
    assert result.entities[0].name == "OpenAI"
    # One chunk-level mention with claim_id=None
    unclaimed = [m for m in result.mentions if m.claim_id is None]
    assert len(unclaimed) == 1


@pytest.mark.asyncio
async def test_extract_claim_refs_name_not_in_entities_list():
    """Weak-signal tolerance: a claim references an entity the LLM didn't list
    in the top-level `entities` array. The canonicalizer should still resolve
    it (via `other` type fallback) instead of silently dropping the link."""
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "ElevenLabs has great TTS",
                    "speaker": None,
                    "timestamp_start": 1.0,
                    "timestamp_end": 2.0,
                    "claim_type": "opinion",
                    "confidence": 0.8,
                    "evidence_excerpt": "ElevenLabs is fantastic",
                    "entity_refs": ["ElevenLabs"],
                }
            ],
            "entities": [],  # LLM forgot to list it
        }
    )
    extractor = KnowledgeExtractor(
        provider=_FakeProvider(response), canonicalizer=_FakeCanonicalizer()
    )
    result = await extractor.extract_claims(
        episode_id="ep-1",
        segments=_segs((1.0, 2.0, "ElevenLabs is great.", None)),
    )
    assert len(result.claims) == 1
    # Fallback canonicalizer assigned an id
    assert len(result.claims[0].entity_ids) == 1


@pytest.mark.asyncio
async def test_extract_tolerates_missing_entities_field():
    """Phase A LLM output (no `entities` field) must still work — entities
    are a weak signal, not required."""
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "anything",
                    "timestamp_start": 0.0,
                    "timestamp_end": 1.0,
                    "claim_type": "fact",
                    "confidence": 0.9,
                    "evidence_excerpt": "...",
                }
            ]
            # no `entities` key
        }
    )
    extractor = KnowledgeExtractor(
        provider=_FakeProvider(response), canonicalizer=_FakeCanonicalizer()
    )
    result = await extractor.extract_claims(
        episode_id="ep-1", segments=_segs((0.0, 1.0, "x", None))
    )
    assert result.success is True
    assert len(result.claims) == 1
    assert result.entities == []


@pytest.mark.asyncio
async def test_extract_without_canonicalizer_keeps_phase_a_behavior():
    """When canonicalizer is None (Phase A caller), entity_refs are silently
    discarded and the run still succeeds with claims populated."""
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "something",
                    "timestamp_start": 0.0,
                    "timestamp_end": 1.0,
                    "claim_type": "fact",
                    "confidence": 0.9,
                    "evidence_excerpt": "...",
                    "entity_refs": ["X", "Y"],
                }
            ],
            "entities": [
                {"name": "X", "entity_type": "other", "confidence": 0.8},
            ],
        }
    )
    extractor = KnowledgeExtractor(
        provider=_FakeProvider(response), canonicalizer=None
    )
    result = await extractor.extract_claims(
        episode_id="ep-1", segments=_segs((0.0, 1.0, "x", None))
    )
    assert len(result.claims) == 1
    assert result.claims[0].entity_ids == []
    assert result.entities == []
    assert result.mentions == []
