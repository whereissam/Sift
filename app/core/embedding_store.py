"""Thin retrieval interface over the generic `embeddings` table.

Phase A created the table (in `JobStore._init_db`) and the interface so
callers could be written against a stable surface. Phase B fills in
`embed()` / `query_topk()` using sentence-transformers for entity
canonicalization. P10 will build the segment-level index on top.

Why this lives behind an interface: the user picked SQLite blobs for v1, but
the moment we hit ANN scale or multi-tenant filtering we'll want pgvector or
Chroma. Keeping every caller behind `EmbeddingStore` means that swap is a
one-file change instead of a refactor.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import sqlite3
import threading
from datetime import datetime
from typing import Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Sentinel so callers can pass `model=DEFAULT_TEXT_MODEL` without importing
# sentence-transformers. The actual model is loaded lazily the first time
# `embed()` is called.
DEFAULT_TEXT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# --- Module-level state for lazy model load + embedding cache -----------

_model_lock = threading.Lock()
_loaded_model = None
_loaded_model_name: Optional[str] = None

# Keyed by (model_name, normalized_text) → vector. Bounded via a simple FIFO
# eviction — we cap at ~10k entries because the typical working set across
# episodes is dominated by a long tail of repeat entity names ("ETH",
# "OpenAI", "Vitalik") where the cache earns its keep. If this turns out
# to be insufficient we can swap for lru_cache semantics, but FIFO is
# enough for a first pass.
_EMBED_CACHE_MAX = 10_000
_embed_cache: "dict[tuple[str, str], list[float]]" = {}
_embed_cache_lock = threading.Lock()


_NORMALIZE_SPACE_RE = re.compile(r"\s+")


def normalize_for_embedding(text: str) -> str:
    """Pre-embedding normalization shared by write and query paths.

    Kept deliberately conservative — aggressive normalization (stop-word
    removal, stemming, punctuation scrubbing) destroys signal the embedding
    model was trained to pick up. We only want to kill noise that would
    otherwise fragment the cache: case, leading/trailing whitespace, and
    internal whitespace runs.
    """
    if not text:
        return ""
    return _NORMALIZE_SPACE_RE.sub(" ", text.strip().lower())


def _load_model(model_name: str):
    """Load sentence-transformers model lazily. Thread-safe, module-cached."""
    global _loaded_model, _loaded_model_name
    with _model_lock:
        if _loaded_model is not None and _loaded_model_name == model_name:
            return _loaded_model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is required for embedding; install "
                "with `uv pip install sentence-transformers`"
            ) from e
        logger.info("Loading embedding model %s (first use)", model_name)
        _loaded_model = SentenceTransformer(model_name)
        _loaded_model_name = model_name
        return _loaded_model


def _cache_get(model: str, norm: str) -> Optional[list[float]]:
    with _embed_cache_lock:
        return _embed_cache.get((model, norm))


def _cache_put(model: str, norm: str, vector: list[float]) -> None:
    with _embed_cache_lock:
        if len(_embed_cache) >= _EMBED_CACHE_MAX:
            # Drop an arbitrary oldest entry — dict preserves insertion order.
            try:
                oldest = next(iter(_embed_cache))
                _embed_cache.pop(oldest, None)
            except StopIteration:  # pragma: no cover — defensive
                pass
        _embed_cache[(model, norm)] = vector


def clear_embedding_cache() -> None:
    """Test hook — drop the in-memory embedding cache."""
    with _embed_cache_lock:
        _embed_cache.clear()


def embed(
    texts: Sequence[str], *, model: str = DEFAULT_TEXT_MODEL
) -> list[list[float]]:
    """Synchronous embedding of a batch of texts (normalize + cache + encode).

    Misses are encoded in one batched `model.encode(...)` call; hits are
    short-circuited. Caller should wrap this in `asyncio.to_thread` when
    running inside an async route — the model itself is CPU-bound.
    """
    if not texts:
        return []

    normalized = [normalize_for_embedding(t) for t in texts]

    # Identify cache misses so we only run the model on novel strings.
    miss_indices: list[int] = []
    miss_norms: list[str] = []
    results: list[Optional[list[float]]] = [None] * len(texts)
    for i, norm in enumerate(normalized):
        cached = _cache_get(model, norm)
        if cached is not None:
            results[i] = cached
        else:
            miss_indices.append(i)
            miss_norms.append(norm)

    if miss_norms:
        m = _load_model(model)
        # `encode` returns numpy array by default — tolist() keeps the
        # interface backend-agnostic.
        vectors = m.encode(miss_norms, convert_to_numpy=True).tolist()
        for i, norm, vec in zip(miss_indices, miss_norms, vectors):
            _cache_put(model, norm, vec)
            results[i] = vec

    # By construction every slot is filled now.
    return [r for r in results if r is not None]


async def embed_async(
    texts: Sequence[str], *, model: str = DEFAULT_TEXT_MODEL
) -> list[list[float]]:
    """Run `embed()` off the event loop via `asyncio.to_thread`."""
    return await asyncio.to_thread(embed, texts, model=model)


def warmup(model: str = DEFAULT_TEXT_MODEL) -> None:
    """Opt-in preload to avoid the first-request latency spike.

    Safe to call from app startup under a feature flag. A no-op if
    sentence-transformers isn't installed — we don't want warmup to crash
    an app that doesn't use entity extraction.
    """
    try:
        _load_model(model)
        # Touch with a dummy text so the forward pass gets JIT'd too.
        embed(["warmup"], model=model)
    except Exception as e:  # pragma: no cover
        logger.warning("Embedding warmup skipped: %s", e)


class EmbeddingStore:
    """Read/write interface over the `embeddings` table.

    Public surface (stable across backends):
      - upsert(object_type, object_id, model, vector)
      - get(object_type, object_id, model) -> Optional[list[float]]
      - query_topk(object_type, model, query_vector, k)  [Phase B]
      - cosine(a, b) -> float                              [pure helper]
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from .job_store import get_job_store

            db_path = str(get_job_store().db_path)
        self.db_path = db_path

    # ----- write path -----

    def upsert(
        self,
        *,
        object_type: str,
        object_id: str,
        model: str,
        vector: Sequence[float],
    ) -> None:
        """Persist one embedding. Overwrites prior value for the same
        (object_type, object_id, model) key."""
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover - numpy is a hard dep
            raise RuntimeError("numpy is required for embedding storage") from e

        arr = np.asarray(vector, dtype=np.float32)
        blob = arr.tobytes()
        norm = float(np.linalg.norm(arr))

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO embeddings
                    (object_type, object_id, model, dim, vector_blob, norm, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_type, object_id, model) DO UPDATE SET
                    dim = excluded.dim,
                    vector_blob = excluded.vector_blob,
                    norm = excluded.norm
                """,
                (
                    object_type,
                    object_id,
                    model,
                    int(arr.size),
                    blob,
                    norm,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ----- read path -----

    def get(
        self, *, object_type: str, object_id: str, model: str
    ) -> Optional[list[float]]:
        """Read one embedding back as a Python list of floats."""
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("numpy is required for embedding storage") from e

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT vector_blob FROM embeddings
                WHERE object_type = ? AND object_id = ? AND model = ?
                """,
                (object_type, object_id, model),
            ).fetchone()
            if not row:
                return None
            return np.frombuffer(row[0], dtype=np.float32).tolist()
        finally:
            conn.close()

    # ----- search path -----

    def query_topk(
        self,
        *,
        object_type: str,
        model: str,
        vector: Sequence[float],
        k: int = 1,
        filter_object_ids: Optional[Sequence[str]] = None,
    ) -> list[tuple[str, float]]:
        """Cosine-rank the stored embeddings of `object_type` against `vector`.

        Returns `(object_id, score)` tuples sorted by score descending,
        capped at `k`. If `filter_object_ids` is provided, only those IDs
        are considered — used by the entity canonicalizer to scope the
        candidate set to one `entity_type`.

        This is a linear scan. That's deliberate for Phase B scale
        (thousands of entities per user at most). When the table grows past
        ~100k rows we swap the backend; the public shape stays the same.
        """
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("numpy is required for embedding storage") from e

        q = np.asarray(list(vector), dtype=np.float32)
        qn = float(np.linalg.norm(q))
        if qn == 0.0:
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            if filter_object_ids:
                placeholders = ",".join("?" * len(filter_object_ids))
                rows = conn.execute(
                    f"""
                    SELECT object_id, dim, vector_blob, norm FROM embeddings
                    WHERE object_type = ? AND model = ?
                      AND object_id IN ({placeholders})
                    """,
                    [object_type, model, *filter_object_ids],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT object_id, dim, vector_blob, norm FROM embeddings
                    WHERE object_type = ? AND model = ?
                    """,
                    (object_type, model),
                ).fetchall()
        finally:
            conn.close()

        scored: list[tuple[str, float]] = []
        for object_id, dim, blob, norm in rows:
            if not blob or not norm:
                continue
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape[0] != q.shape[0]:
                # Different model dims — skip quietly so a stale row can't
                # crash a search.
                continue
            score = float(np.dot(q, v) / (qn * float(norm)))
            scored.append((object_id, score))

        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    # ----- pure helper -----

    @staticmethod
    def cosine(a: Iterable[float], b: Iterable[float]) -> float:
        """Cosine similarity between two vectors. Returns 0.0 for zero-norm."""
        a_list = list(a)
        b_list = list(b)
        if len(a_list) != len(b_list):
            raise ValueError(
                f"vector length mismatch: {len(a_list)} != {len(b_list)}"
            )
        dot = sum(x * y for x, y in zip(a_list, b_list))
        na = math.sqrt(sum(x * x for x in a_list))
        nb = math.sqrt(sum(y * y for y in b_list))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)


_default_store: Optional[EmbeddingStore] = None


def get_embedding_store() -> EmbeddingStore:
    """Return a process-wide EmbeddingStore singleton."""
    global _default_store
    if _default_store is None:
        _default_store = EmbeddingStore()
    return _default_store
