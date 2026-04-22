"""Canonical knowledge extractor — turns a transcript into Claim records.

Phase A: claims-only. Entity / Topic / Prediction extraction lands in Phase B/C.

Pipeline per episode:
  1. Group TranscriptionSegments into ~3000-token chunks (preserving
     timestamps + speaker labels).
  2. For each chunk, ask the LLM (configured via `llm_presets` for the
     `extract` task) for a JSON `{claims: [...]}` response.
  3. Validate via `ClaimDraft`. Quarantine malformed chunks, never crash.
  4. Promote each draft to a `Claim` (stamp episode_id, source_url, version,
     compute stable claim_id).
  5. Drop claims below the storage floor (0.1).
  6. Upsert into JobStore — idempotent re-extraction.

Surface filtering (min_confidence per query) happens at the API layer, not
here. We persist everything above the sanity floor.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import ValidationError

from .knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    ChunkFailure,
    Claim,
    ClaimDraft,
    ExtractionRunResult,
    LLM_RESPONSE_SCHEMA,
    compute_claim_id,
)
from .llm_presets import TaskType, get_provider_for_task
from .summarizer import LiteLLMProvider

logger = logging.getLogger(__name__)

# Anything below this is dropped at extraction time (sanity floor).
# Surface thresholds (API=0.5, UI=0.6, digest=0.7) are applied at the
# query/render layer instead.
STORAGE_CONFIDENCE_FLOOR = 0.1

# Approximate chunk size in *tokens* — 1 token ≈ 0.75 words for English.
# 3000 tokens of transcript fits comfortably in any modern model's window
# while leaving plenty of room for the prompt and JSON response.
CHUNK_TARGET_TOKENS = 3000
CHUNK_OVERLAP_TOKENS = 200
WORDS_PER_TOKEN = 0.75


SYSTEM_PROMPT = (
    "You extract structured CLAIMS from podcast/audio transcript segments. "
    "A claim is a discrete, citable, time-bound statement made by a speaker.\n\n"
    "Each claim must be:\n"
    "- Standalone (understandable without the surrounding context)\n"
    "- Attributed to a speaker when one is identified\n"
    "- Supported by a verbatim excerpt from the transcript\n"
    "- Categorized as: fact, opinion, prediction, question, or recommendation\n\n"
    "Confidence guidelines:\n"
    "- 0.9+: directly stated, unambiguous\n"
    "- 0.7-0.9: clearly stated but mildly interpreted\n"
    "- 0.5-0.7: implied or partially supported\n"
    "- 0.1-0.5: weak inference\n\n"
    "Skip filler, small talk, and non-substantive segments — quality over quantity. "
    "Respond with a JSON object matching the requested schema. No prose."
)


def _format_segments_for_prompt(segments: list[dict]) -> str:
    """Render a chunk of transcript segments with timestamp + speaker tags.

    Output looks like:
        [123.4-128.1] (Speaker A): Some text...
        [128.1-130.0]: Untagged text...
    """
    lines: list[str] = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        speaker = seg.get("speaker")
        prefix = f"[{start:.1f}-{end:.1f}]"
        if speaker:
            prefix += f" ({speaker})"
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{prefix}: {text}")
    return "\n".join(lines)


def _chunk_segments(segments: list[dict]) -> list[list[dict]]:
    """Pack segments into ~CHUNK_TARGET_TOKENS-sized chunks with overlap.

    We split at segment boundaries (never inside a segment) so timestamps and
    speaker attribution stay intact. Overlap helps the LLM see context for
    claims that span the chunk boundary.
    """
    target_words = int(CHUNK_TARGET_TOKENS * WORDS_PER_TOKEN)
    overlap_words = int(CHUNK_OVERLAP_TOKENS * WORDS_PER_TOKEN)

    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_words = 0
    i = 0
    while i < len(segments):
        seg = segments[i]
        seg_words = len((seg.get("text") or "").split())
        if current_words + seg_words > target_words and current:
            chunks.append(current)
            # Build overlap by walking back from the end of the current chunk
            overlap: list[dict] = []
            ow = 0
            for back in reversed(current):
                bw = len((back.get("text") or "").split())
                if ow + bw > overlap_words:
                    break
                overlap.insert(0, back)
                ow += bw
            current = list(overlap)
            current_words = ow
        current.append(seg)
        current_words += seg_words
        i += 1
    if current:
        chunks.append(current)
    return chunks


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(raw: str) -> dict:
    """Parse the LLM's response as JSON, tolerating markdown fences and prose."""
    raw = raw.strip()
    # Strip ```json ... ``` fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: pull the first {...} block out of any prose
        match = _JSON_BLOCK_RE.search(raw)
        if not match:
            raise
        return json.loads(match.group(0))


class KnowledgeExtractor:
    """Service that runs claims extraction over a transcript."""

    def __init__(self, provider: Optional[LiteLLMProvider] = None):
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "KnowledgeExtractor":
        """Build an extractor using the `extract` task preset."""
        return cls(provider=get_provider_for_task(TaskType.EXTRACT))

    @staticmethod
    def is_available() -> bool:
        """Quick availability check — does any provider answer the `extract` task?"""
        provider = get_provider_for_task(TaskType.EXTRACT)
        return provider is not None and provider.is_available()

    async def extract_claims(
        self,
        *,
        episode_id: str,
        segments: list[dict],
        source_url: Optional[str] = None,
    ) -> ExtractionRunResult:
        """Run claims extraction against a list of TranscriptionSegment dicts.

        Each `seg` must look like {start, end, text, speaker?}. Returns an
        `ExtractionRunResult` with the produced claims plus run metadata.
        Persistence is the caller's responsibility (route handler / pipeline).
        """
        if not self.provider:
            return ExtractionRunResult(
                job_id=episode_id,
                success=False,
                error="No LLM provider configured for the `extract` task.",
            )
        if not segments:
            return ExtractionRunResult(
                job_id=episode_id,
                success=True,
                error=None,
            )

        chunks = _chunk_segments(segments)
        logger.info(
            "knowledge_extractor: episode=%s chunks=%d segments=%d",
            episode_id,
            len(chunks),
            len(segments),
        )

        all_claims: list[Claim] = []
        failures: list[ChunkFailure] = []
        total_tokens = 0

        for idx, chunk in enumerate(chunks):
            transcript_text = _format_segments_for_prompt(chunk)
            user_prompt = (
                "Extract claims from the transcript segment below. "
                "Return JSON only, conforming to this schema:\n\n"
                f"{json.dumps(LLM_RESPONSE_SCHEMA, indent=2)}\n\n"
                "Transcript segment:\n"
                f"{transcript_text}\n"
            )
            # `content` is captured outside the try so the except can attach
            # the raw LLM output to the quarantine record (None when the LLM
            # call itself failed before producing any text).
            content: Optional[str] = None
            try:
                content, tokens = await self.provider.generate(
                    prompt=user_prompt, system_prompt=SYSTEM_PROMPT
                )
                total_tokens += tokens or 0
                payload = _parse_llm_json(content)
                drafts = payload.get("claims", [])
                if not isinstance(drafts, list):
                    raise ValueError("`claims` field is not a list")
                for raw_claim in drafts:
                    try:
                        draft = ClaimDraft(**raw_claim)
                    except ValidationError as ve:
                        logger.debug(
                            "skipping malformed claim in chunk %d: %s", idx, ve
                        )
                        continue
                    if draft.confidence < STORAGE_CONFIDENCE_FLOOR:
                        continue
                    claim_id = compute_claim_id(
                        text=draft.text,
                        episode_id=episode_id,
                        speaker=draft.speaker,
                        timestamp_start=draft.timestamp_start,
                    )
                    all_claims.append(
                        Claim(
                            claim_id=claim_id,
                            episode_id=episode_id,
                            text=draft.text,
                            speaker=draft.speaker,
                            timestamp_start=draft.timestamp_start,
                            timestamp_end=draft.timestamp_end,
                            claim_type=draft.claim_type,
                            confidence=draft.confidence,
                            evidence_excerpt=draft.evidence_excerpt,
                            source_url=source_url,
                            extraction_version=EXTRACTION_VERSION,
                            schema_version=SCHEMA_VERSION,
                        )
                    )
            except Exception as e:
                logger.warning(
                    "knowledge_extractor: chunk %d failed: %s", idx, e
                )
                failures.append(
                    ChunkFailure(chunk_index=idx, error=str(e), raw_output=content)
                )

        # De-dup by claim_id (a claim could appear across overlapping chunks)
        deduped: dict[str, Claim] = {}
        for c in all_claims:
            existing = deduped.get(c.claim_id)
            if existing is None or c.confidence > existing.confidence:
                deduped[c.claim_id] = c

        # success = at least one chunk produced *something* (valid JSON, even
        # an empty claim list counts). If every chunk threw, we don't want the
        # caller to overwrite prior data with this run's empty result.
        all_failed = len(chunks) > 0 and len(failures) == len(chunks)
        run_success = not all_failed

        return ExtractionRunResult(
            job_id=episode_id,
            success=run_success,
            claims=list(deduped.values()),
            chunks_processed=len(chunks) - len(failures),
            chunks_failed=len(failures),
            failures=failures,
            tokens_used=total_tokens,
            model=self.provider.model_name,
            provider=self.provider.name,
            error=None if not failures else f"{len(failures)} chunk(s) failed",
        )
