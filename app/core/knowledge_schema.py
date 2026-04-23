"""Canonical Pydantic schema for the AI-friendly knowledge layer (P18).

Phase A scope: Claim only. Phase B adds Entity + EntityMention. Topic /
Prediction land in Phase C but the field hooks (entity_ids, topic_ids)
already exist on Claim so the storage layer doesn't change shape later.

A Claim is a discrete, citable, timestamped, speaker-attributed statement
extracted from a transcript. Every downstream system (MCP, Digest, RAG,
Search) reads from this same object.

Entities use dual identity: `entity_id` is a stable opaque PK
(`ent_<8-char hash>`) that claims and mentions reference, and `slug` is a
mutable human-readable label (`person:vitalik-buterin`) kept for
debug/API-surface ergonomics. Merges are pointer updates on `entity_id`,
never slug rewrites.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bump when the wire format changes in a way that requires re-extraction.
SCHEMA_VERSION = 1

# Default extraction prompt revision. Bump when the prompt changes; consumers
# can use this to identify records that should be re-extracted with the new
# prompt without throwing away the old ones.
EXTRACTION_VERSION = 1


class ClaimType(str, Enum):
    """Discrete categories for a claim."""

    FACT = "fact"
    OPINION = "opinion"
    PREDICTION = "prediction"
    QUESTION = "question"
    RECOMMENDATION = "recommendation"


class EntityType(str, Enum):
    """Discrete entity categories. Kept small — add types deliberately so
    downstream filters stay well-defined."""

    PERSON = "person"
    COMPANY = "company"
    TICKER = "ticker"
    PROJECT = "project"
    PRODUCT = "product"
    PLACE = "place"
    OTHER = "other"


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9\s-]+")
_SLUG_SPACE_RE = re.compile(r"[\s_]+")


def normalize_entity_name(name: str) -> str:
    """Canonical form for cache keys and cosine comparisons.

    Lowercase, strip surrounding whitespace, collapse internal whitespace
    runs. Intentionally conservative — anything more aggressive (stop-word
    removal, stemming) starts destroying signal the embedding model needs.
    """
    if not name:
        return ""
    return _SLUG_SPACE_RE.sub(" ", name.strip().lower())


def slugify_entity_name(name: str) -> str:
    """Kebab-case label fragment used in `slug` (after the type prefix).

    Only ASCII letters, digits, and single hyphens. Falls back to `unknown`
    for names that normalize to empty so we never produce `type:` with a
    blank tail.
    """
    base = normalize_entity_name(name)
    if not base:
        return "unknown"
    base = _SLUG_STRIP_RE.sub("", base)
    base = _SLUG_SPACE_RE.sub(" ", base).strip()
    parts = [p for p in base.split(" ") if p]
    return "-".join(parts) or "unknown"


def compute_entity_id(
    *, name: str, entity_type: "EntityType | str"
) -> str:
    """Stable opaque ID derived from normalized name + type.

    Same input → same `entity_id`, different inputs → different IDs with
    overwhelming probability. The hash collision boundary is not where we
    enforce cross-entity merging — the canonicalizer does that via cosine
    similarity on the embedding. This id exists to give every entity a
    readable-but-opaque PK that survives slug renames and merges.
    """
    etype = entity_type.value if isinstance(entity_type, EntityType) else entity_type
    payload = f"{etype}|{normalize_entity_name(name)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"ent_{digest[:8]}"


def compute_topic_id(*, name: str) -> str:
    """Stable opaque topic ID (`top_<8-char hash>`).

    Uses the full topic-normalization pipeline (ticker expansion +
    conservative plural collapse) so that `"BTC price"` and `"Bitcoin
    prices"` map to the same id before any embedding comparison runs.
    Hash collision is not the de-dup boundary — the canonicalizer does
    that via cosine ≥0.90 on `name + description`. This id exists so
    claims and join rows can point at something opaque and stable, even
    if we later rename a topic.
    """
    from .topic_normalization import normalize_topic_for_match

    payload = normalize_topic_for_match(name)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"top_{digest[:8]}"


class Claim(BaseModel):
    """A discrete, citable statement extracted from a transcript."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str = Field(
        description="Stable hash for cross-job dedup. Derived from text + episode + speaker + timestamp."
    )
    episode_id: str = Field(description="ID of the source job/episode.")
    text: str = Field(
        description="Self-contained restatement of the claim (understandable without surrounding context)."
    )
    speaker: Optional[str] = Field(
        default=None,
        description="Speaker label from diarization, if available.",
    )
    timestamp_start: float = Field(
        ge=0.0, description="Start of the supporting transcript region (seconds)."
    )
    timestamp_end: float = Field(
        ge=0.0, description="End of the supporting transcript region (seconds)."
    )
    claim_type: ClaimType = Field(description="Category of the claim.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model self-reported confidence in the extraction (0-1).",
    )
    evidence_excerpt: str = Field(
        description="Verbatim quote from the transcript that supports the claim."
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        description="Canonical entity IDs referenced by this claim (populated in Phase B).",
    )
    topic_ids: list[str] = Field(
        default_factory=list,
        description="Topic IDs this claim belongs to (populated in Phase C).",
    )
    source_url: Optional[str] = Field(
        default=None, description="URL of the source episode."
    )
    extraction_version: int = Field(
        default=EXTRACTION_VERSION,
        description="Prompt/extractor revision used to produce this claim.",
    )
    schema_version: int = Field(
        default=SCHEMA_VERSION, description="Wire-format version of this record."
    )
    created_at: Optional[datetime] = Field(
        default=None, description="Persisted by the store layer."
    )

    @field_validator("timestamp_end")
    @classmethod
    def _end_after_start(cls, v: float, info) -> float:
        start = info.data.get("timestamp_start")
        if start is not None and v < start:
            # Don't crash on bad LLM output — clamp to start so the claim is
            # still queryable. Quarantine logic flags zero-length spans.
            return start
        return v


class ClaimDraft(BaseModel):
    """Raw shape returned by the LLM, before claim_id stamping and persistence.

    Extractor receives this from JSON mode, then promotes to Claim by computing
    the stable claim_id and attaching episode_id / source_url / version fields.

    `entity_refs` carries entity names *as strings* (not IDs). The LLM doesn't
    know our canonical `entity_id`s — we resolve names to IDs post-extraction
    through the canonicalizer. Entities are treated as weak signals: the LLM
    may reference a name it didn't also list in the top-level `entities`
    array, and the entity canonicalizer is the source of truth.
    """

    model_config = ConfigDict(extra="ignore")

    text: str
    speaker: Optional[str] = None
    timestamp_start: float = Field(ge=0.0)
    timestamp_end: float = Field(ge=0.0)
    claim_type: ClaimType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_excerpt: str
    entity_refs: list[str] = Field(
        default_factory=list,
        description="Entity names referenced by this claim. Resolved to entity_ids post-extraction.",
    )


class Entity(BaseModel):
    """A canonical person / company / ticker / project / product / place.

    Identity is dual: `entity_id` is the stable hash-based PK used as a
    foreign key on claims and mentions; `slug` is a mutable human-readable
    label (with a type prefix and kebab-cased name) regenerable on rename.
    Embedding of the name/aliases lives in the generic `embeddings` table,
    never inline, so the canonicalizer can swap backends later.
    """

    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(description="Stable `ent_<8-char hash>` PK.")
    slug: str = Field(
        description="Human-readable label, e.g. `person:vitalik-buterin`. UNIQUE, mutable."
    )
    name: str = Field(description="Display form of the entity name.")
    entity_type: EntityType = Field(description="Entity category.")
    aliases: list[str] = Field(
        default_factory=list,
        description="Observed surface forms (raw strings) collected from mentions.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence from the original extraction (LLM self-reported).",
    )
    created_at: Optional[datetime] = Field(
        default=None, description="Persisted by the store layer."
    )


class EntityDraft(BaseModel):
    """Raw shape returned by the LLM for a single entity.

    Entities are lower-entropy but higher-precision-sensitive than claims.
    The canonicalizer (not the LLM) is the source of truth for identity —
    this draft just carries the LLM's observation forward.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    entity_type: EntityType
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class EntityMention(BaseModel):
    """One observation of an entity inside a transcript.

    Timestamp is the primary anchor; char offsets are best-effort (populated
    via string search in the chunk when resolvable). `claim_id` is nullable
    because entities can appear without being tied to a specific claim.
    """

    model_config = ConfigDict(extra="ignore")

    entity_id: str
    episode_id: str
    claim_id: Optional[str] = None
    chunk_id: Optional[str] = Field(
        default=None,
        description="Opaque id of the chunk the mention came from (e.g. `<episode>:chunk:<idx>`).",
    )
    raw_text: str = Field(
        description="Surface form as observed in the transcript (pre-normalization)."
    )
    start_char: Optional[int] = Field(
        default=None,
        ge=0,
        description="Offset into the chunk text; NULL when unresolvable.",
    )
    end_char: Optional[int] = Field(default=None, ge=0)
    timestamp: Optional[float] = Field(default=None, ge=0.0)
    speaker: Optional[str] = None
    created_at: Optional[datetime] = None


class Topic(BaseModel):
    """A canonical topic — an abstraction over a cluster of claims.

    Unlike entities, topics don't carry a `type` — the topic graph is
    flat. Name alone is often ambiguous (`"Bitcoin"`) so the description
    carries the LLM's abstraction and gets included in the embedding
    recipe. No slug: topics aren't deep-linked in UI/MCP the way
    entities are, and the kebab form reads worse here than it does on
    people or companies.
    """

    model_config = ConfigDict(extra="ignore")

    topic_id: str = Field(description="Stable `top_<8-char hash>` PK.")
    name: str = Field(description="Short canonical topic label.")
    description: str = Field(
        default="",
        description="LLM-written abstraction; embedded alongside name for canonicalization.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Observed surface forms collected from aggregation runs.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence from the aggregation pass.",
    )
    created_at: Optional[datetime] = Field(
        default=None, description="Persisted by the store layer."
    )


class TopicDraft(BaseModel):
    """Raw topic shape returned by the aggregation LLM call.

    `claim_indices` refers to positions in the claims list we fed into
    the prompt (0-indexed). Those get resolved back to `claim_id`s
    post-call — asking the LLM to emit 32-char hashes reliably is a
    losing bet.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    claim_indices: list[int] = Field(default_factory=list)


class ClaimTopicEdge(BaseModel):
    """One row in the `claim_topics` join (source of truth for claim↔topic).

    The `Claim.topic_ids` JSON array is a denormalized cache of the
    `topic_id`s for fast per-claim render; this edge table powers
    reverse queries (`claims for this topic`) and carries the
    confidence the aggregator assigned to the link.
    """

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    topic_id: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ChunkFailure(BaseModel):
    """One per-chunk extraction failure, surfaced for quarantine persistence."""

    model_config = ConfigDict(extra="ignore")

    chunk_index: int
    error: str
    raw_output: Optional[str] = None


class ExtractionRunResult(BaseModel):
    """Outcome of one extract-knowledge run for a single episode."""

    job_id: str
    success: bool
    claims: list[Claim] = Field(default_factory=list)
    entities: list[Entity] = Field(
        default_factory=list,
        description="Canonical entities discovered (or matched to existing) during this run.",
    )
    mentions: list[EntityMention] = Field(
        default_factory=list,
        description="Per-chunk entity mentions to persist alongside claims.",
    )
    topics: list[Topic] = Field(
        default_factory=list,
        description="Canonical topics from the second-pass aggregation (Phase C.1). Empty when claim_count < threshold or no summarize provider.",
    )
    claim_topic_edges: list[ClaimTopicEdge] = Field(
        default_factory=list,
        description="Source-of-truth claim↔topic edges (join table). `Claim.topic_ids` JSON is a denormalized cache of these.",
    )
    chunks_processed: int = 0
    chunks_failed: int = 0
    failures: list[ChunkFailure] = Field(
        default_factory=list,
        description="Per-chunk failures, surfaced so the route can persist them.",
    )
    tokens_used: int = 0
    model: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None


def compute_claim_id(
    *, text: str, episode_id: str, speaker: Optional[str], timestamp_start: float
) -> str:
    """Stable SHA-256 over the citable identity of a claim.

    Same claim re-extracted on the same episode produces the same id, which
    lets us upsert without duplicates and detect when a re-extraction adds
    genuinely new claims vs. re-finds old ones.
    """
    payload = "|".join(
        [
            text.strip().lower(),
            episode_id,
            (speaker or "").strip().lower(),
            f"{round(timestamp_start, 1):.1f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# JSON Schema fragment fed to the LLM via response_format / function calling.
# Kept as a literal so the prompt and the validator can never drift apart
# silently — both reference this dict.
#
# Phase B extends Phase A with an `entities` array and per-claim `entity_refs`.
# The LLM returns entity names as strings; post-extraction we resolve each
# unique (name, type) pair through the canonicalizer into the opaque
# `entity_id`. Entities are treated as weak signals — a claim may reference
# a name the LLM didn't also list, or vice versa, and both paths are handled
# gracefully.
LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "speaker": {"type": ["string", "null"]},
                    "timestamp_start": {"type": "number", "minimum": 0},
                    "timestamp_end": {"type": "number", "minimum": 0},
                    "claim_type": {
                        "type": "string",
                        "enum": [c.value for c in ClaimType],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "evidence_excerpt": {"type": "string"},
                    "entity_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Entity names referenced by this claim (strings, not IDs).",
                    },
                },
                "required": [
                    "text",
                    "timestamp_start",
                    "timestamp_end",
                    "claim_type",
                    "confidence",
                    "evidence_excerpt",
                ],
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {
                        "type": "string",
                        "enum": [e.value for e in EntityType],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["name", "entity_type"],
            },
        },
    },
    "required": ["claims"],
}


# Phase C.1: separate schema for the second-pass topic aggregation call.
# This call runs once per episode after claims+entities are extracted, not
# per chunk. Input is a numbered list of claim texts; output is a small
# set of topics each pointing back at the claim indices they cover.
# Indices are resolved to stable `claim_id`s by the aggregator.
TOPIC_AGGREGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "claim_indices": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0},
                    },
                },
                "required": ["name", "claim_indices"],
            },
        }
    },
    "required": ["topics"],
}
