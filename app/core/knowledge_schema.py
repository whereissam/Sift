"""Canonical Pydantic schema for the AI-friendly knowledge layer (P18).

Phase A scope: Claim only. Entity / Topic / Prediction land in Phase B/C but
the field hooks (entity_ids, topic_ids) already exist on Claim so the storage
layer doesn't change shape later.

A Claim is a discrete, citable, timestamped, speaker-attributed statement
extracted from a transcript. Every downstream system (MCP, Digest, RAG,
Search) reads from this same object.
"""

from __future__ import annotations

import hashlib
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
    """

    model_config = ConfigDict(extra="ignore")

    text: str
    speaker: Optional[str] = None
    timestamp_start: float = Field(ge=0.0)
    timestamp_end: float = Field(ge=0.0)
    claim_type: ClaimType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_excerpt: str


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
        }
    },
    "required": ["claims"],
}
