"""Canonicalize extracted entity names into stable `entity_id`s.

Called post-extraction: the LLM returns entity names as strings, and we
resolve each (name, type) pair to a canonical entity by embedding the
normalized name and cosine-comparing against the existing entities of the
same type. ≥0.85 → reuse the hit; otherwise mint a new entity with a
hash-based `entity_id` and a human-readable slug.

The canonicalizer is the source of truth for entity identity — not the
LLM. Treating LLM-supplied names as weak signals lets us absorb noise
(case shifts, abbreviations, casual mentions) without exploding the
entity count.
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
    normalize_for_embedding,
)
from .job_store import JobStore, get_job_store
from .knowledge_schema import (
    Entity,
    EntityType,
    compute_entity_id,
    slugify_entity_name,
)

logger = logging.getLogger(__name__)

# Cosine threshold above which two entity names are considered the same
# canonical entity. Too low → merges unrelated entities (Apple the company
# with Apple the fruit), too high → explodes cardinality on surface-form
# variance. 0.85 is the locked default; revisit if downstream quality
# issues point here.
COSINE_MATCH_THRESHOLD = 0.85

ENTITY_OBJECT_TYPE = "entity"


@dataclass
class CanonicalizedEntity:
    """Result of canonicalizing one LLM-supplied entity observation."""

    entity: Entity
    is_new: bool
    surface_form: str


class EntityCanonicalizer:
    """Embed-and-match canonicalizer.

    Instantiate once per extraction run (or once per app). Not thread-safe
    w.r.t. concurrent mints against the same slug — but same-process
    serialization via SQLite writes + in-run slug cache keeps collisions
    out of the common path.
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
        # Per-run memo of name+type → CanonicalizedEntity so the same name
        # mentioned twice in one extraction doesn't trigger two DB
        # round-trips.
        self._run_cache: dict[tuple[str, str], CanonicalizedEntity] = {}

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
        entity_type: EntityType | str,
        confidence: float = 1.0,
    ) -> Optional[CanonicalizedEntity]:
        """Resolve one (name, type) observation to a canonical entity.

        Returns None for blank/whitespace-only names. Persists new entities
        to the store (including their embedding); existing-match returns
        the already-persisted record and merges the observed surface form
        into its aliases.
        """
        if not name or not name.strip():
            return None

        etype = (
            entity_type
            if isinstance(entity_type, EntityType)
            else EntityType(entity_type)
        )
        normalized = normalize_for_embedding(name)
        if not normalized:
            return None

        cache_key = (etype.value, normalized)
        cached = self._run_cache.get(cache_key)
        if cached is not None:
            self._merge_alias(cached.entity, name)
            return cached

        vectors = await embed_async([normalized], model=self._model)
        if not vectors:
            return None
        query_vector = vectors[0]

        candidate_ids = self._job_store.find_entity_ids_by_type(etype.value)
        if candidate_ids:
            top = self._embedding_store.query_topk(
                object_type=ENTITY_OBJECT_TYPE,
                model=self._model,
                vector=query_vector,
                k=1,
                filter_object_ids=candidate_ids,
            )
            if top and top[0][1] >= self._threshold:
                existing_id, score = top[0]
                existing = self._job_store.get_entity_by_id(existing_id)
                if existing:
                    entity = Entity(**existing)
                    self._merge_alias(entity, name)
                    # Persist alias merge when we added a new surface form.
                    self._job_store.upsert_entity(
                        entity.model_dump(mode="json")
                    )
                    result = CanonicalizedEntity(
                        entity=entity, is_new=False, surface_form=name
                    )
                    self._run_cache[cache_key] = result
                    logger.debug(
                        "canonicalize: matched %s → %s (cosine=%.3f)",
                        name,
                        existing_id,
                        score,
                    )
                    return result

        # No match — mint a new entity.
        entity_id = compute_entity_id(name=name, entity_type=etype)
        slug = self._unique_slug(etype, name)
        entity = Entity(
            entity_id=entity_id,
            slug=slug,
            name=name.strip(),
            entity_type=etype,
            aliases=[name.strip()],
            confidence=confidence,
        )
        self._job_store.upsert_entity(entity.model_dump(mode="json"))
        self._embedding_store.upsert(
            object_type=ENTITY_OBJECT_TYPE,
            object_id=entity_id,
            model=self._model,
            vector=query_vector,
        )
        result = CanonicalizedEntity(
            entity=entity, is_new=True, surface_form=name
        )
        self._run_cache[cache_key] = result
        logger.debug("canonicalize: minted %s → %s", name, entity_id)
        return result

    # ----- helpers -----

    def _unique_slug(self, entity_type: EntityType, name: str) -> str:
        """Generate a type-prefixed slug, appending -2/-3/... on collision.

        Slug collisions happen when two *different* entities normalize to
        the same kebab form (e.g. Apple the company vs. Apple the fruit).
        The `entity_id` is hash-based and already unique — the suffix is
        only added to keep the human-readable label unique too.
        """
        base = f"{entity_type.value}:{slugify_entity_name(name)}"
        if not self._job_store.slug_exists(base):
            return base
        # Already used — try numeric suffixes. Keep it bounded so a
        # pathological rerun doesn't scan forever.
        for i in range(2, 1000):
            candidate = f"{base}-{i}"
            if not self._job_store.slug_exists(candidate):
                return candidate
        # Highly unlikely; fall back to appending the entity_id tail.
        return f"{base}-{compute_entity_id(name=name, entity_type=entity_type)[-4:]}"

    @staticmethod
    def _merge_alias(entity: Entity, raw: str) -> None:
        form = raw.strip()
        if form and form not in entity.aliases:
            entity.aliases.append(form)
