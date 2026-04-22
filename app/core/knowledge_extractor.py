"""Canonical knowledge extractor — turns a transcript into Claim records.

Phase A shipped claims-only. Phase B layers entities + per-claim entity
refs on top: one LLM call per chunk still, but the schema now asks for
`{claims, entities}` and each claim carries `entity_refs: [name]`.
Entity identity is resolved post-extraction via `EntityCanonicalizer`,
which is the source of truth.

Pipeline per episode:
  1. Group TranscriptionSegments into ~3000-token chunks (preserving
     timestamps + speaker labels).
  2. For each chunk, ask the LLM (configured via `llm_presets` for the
     `extract` task) for a JSON `{claims, entities}` response.
  3. Validate drafts. Quarantine malformed chunks, never crash.
  4. Canonicalize each extracted entity through the embedding-based
     canonicalizer → stable `entity_id`.
  5. Promote each claim draft to a `Claim` (stamp episode_id, compute
     stable claim_id, resolve `entity_refs` → `entity_ids` via the
     chunk's name→id map).
  6. Emit `EntityMention` rows with best-effort char offsets.
  7. Drop claims below the storage floor (0.1).

Surface filtering (min_confidence per query) happens at the API layer, not
here. We persist everything above the sanity floor.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import ValidationError

from .entity_canonicalizer import EntityCanonicalizer
from .knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    ChunkFailure,
    Claim,
    ClaimDraft,
    Entity,
    EntityDraft,
    EntityMention,
    ExtractionRunResult,
    LLM_RESPONSE_SCHEMA,
    compute_claim_id,
    normalize_entity_name,
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
    "You extract structured CLAIMS and ENTITIES from podcast/audio "
    "transcript segments.\n\n"
    "A CLAIM is a discrete, citable, time-bound statement made by a speaker. "
    "Each claim must be:\n"
    "- Standalone (understandable without the surrounding context)\n"
    "- Attributed to a speaker when one is identified\n"
    "- Supported by a verbatim excerpt from the transcript\n"
    "- Categorized as: fact, opinion, prediction, question, or recommendation\n"
    "- Optionally attached to `entity_refs` — names of entities the claim mentions\n\n"
    "An ENTITY is a person, company, ticker, project, product, or place that "
    "the transcript refers to. Use the `other` type sparingly when none of the "
    "named categories fit. Only list high-confidence entities — it is better "
    "to omit an ambiguous mention than to hallucinate identity.\n\n"
    "Confidence guidelines (apply to both claims and entities):\n"
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


def _find_char_span(chunk_text: str, needle: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort offset of `needle` within `chunk_text` (case-insensitive).

    Returns (None, None) when not found — char spans are a bonus for
    UI highlighting, never the primary anchor. Timestamp remains the
    authoritative locator.
    """
    if not chunk_text or not needle:
        return None, None
    idx = chunk_text.lower().find(needle.lower())
    if idx < 0:
        return None, None
    return idx, idx + len(needle)


def _chunk_timestamp(chunk: list[dict]) -> Optional[float]:
    for seg in chunk:
        start = seg.get("start")
        if start is not None:
            try:
                return float(start)
            except (TypeError, ValueError):
                pass
    return None


def _chunk_speaker(chunk: list[dict]) -> Optional[str]:
    for seg in chunk:
        sp = seg.get("speaker")
        if sp:
            return sp
    return None


class KnowledgeExtractor:
    """Service that runs claims + entities extraction over a transcript."""

    def __init__(
        self,
        provider: Optional[LiteLLMProvider] = None,
        canonicalizer: Optional[EntityCanonicalizer] = None,
    ):
        self.provider = provider
        # Canonicalizer is optional: tests inject a lightweight fake, and
        # Phase A callers that don't need entity resolution can pass None
        # — in that case `entity_refs` is silently discarded.
        self.canonicalizer = canonicalizer

    @classmethod
    def from_settings(cls) -> "KnowledgeExtractor":
        """Build an extractor using the `extract` task preset."""
        return cls(
            provider=get_provider_for_task(TaskType.EXTRACT),
            canonicalizer=EntityCanonicalizer(),
        )

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
        """Run claims + entity extraction against transcript segments.

        Each `seg` must look like {start, end, text, speaker?}. Returns an
        `ExtractionRunResult` with claims, canonicalized entities, and
        mentions plus run metadata. Persistence is the caller's
        responsibility (route handler / pipeline) so we can keep retries
        and tx boundaries where they belong.
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
        # entity_id → Entity (run-level uniqueness; canonicalizer merges
        # aliases across chunks automatically).
        all_entities: dict[str, Entity] = {}
        all_mentions: list[EntityMention] = []
        failures: list[ChunkFailure] = []
        total_tokens = 0

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{episode_id}:chunk:{idx}"
            chunk_text = _format_segments_for_prompt(chunk)
            chunk_timestamp = _chunk_timestamp(chunk)
            chunk_speaker = _chunk_speaker(chunk)
            user_prompt = (
                "Extract claims AND entities from the transcript segment below. "
                "Return JSON only, conforming to this schema:\n\n"
                f"{json.dumps(LLM_RESPONSE_SCHEMA, indent=2)}\n\n"
                "Transcript segment:\n"
                f"{chunk_text}\n"
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
                claim_drafts_raw = payload.get("claims", [])
                if not isinstance(claim_drafts_raw, list):
                    raise ValueError("`claims` field is not a list")
                entity_drafts_raw = payload.get("entities", [])
                if not isinstance(entity_drafts_raw, list):
                    # Tolerate missing/wrong-type entities — it's a weak
                    # signal. Don't fail the whole chunk.
                    entity_drafts_raw = []

                # --- Canonicalize entities first so claims can reference them ---
                name_to_entity_id: dict[str, str] = {}
                chunk_entities: dict[str, Entity] = {}
                for raw_entity in entity_drafts_raw:
                    try:
                        ent_draft = EntityDraft(**raw_entity)
                    except ValidationError as ve:
                        logger.debug(
                            "skipping malformed entity in chunk %d: %s", idx, ve
                        )
                        continue
                    if not self.canonicalizer:
                        continue
                    canon = await self.canonicalizer.canonicalize(
                        name=ent_draft.name,
                        entity_type=ent_draft.entity_type,
                        confidence=ent_draft.confidence,
                    )
                    if canon is None:
                        continue
                    name_to_entity_id[
                        normalize_entity_name(ent_draft.name)
                    ] = canon.entity.entity_id
                    chunk_entities[canon.entity.entity_id] = canon.entity
                    all_entities[canon.entity.entity_id] = canon.entity

                # --- Promote claim drafts into Claim records ---
                chunk_claims: list[Claim] = []
                for raw_claim in claim_drafts_raw:
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
                    resolved_entity_ids: list[str] = []
                    for ref in draft.entity_refs:
                        # Try the entities the LLM also listed in this
                        # chunk first (cheap in-memory map). If the claim
                        # mentions a name the LLM didn't include in the
                        # `entities` array, canonicalize it on the spot —
                        # weak-signal handling without losing the link.
                        key = normalize_entity_name(ref)
                        if not key:
                            continue
                        entity_id = name_to_entity_id.get(key)
                        if entity_id is None and self.canonicalizer:
                            canon = await self.canonicalizer.canonicalize(
                                name=ref,
                                entity_type="other",
                                confidence=0.5,
                            )
                            if canon is not None:
                                entity_id = canon.entity.entity_id
                                name_to_entity_id[key] = entity_id
                                chunk_entities[entity_id] = canon.entity
                                all_entities[entity_id] = canon.entity
                        if entity_id and entity_id not in resolved_entity_ids:
                            resolved_entity_ids.append(entity_id)
                    chunk_claims.append(
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
                            entity_ids=resolved_entity_ids,
                            source_url=source_url,
                            extraction_version=EXTRACTION_VERSION,
                            schema_version=SCHEMA_VERSION,
                        )
                    )
                all_claims.extend(chunk_claims)

                # --- Emit entity mentions for this chunk ---
                # Claim-anchored mentions: one per (claim, entity_id) pair.
                for claim in chunk_claims:
                    for entity_id in claim.entity_ids:
                        entity = chunk_entities.get(entity_id) or all_entities.get(
                            entity_id
                        )
                        surface = entity.name if entity else ""
                        s, e = _find_char_span(chunk_text, surface)
                        all_mentions.append(
                            EntityMention(
                                entity_id=entity_id,
                                episode_id=episode_id,
                                claim_id=claim.claim_id,
                                chunk_id=chunk_id,
                                raw_text=surface or entity_id,
                                start_char=s,
                                end_char=e,
                                timestamp=claim.timestamp_start,
                                speaker=claim.speaker,
                            )
                        )
                # Unreferenced entities still get one chunk-level mention so
                # downstream queries (`mentions for this entity`) return
                # something meaningful.
                referenced_ids = {
                    eid for claim in chunk_claims for eid in claim.entity_ids
                }
                for entity_id, entity in chunk_entities.items():
                    if entity_id in referenced_ids:
                        continue
                    s, e = _find_char_span(chunk_text, entity.name)
                    all_mentions.append(
                        EntityMention(
                            entity_id=entity_id,
                            episode_id=episode_id,
                            claim_id=None,
                            chunk_id=chunk_id,
                            raw_text=entity.name,
                            start_char=s,
                            end_char=e,
                            timestamp=chunk_timestamp,
                            speaker=chunk_speaker,
                        )
                    )
            except Exception as e:
                logger.warning(
                    "knowledge_extractor: chunk %d failed: %s", idx, e
                )
                failures.append(
                    ChunkFailure(chunk_index=idx, error=str(e), raw_output=content)
                )

        # De-dup claims by claim_id (overlapping chunks). Keep the
        # higher-confidence copy and merge entity_ids so we don't lose
        # links seen on only one side of the overlap.
        deduped: dict[str, Claim] = {}
        for c in all_claims:
            existing = deduped.get(c.claim_id)
            if existing is None:
                deduped[c.claim_id] = c
                continue
            merged_ids = list(existing.entity_ids)
            for eid in c.entity_ids:
                if eid not in merged_ids:
                    merged_ids.append(eid)
            if c.confidence > existing.confidence:
                winner = c.model_copy(update={"entity_ids": merged_ids})
            else:
                winner = existing.model_copy(update={"entity_ids": merged_ids})
            deduped[c.claim_id] = winner

        # success = at least one chunk produced *something* (valid JSON, even
        # an empty claim list counts). If every chunk threw, we don't want the
        # caller to overwrite prior data with this run's empty result.
        all_failed = len(chunks) > 0 and len(failures) == len(chunks)
        run_success = not all_failed

        return ExtractionRunResult(
            job_id=episode_id,
            success=run_success,
            claims=list(deduped.values()),
            entities=list(all_entities.values()),
            mentions=all_mentions,
            chunks_processed=len(chunks) - len(failures),
            chunks_failed=len(failures),
            failures=failures,
            tokens_used=total_tokens,
            model=self.provider.model_name,
            provider=self.provider.name,
            error=None if not failures else f"{len(failures)} chunk(s) failed",
        )
