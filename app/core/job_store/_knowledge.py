"""P18 knowledge layer: claims, entities, topics, predictions, extraction failures.

All four domains share one mixin because they're written together inside
``replace_claims_for_job`` — keeping them in one file keeps the cross-table
transaction visible.
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class _KnowledgeMixin:
    """Methods for the P18 knowledge layer."""

    # ===== Knowledge status (on the jobs row) =====

    def set_knowledge_status(self, job_id: str, status: str) -> None:
        """Set the knowledge_status on a job.

        Valid values: 'none' | 'pending' | 'extracting' | 'complete' | 'failed'.
        Used by the extractor and the (Phase C) backfill worker.
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET knowledge_status = ?, updated_at = ? WHERE job_id = ?",
                (status, datetime.utcnow().isoformat(), job_id),
            )

    def get_knowledge_status(self, job_id: str) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT knowledge_status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return row["knowledge_status"] if row else None

    # ===== Claims =====

    def upsert_claims(self, claims: list[dict]) -> int:
        """Upsert a batch of claim dicts. Returns the number of rows written.

        Each dict must contain the full Claim shape. We upsert by claim_id so
        re-extracting the same episode is idempotent — same input produces the
        same id, no duplicates.
        """
        if not claims:
            return 0

        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            for c in claims:
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, episode_id, text, speaker, timestamp_start,
                        timestamp_end, claim_type, confidence, evidence_excerpt,
                        entity_ids, topic_ids, source_url, extraction_version,
                        schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(claim_id) DO UPDATE SET
                        text = excluded.text,
                        speaker = excluded.speaker,
                        timestamp_start = excluded.timestamp_start,
                        timestamp_end = excluded.timestamp_end,
                        claim_type = excluded.claim_type,
                        confidence = excluded.confidence,
                        evidence_excerpt = excluded.evidence_excerpt,
                        entity_ids = excluded.entity_ids,
                        topic_ids = excluded.topic_ids,
                        source_url = excluded.source_url,
                        extraction_version = excluded.extraction_version,
                        schema_version = excluded.schema_version
                    """,
                    (
                        c["claim_id"],
                        c["episode_id"],
                        c["text"],
                        c.get("speaker"),
                        c["timestamp_start"],
                        c["timestamp_end"],
                        c["claim_type"],
                        c["confidence"],
                        c["evidence_excerpt"],
                        json.dumps(c.get("entity_ids", [])),
                        json.dumps(c.get("topic_ids", [])),
                        c.get("source_url"),
                        c["extraction_version"],
                        c["schema_version"],
                        c.get("created_at") or now,
                    ),
                )
        return len(claims)

    def get_claims_for_job(
        self, job_id: str, min_confidence: float = 0.0
    ) -> list[dict]:
        """Return all claims for an episode, ordered by timestamp."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM claims
                WHERE episode_id = ? AND confidence >= ?
                ORDER BY timestamp_start ASC
                """,
                (job_id, min_confidence),
            ).fetchall()
            return [self._claim_row_to_dict(r) for r in rows]

    def query_claims(
        self,
        *,
        claim_type: Optional[str] = None,
        speaker: Optional[str] = None,
        min_confidence: float = 0.0,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Library-wide claim query with filters."""
        clauses: list[str] = ["confidence >= ?"]
        params: list = [min_confidence]
        if claim_type:
            clauses.append("claim_type = ?")
            params.append(claim_type)
        if speaker:
            clauses.append("speaker = ?")
            params.append(speaker)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM claims
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return [self._claim_row_to_dict(r) for r in rows]

    def delete_claims_for_job(self, job_id: str) -> int:
        """Wipe claims for an episode (used before re-extraction)."""
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM claims WHERE episode_id = ?", (job_id,))
            return cur.rowcount

    def replace_claims_for_job(
        self,
        job_id: str,
        claims: list[dict],
        entities: Optional[list[dict]] = None,
        mentions: Optional[list[dict]] = None,
        topics: Optional[list[dict]] = None,
        claim_topic_edges: Optional[list[dict]] = None,
        predictions: Optional[list[dict]] = None,
    ) -> int:
        """Atomically replace all claims for an episode (delete + insert in one tx).

        Closes the data-integrity hole where a separate delete + upsert
        could leave the episode with zero claims if the second call lost
        a race or the process crashed in between. The whole operation
        commits or rolls back as a unit because both statements share a
        single connection inside one `_get_conn()` context.

        Phase B: optionally upsert entities and replace `entity_mentions`
        for the episode in the same transaction. Entities are global
        (PK on `entity_id`) — we upsert, never wipe — but an episode's
        mentions are episode-scoped so we delete-then-insert them
        alongside the claims.

        Phase C.1: optionally upsert topics and replace `claim_topics`
        edges for the episode in the same transaction. Topics are global
        (PK on `topic_id`) — we upsert, never wipe. `claim_topics` is the
        source of truth for the claim↔topic relationship; the
        `claims.topic_ids` JSON on each claim is a denormalized cache
        that must stay consistent — inserting claims after setting up
        edges via this method relies on the caller having written
        `topic_ids` into each claim dict (extractor does this). The join
        rows are scoped to the claim_ids being inserted, so the
        ON DELETE CASCADE on the FK handles cleanup when a claim is
        removed in a later re-extraction.

        Phase C.2: optionally write `predictions` rows in the same tx.
        Each row is keyed by `claim_id` (FK UNIQUE → claims). SQLite's
        `foreign_keys` PRAGMA is off by default; we explicitly delete
        the episode's predictions before deleting the claims so we
        don't leave orphan rows pointing at vanished claim_ids. New
        prediction rows go in after the claim inserts so the FK is
        satisfied. Bogus rows (claim_id not in this run) are dropped
        rather than crashing the tx.
        """
        now = datetime.utcnow().isoformat()
        claim_ids_in_run = {c["claim_id"] for c in claims}
        with self._get_conn() as conn:
            # SQLite's foreign_keys PRAGMA is off by default and flipping it
            # globally risks breaking other tests; explicitly clear the
            # claim_topics rows for this episode first so the subsequent
            # DELETE FROM claims can't leave orphan edges behind.
            conn.execute(
                """
                DELETE FROM claim_topics
                WHERE claim_id IN (
                    SELECT claim_id FROM claims WHERE episode_id = ?
                )
                """,
                (job_id,),
            )
            conn.execute(
                """
                DELETE FROM predictions
                WHERE claim_id IN (
                    SELECT claim_id FROM claims WHERE episode_id = ?
                )
                """,
                (job_id,),
            )
            conn.execute("DELETE FROM claims WHERE episode_id = ?", (job_id,))
            if mentions is not None:
                conn.execute(
                    "DELETE FROM entity_mentions WHERE episode_id = ?",
                    (job_id,),
                )
            if entities:
                for e in entities:
                    self._upsert_entity_row(conn, e, now)
            if topics:
                for t in topics:
                    self._upsert_topic_row(conn, t, now)
            for c in claims:
                conn.execute(
                    """
                    INSERT INTO claims (
                        claim_id, episode_id, text, speaker, timestamp_start,
                        timestamp_end, claim_type, confidence, evidence_excerpt,
                        entity_ids, topic_ids, source_url, extraction_version,
                        schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c["claim_id"],
                        c["episode_id"],
                        c["text"],
                        c.get("speaker"),
                        c["timestamp_start"],
                        c["timestamp_end"],
                        c["claim_type"],
                        c["confidence"],
                        c["evidence_excerpt"],
                        json.dumps(c.get("entity_ids", [])),
                        json.dumps(c.get("topic_ids", [])),
                        c.get("source_url"),
                        c["extraction_version"],
                        c["schema_version"],
                        c.get("created_at") or now,
                    ),
                )
            if mentions:
                for m in mentions:
                    self._insert_mention_row(conn, m, now)
            if claim_topic_edges:
                for edge in claim_topic_edges:
                    # Defensive: only insert edges that point at claims in
                    # this run. Stale edges from a bug upstream shouldn't
                    # cause FK insert failures that roll back the whole tx.
                    if edge["claim_id"] not in claim_ids_in_run:
                        logger.warning(
                            "replace_claims_for_job: dropping edge for "
                            "unknown claim_id=%s",
                            edge["claim_id"],
                        )
                        continue
                    self._insert_claim_topic_edge(conn, edge, now)
            if predictions:
                for p in predictions:
                    if p["claim_id"] not in claim_ids_in_run:
                        logger.warning(
                            "replace_claims_for_job: dropping prediction for "
                            "unknown claim_id=%s",
                            p["claim_id"],
                        )
                        continue
                    self._upsert_prediction_row(conn, p, now)
        return len(claims)

    # ===== P18 Phase B: Entity + Mention accessors =====

    @staticmethod
    def _upsert_entity_row(conn: sqlite3.Connection, e: dict, now: str) -> None:
        """Internal: upsert an entity on an existing connection.

        Merge semantics: on conflict on `entity_id` we update `name` +
        `confidence` (latest wins) and union the `aliases` list so novel
        surface forms accumulate across episodes.
        """
        row = conn.execute(
            "SELECT aliases FROM entities WHERE entity_id = ?",
            (e["entity_id"],),
        ).fetchone()
        existing_aliases: list[str] = []
        if row and row["aliases"]:
            try:
                existing_aliases = json.loads(row["aliases"])
            except (TypeError, json.JSONDecodeError):
                existing_aliases = []
        incoming = e.get("aliases", []) or []
        merged: list[str] = list(existing_aliases)
        for a in incoming:
            if a and a not in merged:
                merged.append(a)
        conn.execute(
            """
            INSERT INTO entities (
                entity_id, slug, name, entity_type, aliases, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                name = excluded.name,
                entity_type = excluded.entity_type,
                aliases = excluded.aliases,
                confidence = excluded.confidence
            """,
            (
                e["entity_id"],
                e["slug"],
                e["name"],
                e["entity_type"],
                json.dumps(merged),
                e.get("confidence", 1.0),
                e.get("created_at") or now,
            ),
        )

    @staticmethod
    def _insert_mention_row(conn: sqlite3.Connection, m: dict, now: str) -> None:
        conn.execute(
            """
            INSERT INTO entity_mentions (
                entity_id, episode_id, claim_id, chunk_id, raw_text,
                start_char, end_char, timestamp, speaker, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m["entity_id"],
                m["episode_id"],
                m.get("claim_id"),
                m.get("chunk_id"),
                m["raw_text"],
                m.get("start_char"),
                m.get("end_char"),
                m.get("timestamp"),
                m.get("speaker"),
                m.get("created_at") or now,
            ),
        )

    def upsert_entity(self, entity: dict) -> None:
        """Upsert a single entity."""
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._upsert_entity_row(conn, entity, now)

    def get_entity_by_id(self, entity_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            return self._entity_row_to_dict(row) if row else None

    def get_entity_by_slug(self, slug: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE slug = ?", (slug,)
            ).fetchone()
            return self._entity_row_to_dict(row) if row else None

    def slug_exists(self, slug: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM entities WHERE slug = ?", (slug,)
            ).fetchone()
            return row is not None

    def list_entities(
        self,
        *,
        entity_type: Optional[str] = None,
        slug: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if slug:
            clauses.append("slug = ?")
            params.append(slug)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM entities {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._entity_row_to_dict(r) for r in rows]

    def find_entity_ids_by_type(self, entity_type: str) -> list[str]:
        """Candidate set for the canonicalizer's cosine scan."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ?",
                (entity_type,),
            ).fetchall()
        return [r["entity_id"] for r in rows]

    def add_entity_mention(self, mention: dict) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._insert_mention_row(conn, mention, now)

    def get_mentions_for_entity(
        self, entity_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM entity_mentions
                WHERE entity_id = ?
                ORDER BY episode_id ASC, timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (entity_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_mentions_for_episode(self, episode_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM entity_mentions WHERE episode_id = ?", (episode_id,)
            )
            return cur.rowcount

    @staticmethod
    def _entity_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        raw = d.get("aliases")
        try:
            d["aliases"] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            d["aliases"] = []
        return d

    # ===== P18 Phase C.1: Topic + claim_topic accessors =====

    @staticmethod
    def _upsert_topic_row(conn: sqlite3.Connection, t: dict, now: str) -> None:
        """Internal: upsert a topic on an existing connection.

        Merge semantics on conflict (`topic_id` collision): union aliases,
        take the latest `name`/`description`/`confidence`. Description is
        allowed to be replaced by a later aggregation pass — the
        canonicalizer only merges when cosine ≥0.90, so "replacement" here
        means the same semantic topic got a clearer description.
        """
        row = conn.execute(
            "SELECT aliases FROM topics WHERE topic_id = ?", (t["topic_id"],)
        ).fetchone()
        existing_aliases: list[str] = []
        if row and row["aliases"]:
            try:
                existing_aliases = json.loads(row["aliases"])
            except (TypeError, json.JSONDecodeError):
                existing_aliases = []
        incoming = t.get("aliases", []) or []
        merged: list[str] = list(existing_aliases)
        for a in incoming:
            if a and a not in merged:
                merged.append(a)
        conn.execute(
            """
            INSERT INTO topics (
                topic_id, name, description, aliases, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                aliases = excluded.aliases,
                confidence = excluded.confidence
            """,
            (
                t["topic_id"],
                t["name"],
                t.get("description", ""),
                json.dumps(merged),
                t.get("confidence", 1.0),
                t.get("created_at") or now,
            ),
        )

    @staticmethod
    def _insert_claim_topic_edge(
        conn: sqlite3.Connection, edge: dict, now: str
    ) -> None:
        """Insert-or-update a claim↔topic edge.

        Uses `INSERT ... ON CONFLICT(claim_id, topic_id) DO UPDATE` so a
        second aggregation run on the same pair overwrites `confidence`
        rather than raising a UNIQUE violation. Deliberately not
        `INSERT OR REPLACE` — that would delete-and-reinsert, resetting
        `created_at` on every run. We want the original edge's
        `created_at` preserved so the earliest observation timestamp
        survives re-extraction.
        """
        conn.execute(
            """
            INSERT INTO claim_topics (claim_id, topic_id, confidence, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(claim_id, topic_id) DO UPDATE SET
                confidence = excluded.confidence
            """,
            (
                edge["claim_id"],
                edge["topic_id"],
                edge.get("confidence", 1.0),
                edge.get("created_at") or now,
            ),
        )

    def upsert_topic(self, topic: dict) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._upsert_topic_row(conn, topic, now)

    def get_topic_by_id(self, topic_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM topics WHERE topic_id = ?", (topic_id,)
            ).fetchone()
            return self._topic_row_to_dict(row) if row else None

    def list_topics(
        self,
        *,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM topics {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._topic_row_to_dict(r) for r in rows]

    def find_topic_ids(self) -> list[str]:
        """Candidate set for the topic canonicalizer's cosine scan."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT topic_id FROM topics").fetchall()
        return [r["topic_id"] for r in rows]

    def add_claim_topic_edge(self, edge: dict) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._insert_claim_topic_edge(conn, edge, now)

    def get_claim_topic_edges(self, claim_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM claim_topics WHERE claim_id = ?", (claim_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_claims_for_topic(
        self, topic_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """Return claims linked to a topic via the join table (source of truth)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT c.* FROM claims c
                JOIN claim_topics ct ON c.claim_id = ct.claim_id
                WHERE ct.topic_id = ?
                ORDER BY c.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (topic_id, limit, offset),
            ).fetchall()
        return [self._claim_row_to_dict(r) for r in rows]

    @staticmethod
    def _topic_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        raw = d.get("aliases")
        try:
            d["aliases"] = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            d["aliases"] = []
        return d

    # ===== P18 Phase C.2: Prediction accessors =====

    @staticmethod
    def _upsert_prediction_row(
        conn: sqlite3.Connection, p: dict, now: str
    ) -> None:
        """Internal: upsert a prediction on an existing connection.

        On `claim_id` collision we update lifecycle-input columns
        (`target_horizon`, `conditions`, `falsifiable_by`) so a
        re-extraction can refine them, but we deliberately do **not**
        touch `resolution`/`resolution_note`/`resolved_at`/`resolved_by`
        — those are operator-set state that re-extraction must never
        clobber. `created_at` is preserved across upserts; only
        `updated_at` advances.
        """
        conn.execute(
            """
            INSERT INTO predictions (
                claim_id, target_horizon, conditions, falsifiable_by,
                resolution, resolution_note, resolved_at, resolved_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO UPDATE SET
                target_horizon = excluded.target_horizon,
                conditions = excluded.conditions,
                falsifiable_by = excluded.falsifiable_by,
                updated_at = excluded.updated_at
            """,
            (
                p["claim_id"],
                p.get("target_horizon"),
                p.get("conditions"),
                p.get("falsifiable_by"),
                p.get("resolution") or "pending",
                p.get("resolution_note"),
                p.get("resolved_at"),
                p.get("resolved_by"),
                p.get("created_at") or now,
                p.get("updated_at") or now,
            ),
        )

    def upsert_prediction(self, prediction: dict) -> None:
        """Upsert a single prediction (lifecycle-input fields only).

        Use `resolve_prediction` to change resolution state; this
        method's ON CONFLICT clause leaves resolution columns alone.
        """
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            self._upsert_prediction_row(conn, prediction, now)

    def get_prediction_by_claim_id(self, claim_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM predictions WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_predictions(
        self,
        *,
        resolution: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if resolution:
            clauses.append("resolution = ?")
            params.append(resolution)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM predictions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_prediction(
        self,
        claim_id: str,
        *,
        resolution: str,
        note: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> Optional[dict]:
        """Set the lifecycle state on an existing prediction.

        Returns the updated row, or None if no prediction exists for
        `claim_id`. Reverting to `pending` (e.g. on operator typo) is
        allowed and clears `resolved_at`/`resolved_by`/`resolution_note`
        so the row can't carry stale resolution metadata across a
        revert.
        """
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT 1 FROM predictions WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if not existing:
                return None
            if resolution == "pending":
                conn.execute(
                    """
                    UPDATE predictions SET
                        resolution = 'pending',
                        resolution_note = NULL,
                        resolved_at = NULL,
                        resolved_by = NULL,
                        updated_at = ?
                    WHERE claim_id = ?
                    """,
                    (now, claim_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE predictions SET
                        resolution = ?,
                        resolution_note = ?,
                        resolved_at = ?,
                        resolved_by = ?,
                        updated_at = ?
                    WHERE claim_id = ?
                    """,
                    (resolution, note, now, resolved_by, now, claim_id),
                )
        return self.get_prediction_by_claim_id(claim_id)

    @staticmethod
    def _claim_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # JSON-array columns
        for k in ("entity_ids", "topic_ids"):
            raw = d.get(k)
            try:
                d[k] = json.loads(raw) if raw else []
            except (TypeError, json.JSONDecodeError):
                d[k] = []
        return d

    # ===== Extraction failure quarantine =====

    def record_extraction_failure(
        self,
        *,
        episode_id: str,
        chunk_index: Optional[int],
        error: str,
        raw_output: Optional[str] = None,
        extraction_version: Optional[int] = None,
        model: Optional[str] = None,
    ) -> None:
        """Quarantine a malformed extractor response so the pipeline never
        crashes on bad LLM output."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO extraction_failures
                    (episode_id, chunk_index, raw_output, error,
                     extraction_version, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    chunk_index,
                    raw_output,
                    error,
                    extraction_version,
                    model,
                    datetime.utcnow().isoformat(),
                ),
            )
