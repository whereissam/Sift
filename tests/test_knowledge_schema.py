"""Tests for app/core/knowledge_schema.py."""

from __future__ import annotations

import pytest

from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimDraft,
    ClaimTopicEdge,
    ClaimType,
    Entity,
    EntityDraft,
    EntityMention,
    EntityType,
    LLM_RESPONSE_SCHEMA,
    TOPIC_AGGREGATION_SCHEMA,
    Topic,
    TopicDraft,
    compute_claim_id,
    compute_entity_id,
    compute_topic_id,
    normalize_entity_name,
    slugify_entity_name,
)


class TestClaimIdStability:
    def test_same_inputs_produce_same_id(self):
        a = compute_claim_id(
            text="ETH may outperform BTC",
            episode_id="ep-1",
            speaker="Host A",
            timestamp_start=12.34,
        )
        b = compute_claim_id(
            text="ETH may outperform BTC",
            episode_id="ep-1",
            speaker="Host A",
            timestamp_start=12.34,
        )
        assert a == b

    def test_text_case_insensitive(self):
        a = compute_claim_id(
            text="ETH outperforms",
            episode_id="ep-1",
            speaker="Host",
            timestamp_start=10.0,
        )
        b = compute_claim_id(
            text="eth outperforms",
            episode_id="ep-1",
            speaker="Host",
            timestamp_start=10.0,
        )
        assert a == b

    def test_episode_id_distinguishes(self):
        a = compute_claim_id(
            text="ETH outperforms", episode_id="ep-1", speaker="Host", timestamp_start=10.0
        )
        b = compute_claim_id(
            text="ETH outperforms", episode_id="ep-2", speaker="Host", timestamp_start=10.0
        )
        assert a != b

    def test_no_speaker_normalizes_to_empty(self):
        # "" and None should produce the same id (both map to "")
        a = compute_claim_id(
            text="t", episode_id="e", speaker=None, timestamp_start=1.0
        )
        b = compute_claim_id(text="t", episode_id="e", speaker="", timestamp_start=1.0)
        assert a == b

    def test_timestamp_rounded_to_one_decimal(self):
        a = compute_claim_id(
            text="t", episode_id="e", speaker="s", timestamp_start=12.34
        )
        b = compute_claim_id(
            text="t", episode_id="e", speaker="s", timestamp_start=12.36
        )
        # 12.34 -> 12.3, 12.36 -> 12.4 — different bucket
        assert a != b
        c = compute_claim_id(
            text="t", episode_id="e", speaker="s", timestamp_start=12.34
        )
        d = compute_claim_id(
            text="t", episode_id="e", speaker="s", timestamp_start=12.31
        )
        # Both round to 12.3
        assert c == d


class TestClaimDraft:
    def test_valid_minimum(self):
        draft = ClaimDraft(
            text="x",
            timestamp_start=0.0,
            timestamp_end=1.0,
            claim_type=ClaimType.OPINION,
            confidence=0.8,
            evidence_excerpt="x",
        )
        assert draft.speaker is None

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ClaimDraft(
                text="x",
                timestamp_start=0.0,
                timestamp_end=1.0,
                claim_type=ClaimType.FACT,
                confidence=1.5,
                evidence_excerpt="x",
            )

    def test_unknown_claim_type_rejected(self):
        with pytest.raises(Exception):
            ClaimDraft(
                text="x",
                timestamp_start=0.0,
                timestamp_end=1.0,
                claim_type="not-a-type",  # type: ignore[arg-type]
                confidence=0.5,
                evidence_excerpt="x",
            )


class TestClaim:
    def test_end_clamps_to_start_when_inverted(self):
        c = Claim(
            claim_id="abc",
            episode_id="ep",
            text="t",
            timestamp_start=10.0,
            timestamp_end=5.0,  # malformed; should clamp
            claim_type=ClaimType.FACT,
            confidence=0.8,
            evidence_excerpt="x",
        )
        assert c.timestamp_end == 10.0

    def test_default_versions(self):
        c = Claim(
            claim_id="abc",
            episode_id="ep",
            text="t",
            timestamp_start=0.0,
            timestamp_end=1.0,
            claim_type=ClaimType.FACT,
            confidence=0.8,
            evidence_excerpt="x",
        )
        assert c.extraction_version == EXTRACTION_VERSION
        assert c.schema_version == SCHEMA_VERSION


class TestLLMSchema:
    def test_lists_all_claim_types(self):
        enum_in_schema = LLM_RESPONSE_SCHEMA["properties"]["claims"]["items"][
            "properties"
        ]["claim_type"]["enum"]
        assert set(enum_in_schema) == {c.value for c in ClaimType}

    def test_lists_all_entity_types(self):
        enum_in_schema = LLM_RESPONSE_SCHEMA["properties"]["entities"]["items"][
            "properties"
        ]["entity_type"]["enum"]
        assert set(enum_in_schema) == {e.value for e in EntityType}

    def test_claims_item_has_entity_refs(self):
        props = LLM_RESPONSE_SCHEMA["properties"]["claims"]["items"]["properties"]
        assert "entity_refs" in props
        assert props["entity_refs"]["type"] == "array"


class TestEntityNameHelpers:
    def test_normalize_lowercases_and_strips(self):
        assert normalize_entity_name("  Vitalik Buterin  ") == "vitalik buterin"

    def test_normalize_collapses_whitespace(self):
        assert normalize_entity_name("Vitalik\t\tButerin") == "vitalik buterin"

    def test_slugify_kebab_cases(self):
        assert slugify_entity_name("Vitalik Buterin") == "vitalik-buterin"

    def test_slugify_strips_punctuation(self):
        assert slugify_entity_name("OpenAI, Inc.") == "openai-inc"

    def test_slugify_empty_falls_back(self):
        assert slugify_entity_name("   ") == "unknown"
        assert slugify_entity_name("") == "unknown"


class TestEntityIdStability:
    def test_same_input_same_id(self):
        a = compute_entity_id(name="Vitalik Buterin", entity_type=EntityType.PERSON)
        b = compute_entity_id(name="vitalik buterin", entity_type=EntityType.PERSON)
        # Normalization means casing doesn't change the id
        assert a == b
        assert a.startswith("ent_")
        assert len(a) == len("ent_") + 8

    def test_type_distinguishes(self):
        a = compute_entity_id(name="Apple", entity_type=EntityType.COMPANY)
        b = compute_entity_id(name="Apple", entity_type=EntityType.PRODUCT)
        assert a != b


class TestEntityModel:
    def test_minimum_valid_entity(self):
        e = Entity(
            entity_id="ent_12345678",
            slug="person:alice",
            name="Alice",
            entity_type=EntityType.PERSON,
        )
        assert e.aliases == []
        assert e.confidence == 1.0

    def test_entity_draft_requires_name_and_type(self):
        with pytest.raises(Exception):
            EntityDraft()  # type: ignore[call-arg]

    def test_entity_mention_defaults(self):
        m = EntityMention(
            entity_id="ent_12345678", episode_id="ep-1", raw_text="Alice"
        )
        assert m.claim_id is None
        assert m.start_char is None
        assert m.timestamp is None


class TestClaimDraftEntityRefs:
    def test_entity_refs_default_empty(self):
        d = ClaimDraft(
            text="x",
            timestamp_start=0.0,
            timestamp_end=1.0,
            claim_type=ClaimType.FACT,
            confidence=0.9,
            evidence_excerpt="x",
        )
        assert d.entity_refs == []

    def test_entity_refs_roundtrip(self):
        d = ClaimDraft(
            text="x",
            timestamp_start=0.0,
            timestamp_end=1.0,
            claim_type=ClaimType.FACT,
            confidence=0.9,
            evidence_excerpt="x",
            entity_refs=["ETH", "BTC"],
        )
        assert d.entity_refs == ["ETH", "BTC"]


class TestTopicIdStability:
    def test_same_input_same_id(self):
        a = compute_topic_id(name="Bitcoin Price")
        b = compute_topic_id(name="  bitcoin  price  ")
        # Normalization collapses both surface forms to the same id
        assert a == b
        assert a.startswith("top_")
        assert len(a) == len("top_") + 8

    def test_ticker_variants_collapse(self):
        assert compute_topic_id(name="BTC") == compute_topic_id(name="Bitcoin")
        assert compute_topic_id(name="ETH prices") == compute_topic_id(
            name="Ethereum price"
        )

    def test_different_topic_different_id(self):
        a = compute_topic_id(name="Bitcoin price")
        b = compute_topic_id(name="AI safety")
        assert a != b


class TestTopicModel:
    def test_minimum_valid(self):
        t = Topic(topic_id="top_12345678", name="Bitcoin Price")
        assert t.description == ""
        assert t.aliases == []
        assert t.confidence == 1.0

    def test_topic_draft_defaults(self):
        d = TopicDraft(name="Bitcoin Price")
        assert d.description == ""
        assert d.confidence == 0.8
        assert d.claim_indices == []

    def test_claim_topic_edge_defaults(self):
        e = ClaimTopicEdge(claim_id="c", topic_id="top_12345678")
        assert e.confidence == 1.0


class TestTopicAggregationSchema:
    def test_requires_topics_array(self):
        assert "topics" in TOPIC_AGGREGATION_SCHEMA["required"]

    def test_topic_item_required_fields(self):
        topic_item = TOPIC_AGGREGATION_SCHEMA["properties"]["topics"]["items"]
        assert set(topic_item["required"]) == {"name", "claim_indices"}

    def test_claim_indices_is_integer_array(self):
        ci = TOPIC_AGGREGATION_SCHEMA["properties"]["topics"]["items"][
            "properties"
        ]["claim_indices"]
        assert ci["type"] == "array"
        assert ci["items"]["type"] == "integer"
