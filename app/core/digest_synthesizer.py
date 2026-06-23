"""P20 cross-episode synthesis engine.

Takes claims gathered across several episodes (one window of a subscription set
or one topic) and asks the ``synthesize`` LLM preset to produce a structured
``DigestSynthesis``: themes, consensus, disagreements, predictions to track, and
repeated narratives. This is the differentiator over single-episode summaries —
it reads *across* sources.

Design mirrors ``knowledge_extractor``: resolve the provider from the task-preset
registry (never hardcode), JSON-mode prompting with defensive parsing, and
graceful degradation — too few claims or no provider returns a non-success
result rather than raising, so a digest run never crashes the worker.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from .digest_schema import DigestRunResult, DigestSynthesis
from .llm_presets import TaskType, get_provider_for_task
from .summarizer import LiteLLMProvider

logger = logging.getLogger(__name__)

# Below this, cross-source synthesis isn't meaningful — degrade to "empty".
MIN_CLAIMS_FOR_SYNTHESIS = 3
# Cap the claims fed to the model (highest-confidence first) to bound cost.
DEFAULT_MAX_CLAIMS = 200

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = (
    "You are a cross-source intelligence analyst. You are given claims extracted "
    "from MULTIPLE episodes (podcasts, talks, videos) over a time window. Your job "
    "is cross-source synthesis: what do the sources agree on, where do they "
    "disagree, which narratives repeat (and who amplifies them), and which "
    "forward-looking predictions are worth tracking. Attribute points to their "
    "source episode id. Do not summarize a single episode — synthesize across "
    "them. Respond with ONLY a JSON object, no prose."
)

_RESPONSE_SHAPE = """Return JSON with this exact shape:
{
  "headline": "one-sentence takeaway across all sources",
  "themes": [{"title": "...", "summary": "...", "episode_ids": ["..."], "source_count": 2}],
  "consensus": [{"statement": "...", "sources": ["episode_id", "..."]}],
  "disagreements": [{"topic": "...", "positions": [{"source": "episode_id", "stance": "..."}]}],
  "predictions": [{"text": "...", "source": "episode_id", "horizon": "Q4 2026 or null"}],
  "narratives": [{"narrative": "...", "amplifiers": ["episode_id", "..."]}]
}
Omit a section by returning an empty array. Keep it tight and signal-dense."""


def _parse_llm_json(raw: str) -> dict:
    """Parse the model response as JSON, tolerating fences and surrounding prose."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(raw)
        if not match:
            raise
        return json.loads(match.group(0))


def _format_claims_for_prompt(claims: list[dict], max_claims: int) -> str:
    """Render claims as compact, source-attributed lines for the prompt.

    Highest-confidence claims first so the cap keeps the strongest signal. Each
    line carries the source episode id, speaker, type, and text — enough for the
    model to attribute consensus/disagreement without the full transcript.
    """
    ordered = sorted(
        claims, key=lambda c: c.get("confidence") or 0.0, reverse=True
    )[:max_claims]
    lines = []
    for c in ordered:
        speaker = c.get("speaker") or "?"
        ctype = c.get("claim_type") or "claim"
        ep = c.get("episode_id") or "?"
        text = (c.get("text") or "").strip()
        lines.append(f"[{ep}] ({ctype}, {speaker}): {text}")
    return "\n".join(lines)


class DigestSynthesizer:
    """Cross-episode synthesizer over a list of claims."""

    def __init__(self, provider: Optional[LiteLLMProvider] = None):
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "DigestSynthesizer":
        """Build using the ``synthesize`` task preset (better model allowed)."""
        return cls(provider=get_provider_for_task(TaskType.SYNTHESIZE))

    async def synthesize(
        self,
        claims: list[dict],
        *,
        window_label: str = "",
        max_claims: int = DEFAULT_MAX_CLAIMS,
    ) -> DigestRunResult:
        """Synthesize across the given claims. Never raises for an expected
        degradation (no provider / too few claims / malformed output)."""
        episode_ids = {c.get("episode_id") for c in claims if c.get("episode_id")}
        base = {"episode_count": len(episode_ids), "claim_count": len(claims)}

        if len(claims) < MIN_CLAIMS_FOR_SYNTHESIS:
            return DigestRunResult(
                success=False,
                error=f"Too few claims ({len(claims)}) for cross-source synthesis.",
                **base,
            )
        if not self.provider:
            return DigestRunResult(
                success=False,
                error="No LLM provider configured for the `synthesize` task.",
                **base,
            )

        prompt = (
            (f"Time window: {window_label}\n\n" if window_label else "")
            + f"Claims across {len(episode_ids)} episode(s):\n"
            + _format_claims_for_prompt(claims, max_claims)
            + "\n\n"
            + _RESPONSE_SHAPE
        )

        try:
            content, tokens = await self.provider.generate(prompt, SYSTEM_PROMPT)
        except Exception as e:  # noqa: BLE001 - provider/network failure
            logger.error("Digest synthesis LLM call failed: %s", e)
            return DigestRunResult(
                success=False, error=f"Synthesis call failed: {e}", **base
            )

        try:
            data = _parse_llm_json(content)
            synthesis = DigestSynthesis.model_validate(data)
        except Exception as e:  # noqa: BLE001 - malformed output, don't crash the run
            logger.warning("Digest synthesis returned unparseable output: %s", e)
            return DigestRunResult(
                success=False,
                error="Model returned malformed synthesis JSON.",
                tokens_used=tokens,
                model=self.provider.model_name,
                provider=self.provider.name,
                **base,
            )

        return DigestRunResult(
            success=True,
            synthesis=synthesis,
            tokens_used=tokens,
            model=self.provider.model_name,
            provider=self.provider.name,
            **base,
        )
