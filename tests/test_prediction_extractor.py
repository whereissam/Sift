"""Tests for app/core/prediction_extractor.py — mocked LLM provider."""

from __future__ import annotations

import json
from typing import Optional

import pytest

from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)
from app.core.prediction_extractor import (
    MAX_PREDICTIONS_PER_CALL,
    PredictionExtractor,
    _format_predictions_for_prompt,
)


class _FakeProvider:
    def __init__(self, response: str, tokens: int = 17, available: bool = True):
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


def _claim(
    text: str,
    *,
    episode_id: str = "ep-1",
    timestamp_start: float = 1.0,
    speaker: Optional[str] = None,
    claim_type: ClaimType = ClaimType.PREDICTION,
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
        claim_type=claim_type,
        confidence=confidence,
        evidence_excerpt=text,
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )


class TestFormatter:
    def test_numbered_with_speaker(self):
        claims = [
            _claim("rates will fall", speaker="Host A"),
            _claim("BTC will hit 200k", speaker=None, timestamp_start=2.0),
        ]
        out = _format_predictions_for_prompt(claims)
        assert "[0] (Host A) rates will fall" in out
        assert "[1] BTC will hit 200k" in out


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_lifecycle_fields_extracted(self):
        response = json.dumps(
            {
                "predictions": [
                    {
                        "claim_index": 0,
                        "target_horizon": "end of 2026",
                        "conditions": "if Fed cuts rates",
                        "falsifiable_by": "BTC closing above $200k",
                    },
                    {
                        "claim_index": 1,
                        "target_horizon": None,
                        "conditions": None,
                        "falsifiable_by": "ETH/BTC ratio > 0.06",
                    },
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        claims = [
            _claim("BTC will hit 200k"),
            _claim("ETH will outperform", timestamp_start=2.0),
        ]
        preds, tokens = await ext.enrich(claims)
        assert tokens > 0
        assert len(preds) == 2
        by_id = {p.claim_id: p for p in preds}
        first = by_id[claims[0].claim_id]
        assert first.target_horizon == "end of 2026"
        assert first.falsifiable_by == "BTC closing above $200k"
        # Second has only a falsifier — partial extraction is allowed.
        second = by_id[claims[1].claim_id]
        assert second.target_horizon is None
        assert second.falsifiable_by == "ETH/BTC ratio > 0.06"


class TestFiltering:
    @pytest.mark.asyncio
    async def test_only_prediction_type_claims_enriched(self):
        # The provider response references claim_index 0 — but the
        # extractor must filter to prediction-type claims first, so
        # passing a fact + a prediction means the prediction (not the
        # fact) is at index 0 in the working list.
        response = json.dumps(
            {
                "predictions": [
                    {
                        "claim_index": 0,
                        "target_horizon": "soon",
                        "falsifiable_by": "thing happens",
                    }
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        fact = _claim("this is a fact", claim_type=ClaimType.FACT)
        pred = _claim(
            "BTC will hit 200k",
            claim_type=ClaimType.PREDICTION,
            timestamp_start=2.0,
        )
        preds, _ = await ext.enrich([fact, pred])
        assert len(preds) == 1
        assert preds[0].claim_id == pred.claim_id

    @pytest.mark.asyncio
    async def test_no_prediction_claims_returns_empty_without_calling_llm(self):
        provider = _FakeProvider("{}")
        ext = PredictionExtractor(provider=provider)
        only_facts = [
            _claim(f"fact {i}", claim_type=ClaimType.FACT, timestamp_start=float(i))
            for i in range(3)
        ]
        preds, tokens = await ext.enrich(only_facts)
        assert preds == []
        assert tokens == 0
        # LLM was not called — saved a round trip
        assert provider.calls == []


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_missing_provider_returns_empty(self):
        ext = PredictionExtractor(provider=None)
        preds, tokens = await ext.enrich([_claim("p")])
        assert (preds, tokens) == ([], 0)

    @pytest.mark.asyncio
    async def test_garbage_llm_output_returns_empty(self):
        ext = PredictionExtractor(provider=_FakeProvider("totally not json"))
        preds, tokens = await ext.enrich(
            [_claim(f"p{i}", timestamp_start=float(i)) for i in range(2)]
        )
        assert preds == []

    @pytest.mark.asyncio
    async def test_predictions_field_missing(self):
        ext = PredictionExtractor(
            provider=_FakeProvider('{"something_else": []}')
        )
        preds, tokens = await ext.enrich(
            [_claim(f"p{i}", timestamp_start=float(i)) for i in range(2)]
        )
        # Tokens still surface — we paid for the call even though the
        # shape was wrong.
        assert preds == []
        assert tokens > 0

    @pytest.mark.asyncio
    async def test_out_of_range_claim_index_dropped(self):
        response = json.dumps(
            {
                "predictions": [
                    {"claim_index": 99, "target_horizon": "soon"},
                    {"claim_index": 0, "target_horizon": "now"},
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        claims = [_claim("p1"), _claim("p2", timestamp_start=2.0)]
        preds, _ = await ext.enrich(claims)
        # Only the in-range index produces a prediction
        assert len(preds) == 1
        assert preds[0].claim_id == claims[0].claim_id

    @pytest.mark.asyncio
    async def test_all_null_lifecycle_fields_dropped(self):
        """Empty draft (every lifecycle field null) adds no signal — skip."""
        response = json.dumps(
            {
                "predictions": [
                    {
                        "claim_index": 0,
                        "target_horizon": None,
                        "conditions": None,
                        "falsifiable_by": None,
                    }
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        preds, _ = await ext.enrich([_claim("p")])
        assert preds == []

    @pytest.mark.asyncio
    async def test_malformed_draft_dropped_others_kept(self):
        # First entry is the wrong shape (claim_index missing); second
        # is well-formed. Extractor drops the bad one but still returns
        # the good one.
        response = json.dumps(
            {
                "predictions": [
                    {"target_horizon": "no index"},
                    {"claim_index": 0, "target_horizon": "now"},
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        preds, _ = await ext.enrich([_claim("p")])
        assert len(preds) == 1


class TestTruncation:
    @pytest.mark.asyncio
    async def test_oversized_input_truncated_to_highest_confidence(self):
        response = json.dumps(
            {
                "predictions": [
                    {"claim_index": 0, "target_horizon": "x"},
                ]
            }
        )
        ext = PredictionExtractor(provider=_FakeProvider(response))
        claims = []
        for i in range(MAX_PREDICTIONS_PER_CALL + 5):
            claims.append(
                _claim(
                    f"p{i}",
                    timestamp_start=float(i),
                    confidence=max(0.1, 1.0 - (i * 0.005)),
                )
            )
        preds, _ = await ext.enrich(claims)
        # Truncated input still produces predictions
        assert len(preds) == 1
