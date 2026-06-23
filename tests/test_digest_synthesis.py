"""Tests for the P20 digest schema renderer + cross-episode synthesizer.

Covers the deterministic markdown rendering and the synthesizer's three paths:
graceful degradation (too few claims / no provider), a successful structured
synthesis, and malformed-output handling — all without a real LLM.
"""

from __future__ import annotations

import json

import pytest

from app.core.digest_schema import (
    DigestSynthesis,
    render_digest_markdown,
)
from app.core.digest_synthesizer import (
    MIN_CLAIMS_FOR_SYNTHESIS,
    DigestSynthesizer,
    _format_claims_for_prompt,
)


def _claims(n: int, *, episode="e1"):
    return [
        {
            "episode_id": episode,
            "text": f"claim {i}",
            "claim_type": "fact",
            "confidence": 0.5 + i * 0.01,
            "speaker": "A",
        }
        for i in range(n)
    ]


class FakeProvider:
    def __init__(self, content="{}", tokens=120, *, fail=False):
        self._content = content
        self._tokens = tokens
        self._fail = fail
        self.model_name = "gpt-4o"
        self.name = "openai"

    async def generate(self, prompt, system_prompt=""):
        if self._fail:
            raise RuntimeError("provider exploded")
        return self._content, self._tokens


class TestMarkdown:
    def test_renders_all_sections(self):
        s = DigestSynthesis(
            headline="Big week in crypto",
            themes=[{"title": "BTC", "summary": "up", "source_count": 3}],
            consensus=[{"statement": "bullish on ETH", "sources": ["e1", "e2"]}],
            disagreements=[
                {"topic": "rates", "positions": [{"source": "e1", "stance": "cut"}]}
            ],
            predictions=[{"text": "BTC 200k", "source": "e2", "horizon": "Q4"}],
            narratives=[{"narrative": "supercycle", "amplifiers": ["e1"]}],
        )
        md = render_digest_markdown(s, title="Weekly", window_label="last 7 days")
        for needle in ("# Weekly", "Big week", "## Themes", "BTC", "## Consensus",
                       "## Disagreements", "rates", "## Predictions", "200k",
                       "## Narratives", "supercycle"):
            assert needle in md

    def test_empty_sections_omitted(self):
        md = render_digest_markdown(
            DigestSynthesis(headline="quiet"), title="T", window_label="w"
        )
        assert "## Themes" not in md
        assert "quiet" in md


class TestFormatClaims:
    def test_orders_by_confidence_and_caps(self):
        claims = _claims(10)
        out = _format_claims_for_prompt(claims, max_claims=3)
        lines = out.splitlines()
        assert len(lines) == 3
        # Highest-confidence claim (claim 9) comes first.
        assert "claim 9" in lines[0]


class TestSynthesizerDegradation:
    @pytest.mark.asyncio
    async def test_too_few_claims(self):
        synth = DigestSynthesizer(provider=FakeProvider())
        r = await synth.synthesize(_claims(MIN_CLAIMS_FOR_SYNTHESIS - 1))
        assert r.success is False
        assert "Too few claims" in r.error

    @pytest.mark.asyncio
    async def test_no_provider(self):
        r = await DigestSynthesizer(provider=None).synthesize(_claims(5))
        assert r.success is False
        assert "No LLM provider" in r.error
        # Counts still reported even on degradation.
        assert r.claim_count == 5

    @pytest.mark.asyncio
    async def test_provider_exception_is_handled(self):
        synth = DigestSynthesizer(provider=FakeProvider(fail=True))
        r = await synth.synthesize(_claims(5))
        assert r.success is False
        assert "Synthesis call failed" in r.error


class TestSynthesizerSuccess:
    @pytest.mark.asyncio
    async def test_parses_structured_output(self):
        payload = json.dumps(
            {
                "headline": "cross-source takeaway",
                "consensus": [{"statement": "bullish", "sources": ["e1", "e2"]}],
                "predictions": [{"text": "200k", "source": "e2"}],
            }
        )
        synth = DigestSynthesizer(provider=FakeProvider(content=payload, tokens=321))
        r = await synth.synthesize(_claims(6, episode="e1") + _claims(4, episode="e2"))
        assert r.success is True
        assert r.synthesis.headline == "cross-source takeaway"
        assert r.synthesis.consensus[0].statement == "bullish"
        assert r.tokens_used == 321
        assert r.model == "gpt-4o"
        assert r.episode_count == 2

    @pytest.mark.asyncio
    async def test_tolerates_markdown_fenced_json(self):
        fenced = "```json\n{\"headline\": \"hi\"}\n```"
        synth = DigestSynthesizer(provider=FakeProvider(content=fenced))
        r = await synth.synthesize(_claims(4))
        assert r.success is True
        assert r.synthesis.headline == "hi"

    @pytest.mark.asyncio
    async def test_malformed_json_is_handled(self):
        synth = DigestSynthesizer(provider=FakeProvider(content="not json at all"))
        r = await synth.synthesize(_claims(4))
        assert r.success is False
        assert "malformed" in r.error.lower()
        # Tokens still accounted even on a parse failure.
        assert r.tokens_used == 120
