"""Second-pass prediction enrichment over `claim_type=prediction` claims.

Cousin of `topic_aggregator.py`. Runs once per episode after the chunk
loop validates claims, scoped to claims of `claim_type=prediction`.
Output is a `Prediction` row per (in-scope) claim with the lifecycle
input fields (`target_horizon`, `conditions`, `falsifiable_by`) the LLM
could extract.

Why a separate pass instead of folding the lifecycle fields into
`{claims, entities}`:

- Most claims are not predictions. Asking every chunk to also produce
  prediction lifecycle data wastes tokens on every fact/opinion.
- Lifecycle extraction is precision-sensitive. A short, single-purpose
  prompt is easier to debug and retry than a kitchen-sink one.
- Predictions are sparser than claims. One episode-level call is
  cheaper than N chunk-level ones when most chunks have zero
  predictions to enrich.

Reuses the `extract` task preset by default. Graceful-degradation
contract is identical to `TopicAggregator.aggregate`: never raise.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import ValidationError

from .knowledge_schema import (
    Claim,
    ClaimType,
    PREDICTION_EXTRACTION_SCHEMA,
    Prediction,
    PredictionDraft,
)
from .llm_presets import TaskType, get_provider_for_task
from .summarizer import LiteLLMProvider

logger = logging.getLogger(__name__)

# Cap how many prediction claims we feed into one enrichment call.
# Predictions are sparser than topics; this is set lower so the prompt
# stays short and the LLM doesn't have to manage a long index space.
MAX_PREDICTIONS_PER_CALL = 60


SYSTEM_PROMPT = (
    "You enrich PREDICTION claims with lifecycle metadata.\n\n"
    "For each numbered prediction, extract:\n"
    "- target_horizon: when the prediction should resolve. Free-form "
    "string — an absolute date ('2026-12-31'), a relative interval "
    "('within 6 months', 'by Q2 next year'), an event ('after the "
    "next halving'), or null if genuinely unspecified.\n"
    "- conditions: any preconditions the speaker stated ('if rates "
    "fall below 4%', 'assuming the bill passes'). Null if none.\n"
    "- falsifiable_by: what evidence would resolve the prediction true "
    "or false ('BTC closing above $200k', 'official approval from "
    "the FDA'). Null if the prediction is too vague to falsify.\n\n"
    "Be strict. If the speaker did not state something, return null "
    "rather than inventing a horizon or condition. Skip predictions "
    "you cannot enrich at all (don't emit empty all-null records).\n\n"
    "Respond with a JSON object matching the requested schema. No prose."
)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(raw: str) -> dict:
    """Tolerate markdown fences and prose around the JSON payload.

    Same shape as the parsers in `knowledge_extractor` and
    `topic_aggregator`; duplicated here to avoid a circular import.
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


def _format_predictions_for_prompt(claims: list[Claim]) -> str:
    """Render prediction claims with 0-indexed labels.

    Includes the speaker tag inline when present so the LLM has the
    attribution context it needs to reason about conditions ("if I'm
    elected" reads very differently with vs. without speaker).
    """
    lines: list[str] = []
    for i, c in enumerate(claims):
        prefix = f"[{i}]"
        if c.speaker:
            prefix += f" ({c.speaker})"
        lines.append(f"{prefix} {c.text}")
    return "\n".join(lines)


def _filter_prediction_claims(claims: list[Claim]) -> list[Claim]:
    return [c for c in claims if c.claim_type == ClaimType.PREDICTION]


class PredictionExtractor:
    """Service that runs the prediction enrichment pass."""

    def __init__(self, provider: Optional[LiteLLMProvider] = None):
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "PredictionExtractor":
        """Build an extractor using the `extract` task preset.

        We reuse `extract` rather than `summarize` because lifecycle
        extraction is closer to structured-data parsing than to
        summarization. If quality drops we'll revisit.
        """
        return cls(provider=get_provider_for_task(TaskType.EXTRACT))

    @staticmethod
    def is_available() -> bool:
        provider = get_provider_for_task(TaskType.EXTRACT)
        return provider is not None and provider.is_available()

    async def enrich(
        self, claims: list[Claim]
    ) -> tuple[list[Prediction], int]:
        """Return `(predictions, tokens_used)`.

        Filters to `claim_type=prediction` internally so callers can
        pass the full claims list without pre-filtering. Graceful
        degradation:

        - No provider / no prediction-type claims → `([], 0)` (LLM not
          called).
        - LLM throws / JSON unparseable → `([], 0)`.
        - LLM returned but `predictions` field missing or wrong type →
          `([], tokens_from_call)` so the cost surfaces even when the
          shape didn't.
        - Individual prediction draft fails validation → skipped, rest
          of the list still lands.
        - claim_index out of range → skipped (LLM occasionally
          hallucinates indices beyond the list it received).
        """
        if not self.provider:
            return [], 0

        prediction_claims = _filter_prediction_claims(claims)
        if not prediction_claims:
            return [], 0

        working = prediction_claims
        if len(working) > MAX_PREDICTIONS_PER_CALL:
            working = sorted(working, key=lambda c: c.confidence, reverse=True)[
                :MAX_PREDICTIONS_PER_CALL
            ]
            logger.info(
                "prediction_extractor: truncated %d predictions → %d",
                len(prediction_claims),
                MAX_PREDICTIONS_PER_CALL,
            )

        numbered = _format_predictions_for_prompt(working)
        user_prompt = (
            "Enrich the following prediction claims with lifecycle "
            "metadata. Return JSON only, conforming to this schema:\n\n"
            f"{json.dumps(PREDICTION_EXTRACTION_SCHEMA, indent=2)}\n\n"
            "Predictions:\n"
            f"{numbered}\n"
        )

        try:
            content, tokens = await self.provider.generate(
                prompt=user_prompt, system_prompt=SYSTEM_PROMPT
            )
            payload = _parse_llm_json(content)
        except Exception as e:
            logger.warning("prediction_extractor: LLM call failed: %s", e)
            return [], 0

        drafts_raw = payload.get("predictions", [])
        if not isinstance(drafts_raw, list):
            logger.warning(
                "prediction_extractor: `predictions` field missing or not a list"
            )
            return [], tokens or 0

        out: dict[str, Prediction] = {}
        for raw in drafts_raw:
            if not isinstance(raw, dict):
                continue
            idx = raw.get("claim_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(working):
                logger.debug(
                    "prediction_extractor: dropping out-of-range claim_index=%r",
                    idx,
                )
                continue
            try:
                draft = PredictionDraft(**raw)
            except ValidationError as ve:
                logger.debug("skipping malformed prediction draft: %s", ve)
                continue
            # Skip records where every lifecycle field is empty — they
            # add no signal beyond the claim itself.
            if not (draft.target_horizon or draft.conditions or draft.falsifiable_by):
                continue
            claim_id = working[idx].claim_id
            # Last-write-wins on duplicate claim_index from the LLM.
            out[claim_id] = Prediction(
                claim_id=claim_id,
                target_horizon=draft.target_horizon,
                conditions=draft.conditions,
                falsifiable_by=draft.falsifiable_by,
            )

        return list(out.values()), tokens or 0
