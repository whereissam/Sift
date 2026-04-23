"""Canonicalize extracted topic names into stable `topic_id`s.

Cousin of `entity_canonicalizer.py`, with three deliberate differences:

1. No type axis — topics are flat.
2. Threshold is **0.90** (vs. 0.85 for entities). Topics drift more on
   surface form (`"Bitcoin price"` vs `"BTC price action"`) and
   over-merging corrupts the graph in ways that are painful to unwind.
3. Normalization is richer — ticker expansion and conservative plural
   collapse run before embedding so the cosine space only has to
   distinguish genuinely different concepts.

The embedded string is `"{name}: {description}"` — name alone is short
and ambiguous, description carries the LLM's abstraction. Both stored
separately so we can re-embed later with a different recipe without
losing source text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .embedding_store import (
    DEFAULT_TEXT_MODEL,
    EmbeddingStore,
    embed_async,
    get_embedding_store,
)
from .job_store import JobStore, get_job_store
from .knowledge_schema import Topic, compute_topic_id
from .topic_normalization import normalize_topic_for_match

logger = logging.getLogger(__name__)

# Cosine threshold for reusing an existing topic. Higher than entities
# (0.85) because topic surface forms are fuzzier — errs toward
# under-merging, which is easier to tune down later than the inverse.
COSINE_MATCH_THRESHOLD = 0.90

TOPIC_OBJECT_TYPE = "topic"


def _embed_text(name: str, description: str) -> str:
    """The string we feed to the embedding model for a topic.

    `name: description` reads cleanly to most sentence transformers and
    keeps the cache key obvious (`embed_cache[(model, "name: desc")]`).
    Description is optional — empty description collapses to just the
    name, so the canonicalizer still works for Phase A topics that
    predate description.
    """
    if description:
        return f"{name}: {description}"
    return name


@dataclass
class CanonicalizedTopic:
    """Result of canonicalizing one aggregation-pass topic observation."""

    topic: Topic
    is_new: bool
    surface_form: str


class TopicCanonicalizer:
    """Embed-and-match topic canonicalizer.

    One instance per aggregation run. Maintains a run-level cache so the
    same topic mentioned twice in a run doesn't cost two DB round-trips.
    Writes back to the store (entity + embedding) as it goes.
    """

    def __init__(
        self,
        *,
        job_store: Optional[JobStore] = None,
        embedding_store: Optional[EmbeddingStore] = None,
        model: str = DEFAULT_TEXT_MODEL,
        threshold: float = COSINE_MATCH_THRESHOLD,
    ):
        self._job_store = job_store or get_job_store()
        self._embedding_store = embedding_store or get_embedding_store()
        self._model = model
        self._threshold = threshold
        # Per-run memo of normalized name → CanonicalizedTopic.
        self._run_cache: dict[str, CanonicalizedTopic] = {}

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def model(self) -> str:
        return self._model

    async def canonicalize(
        self,
        *,
        name: str,
        description: str = "",
        confidence: float = 1.0,
    ) -> Optional[CanonicalizedTopic]:
        """Resolve one topic observation to a canonical topic.

        Returns None for blank names. On reuse, merges the observed
        surface form into the existing topic's aliases and replaces
        the description with the newer, higher-confidence abstraction.
        """
        if not name or not name.strip():
            return None

        normalized = normalize_topic_for_match(name)
        if not normalized:
            return None

        cached = self._run_cache.get(normalized)
        if cached is not None:
            self._merge_alias(cached.topic, name)
            return cached

        vectors = await embed_async(
            [_embed_text(normalized, description)], model=self._model
        )
        if not vectors:
            return None
        query_vector = vectors[0]

        candidate_ids = self._job_store.find_topic_ids()
        if candidate_ids:
            top = self._embedding_store.query_topk(
                object_type=TOPIC_OBJECT_TYPE,
                model=self._model,
                vector=query_vector,
                k=1,
                filter_object_ids=candidate_ids,
            )
            if top and top[0][1] >= self._threshold:
                existing_id, score = top[0]
                existing = self._job_store.get_topic_by_id(existing_id)
                if existing:
                    topic = Topic(**existing)
                    self._merge_alias(topic, name)
                    # If the new description is higher-confidence, take it.
                    if (
                        description
                        and confidence >= topic.confidence
                        and description != topic.description
                    ):
                        topic.description = description
                        topic.confidence = confidence
                    self._job_store.upsert_topic(topic.model_dump(mode="json"))
                    result = CanonicalizedTopic(
                        topic=topic, is_new=False, surface_form=name
                    )
                    self._run_cache[normalized] = result
                    logger.debug(
                        "topic canonicalize: matched %s → %s (cosine=%.3f)",
                        name,
                        existing_id,
                        score,
                    )
                    return result

        # No match — mint a new topic.
        topic_id = compute_topic_id(name=name)
        topic = Topic(
            topic_id=topic_id,
            name=name.strip(),
            description=description,
            aliases=[name.strip()],
            confidence=confidence,
        )
        self._job_store.upsert_topic(topic.model_dump(mode="json"))
        self._embedding_store.upsert(
            object_type=TOPIC_OBJECT_TYPE,
            object_id=topic_id,
            model=self._model,
            vector=query_vector,
        )
        result = CanonicalizedTopic(topic=topic, is_new=True, surface_form=name)
        self._run_cache[normalized] = result
        logger.debug("topic canonicalize: minted %s → %s", name, topic_id)
        return result

    @staticmethod
    def _merge_alias(topic: Topic, raw: str) -> None:
        form = raw.strip()
        if form and form not in topic.aliases:
            topic.aliases.append(form)
