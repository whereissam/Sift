"""Tests for app/core/knowledge_schema.py."""

from __future__ import annotations

import pytest

from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimDraft,
    ClaimType,
    LLM_RESPONSE_SCHEMA,
    compute_claim_id,
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
