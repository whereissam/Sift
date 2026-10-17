"""KOL accessors for the prediction scorecard (docs/kol-scorecard.md).

A KOL is an ordinary `person` entity plus public handles (`kol_handles`).
`episode_speakers` says which KOL is behind a speaker label in one episode;
the review queue joins through it so a prediction can only be verified once
the person who said it is known.
"""

import json
import sqlite3
from datetime import datetime
from typing import Optional

KOL_PLATFORMS = ("x", "youtube", "podcast")


class HandleTakenError(ValueError):
    """The handle already belongs to a different KOL."""

    def __init__(self, platform: str, handle: str, entity_id: str):
        super().__init__(f"{platform} handle {handle!r} already belongs to {entity_id}")
        self.entity_id = entity_id


def normalize_handle(platform: str, handle: str) -> str:
    """`@Cobie ` and `cobie` are the same X account; feed URLs are kept as-is."""
    handle = handle.strip()
    if platform in ("x", "youtube"):
        return handle.lstrip("@").lower()
    return handle


class _KolsMixin:
    """KOL + handle + speaker-mapping CRUD used by the scorecard routes."""

    def upsert_kol(
        self,
        *,
        entity_id: str,
        name: str,
        slug: str,
        handles: list[tuple[str, str]],
    ) -> dict:
        """Create (or reuse) the person entity and attach handles.

        `entity_id` / `slug` come from the knowledge schema helpers (the
        caller computes them, as the canonicalizer does). `slug` gets a
        -2/-3 suffix if taken. Raises `HandleTakenError` if a handle already
        belongs to another person; nothing is written in that case.
        """
        now = datetime.utcnow().isoformat()
        normalized = [(p, normalize_handle(p, h)) for p, h in handles]
        with self._get_conn() as conn:
            for platform, handle in normalized:
                owner = conn.execute(
                    "SELECT entity_id FROM kol_handles WHERE platform = ? AND handle = ?",
                    (platform, handle),
                ).fetchone()
                if owner and owner["entity_id"] != entity_id:
                    raise HandleTakenError(platform, handle, owner["entity_id"])

            if not conn.execute(
                "SELECT 1 FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone():
                slug = self._free_person_slug(conn, slug)
                conn.execute(
                    """
                    INSERT INTO entities (
                        entity_id, slug, name, entity_type, aliases, confidence, created_at
                    ) VALUES (?, ?, ?, 'person', '[]', 1.0, ?)
                    """,
                    (entity_id, slug, name.strip(), now),
                )
            for platform, handle in normalized:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO kol_handles (entity_id, platform, handle, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entity_id, platform, handle, now),
                )
        return self.get_kol(entity_id)

    @staticmethod
    def _free_person_slug(conn: sqlite3.Connection, base: str) -> str:
        """Same -2/-3 suffixing as the entity canonicalizer, on this connection."""
        candidate, n = base, 2
        while conn.execute("SELECT 1 FROM entities WHERE slug = ?", (candidate,)).fetchone():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def get_kol(self, entity_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT entity_id, slug, name, aliases FROM entities "
                "WHERE entity_id = ? AND entity_type = 'person'",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            return self._kol_dict(conn, row)

    def list_kols(self) -> list[dict]:
        """Every person that has a handle or has been assigned to a speaker."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT entity_id, slug, name, aliases FROM entities
                WHERE entity_type = 'person' AND (
                    entity_id IN (SELECT entity_id FROM kol_handles)
                    OR entity_id IN (SELECT entity_id FROM episode_speakers)
                )
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
            return [self._kol_dict(conn, r) for r in rows]

    @staticmethod
    def _kol_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        handles = conn.execute(
            "SELECT platform, handle FROM kol_handles WHERE entity_id = ? "
            "ORDER BY platform, handle",
            (row["entity_id"],),
        ).fetchall()
        try:
            aliases = json.loads(row["aliases"] or "[]")
        except (TypeError, json.JSONDecodeError):
            aliases = []
        return {
            "entity_id": row["entity_id"],
            "slug": row["slug"],
            "name": row["name"],
            "aliases": aliases,
            "handles": [dict(h) for h in handles],
        }

    def remove_kol_handle(self, entity_id: str, platform: str, handle: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM kol_handles WHERE entity_id = ? AND platform = ? AND handle = ?",
                (entity_id, platform, normalize_handle(platform, handle)),
            )
            return cursor.rowcount > 0

    def list_episode_speakers(self, episode_id: str) -> list[dict]:
        """Every speaker label on the episode's claims, with its KOL if assigned."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT c.speaker, COUNT(*) AS claim_count,
                       es.entity_id, e.name AS kol_name, es.confirmed_by
                FROM claims c
                LEFT JOIN episode_speakers es
                       ON es.episode_id = c.episode_id AND es.speaker = c.speaker
                LEFT JOIN entities e ON e.entity_id = es.entity_id
                WHERE c.episode_id = ? AND c.speaker IS NOT NULL AND c.speaker != ''
                GROUP BY c.speaker
                ORDER BY claim_count DESC, c.speaker
                """,
                (episode_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_episode_speaker(
        self,
        episode_id: str,
        speaker: str,
        entity_id: str,
        *,
        confirmed_by: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO episode_speakers (
                    episode_id, speaker, entity_id, confirmed_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id, speaker) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    confirmed_by = excluded.confirmed_by,
                    updated_at = excluded.updated_at
                """,
                (episode_id, speaker, entity_id, confirmed_by, now, now),
            )

    def clear_episode_speaker(self, episode_id: str, speaker: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM episode_speakers WHERE episode_id = ? AND speaker = ?",
                (episode_id, speaker),
            )
            return cursor.rowcount > 0

    def get_speaker_kol(self, episode_id: str, speaker: Optional[str]) -> Optional[str]:
        """The KOL entity_id behind a speaker label, or None if unassigned."""
        if not speaker:
            return None
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT entity_id FROM episode_speakers WHERE episode_id = ? AND speaker = ?",
                (episode_id, speaker),
            ).fetchone()
        return row["entity_id"] if row else None
