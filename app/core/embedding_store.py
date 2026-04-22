"""Thin retrieval interface over the generic `embeddings` table.

Phase A creates the table (in `JobStore._init_db`) and ships this minimal
interface so callers can be written today against a stable surface. Phase B
fills in the actual `embed()` method (sentence-transformers) when entity
canonicalization needs it; P10 builds the segment-level index.

Why this lives behind an interface: the user picked SQLite blobs for v1, but
the moment we hit ANN scale or multi-tenant filtering we'll want pgvector or
Chroma. Keeping every caller behind `EmbeddingStore` means that swap is a
one-file change instead of a refactor.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime
from typing import Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Sentinel objects so callers can pass `model=DEFAULT_TEXT_MODEL` without
# importing sentence-transformers. The actual model is loaded lazily in
# Phase B's embed() implementation.
DEFAULT_TEXT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


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
