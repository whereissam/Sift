"""Second-pass topic aggregation over already-extracted claims.

Runs once per episode after the chunk-level `{claims, entities}` pass.
Input is the validated claims list; output is a small set of topics
plus claim↔topic edges. This is deliberately **not** fused into the
chunk loop:

- Claims are the distilled semantic units, topics are an abstraction
  over them. Feeding raw transcript to the topic prompt re-introduces
  noise the claim extractor already filtered out.
- Single-purpose prompts are easier to debug and retry.
- One episode-level LLM call is cheaper than N chunk-level ones when
  each chunk would emit near-duplicate topics.

Uses the `summarize` task preset (cheap-medium). `synthesize` is
reserved for P20 cross-episode work.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import ValidationError

from .knowledge_schema import (
    Claim,
    ClaimTopicEdge,
    Topic,
    TopicDraft,
    TOPIC_AGGREGATION_SCHEMA,
)
from .llm_presets import TaskType, get_provider_for_task
from .summarizer import LiteLLMProvider
from .topic_canonicalizer import TopicCanonicalizer

logger = logging.getLogger(__name__)

# Below this claim count, the aggregation pass is skipped — too little
# signal to justify the extra LLM call. Tuned to match the route trigger
# in `knowledge_extractor.py` so a manual aggregator run and an
# extractor run behave the same way.
MIN_CLAIMS_FOR_AGGREGATION = 3

# Cap how many claims we feed into one aggregation call. Summarize-tier
# models handle a few thousand tokens of claim text well; anything bigger
# and topic quality drops sharply (the model over-generalizes). If an
# episode has more, we truncate to the highest-confidence head and log.
MAX_CLAIMS_PER_CALL = 120


SYSTEM_PROMPT = (
    "You group a list of extracted CLAIMS from a podcast/audio transcript "
    "into coherent TOPICS.\n\n"
    "Each topic must be:\n"
    "- A short, canonical label (2-6 words, noun phrase preferred)\n"
    "- Accompanied by a one-sentence description of what the topic "
    "actually covers in *these* claims (not a generic dictionary "
    "definition)\n"
    "- Linked to the subset of claims it covers, by 0-indexed position "
    "in the claim list you are given\n\n"
    "Guidelines:\n"
    "- Prefer 3-10 topics per episode. Under 3 means the episode is too "
    "narrow to benefit from topic labels; over 10 usually means you're "
    "labeling individual claims instead of clusters.\n"
    "- A claim may belong to more than one topic. A topic must cover at "
    "least one claim. Claims unrelated to any coherent topic may be "
    "omitted.\n"
    "- Confidence 0.9+ for topics that span 3+ supporting claims with "
    "tight semantic overlap; 0.5-0.7 for single-claim or loosely related "
    "topics.\n\n"
    "Respond with a JSON object matching the requested schema. No prose."
)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(raw: str) -> dict:
    """Parse the LLM's response as JSON, tolerating markdown fences and prose.

    Duplicated from `knowledge_extractor` to avoid a circular import —
    both modules parse LLM output the same way but with their own
    module-level compiled regex, which is the right tradeoff for ~10
    lines of code.
    """
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


def _format_claims_for_prompt(claims: list[Claim]) -> str:
    """Render the claims list with 0-indexed labels.

    Keeping this simple — one claim per line prefixed with its index.
    The LLM cross-references by index in `claim_indices`.
    """
    return "\n".join(f"[{i}] {c.text}" for i, c in enumerate(claims))


class TopicAggregator:
    """Service that runs the topic aggregation pass."""

    def __init__(
        self,
        provider: Optional[LiteLLMProvider] = None,
        canonicalizer: Optional[TopicCanonicalizer] = None,
    ):
        self.provider = provider
        self.canonicalizer = canonicalizer

    @classmethod
    def from_settings(cls) -> "TopicAggregator":
        """Build an aggregator using the `summarize` task preset + a fresh canonicalizer."""
        return cls(
            provider=get_provider_for_task(TaskType.SUMMARIZE),
            canonicalizer=TopicCanonicalizer(),
        )

    @staticmethod
    def is_available() -> bool:
        provider = get_provider_for_task(TaskType.SUMMARIZE)
        return provider is not None and provider.is_available()

    async def aggregate(
        self, claims: list[Claim]
    ) -> tuple[list[Topic], list[ClaimTopicEdge], int]:
        """Return `(topics, edges, tokens_used)`.

        Graceful-degradation policy: never raise. Topic aggregation is
        additive signal and must never block the rest of the extraction
        pipeline. Degradation branches:

        - No provider / no canonicalizer / claim_count below
          `MIN_CLAIMS_FOR_AGGREGATION`  → `([], [], 0)` (LLM never
          called, so token count is genuinely zero).
        - LLM call throws / JSON unparseable → `([], [], 0)`.
        - LLM call succeeded but `topics` field is missing or malformed
          → `([], [], tokens_from_call)`. Tokens were spent on the call,
          so we surface the true cost; only the extracted shape is
          empty.
        """
        if not self.provider or not self.canonicalizer:
            return [], [], 0
        if len(claims) < MIN_CLAIMS_FOR_AGGREGATION:
            return [], [], 0

        # Cap the input size, keeping the highest-confidence claims if
        # we need to truncate.
        working = claims
        if len(working) > MAX_CLAIMS_PER_CALL:
            working = sorted(working, key=lambda c: c.confidence, reverse=True)[
                :MAX_CLAIMS_PER_CALL
            ]
            logger.info(
                "topic_aggregator: truncated %d claims → %d for aggregation",
                len(claims),
                MAX_CLAIMS_PER_CALL,
            )

        numbered = _format_claims_for_prompt(working)
        user_prompt = (
            "Group the following claims into topics. "
            "Return JSON only, conforming to this schema:\n\n"
            f"{json.dumps(TOPIC_AGGREGATION_SCHEMA, indent=2)}\n\n"
            "Claims:\n"
            f"{numbered}\n"
        )

        try:
            content, tokens = await self.provider.generate(
                prompt=user_prompt, system_prompt=SYSTEM_PROMPT
            )
            payload = _parse_llm_json(content)
        except Exception as e:
            logger.warning("topic_aggregator: LLM call failed: %s", e)
            return [], [], 0

        drafts_raw = payload.get("topics", [])
        if not isinstance(drafts_raw, list):
            logger.warning(
                "topic_aggregator: `topics` field missing or not a list"
            )
            return [], [], tokens or 0

        topics: list[Topic] = []
        seen_topic_ids: set[str] = set()
        edges: list[ClaimTopicEdge] = []
        for raw in drafts_raw:
            try:
                draft = TopicDraft(**raw)
            except ValidationError as ve:
                logger.debug("skipping malformed topic: %s", ve)
                continue
            canon = await self.canonicalizer.canonicalize(
                name=draft.name,
                description=draft.description,
                confidence=draft.confidence,
            )
            if canon is None:
                continue
            if canon.topic.topic_id not in seen_topic_ids:
                topics.append(canon.topic)
                seen_topic_ids.add(canon.topic.topic_id)
            for idx in draft.claim_indices:
                # Indices are relative to the list we fed into the
                # prompt (`working`). Out-of-range → skip rather than
                # corrupting edges. The LLM occasionally hallucinates an
                # index beyond the list it received.
                if idx < 0 or idx >= len(working):
                    logger.debug(
                        "topic_aggregator: dropping out-of-range claim_index=%d",
                        idx,
                    )
                    continue
                edges.append(
                    ClaimTopicEdge(
                        claim_id=working[idx].claim_id,
                        topic_id=canon.topic.topic_id,
                        confidence=draft.confidence,
                    )
                )

        return topics, edges, tokens or 0
