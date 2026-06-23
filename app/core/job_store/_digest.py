"""P20: subscription digest pipeline store (configs + generated runs).

A *digest config* is a named, reusable definition — a set of subscriptions, a
time window, a cadence, and an optional webhook channel. A *digest run* is one
generated cross-episode synthesis for that config over a concrete window.

Kept in its own mixin so the digest control plane (due-selection, run history)
stays separate from the knowledge-data accessors. ``subscription_ids`` is stored
as a JSON array — a digest can span many feeds, which is the whole point
("what 5 podcasts said about X this week").
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Columns a caller may update on a digest config (everything but id/created_at).
_UPDATABLE_DIGEST_COLUMNS = {
    "name",
    "subscription_ids",
    "window_days",
    "schedule_hours",
    "min_confidence",
    "webhook_url",
    "enabled",
    "last_run_at",
}


class _DigestMixin:
    """CRUD for digest configs + run history + due-selection."""

    # ===== config CRUD =====

    def create_digest_config(
        self,
        digest_id: str,
        *,
        name: str,
        subscription_ids: list[str],
        window_days: int = 7,
        schedule_hours: int = 24,
        min_confidence: float = 0.6,
        webhook_url: Optional[str] = None,
        enabled: bool = True,
    ) -> dict:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO digest_configs (
                    digest_id, name, subscription_ids, window_days, schedule_hours,
                    min_confidence, webhook_url, enabled, last_run_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    digest_id,
                    name,
                    json.dumps(subscription_ids),
                    window_days,
                    schedule_hours,
                    min_confidence,
                    webhook_url,
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_digest_config(digest_id)

    def get_digest_config(self, digest_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM digest_configs WHERE digest_id = ?", (digest_id,)
            ).fetchone()
            return _config_row_to_dict(row) if row else None

    def list_digest_configs(self, *, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM digest_configs"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        with self._get_conn() as conn:
            return [_config_row_to_dict(r) for r in conn.execute(sql).fetchall()]

    def update_digest_config(self, digest_id: str, **updates) -> Optional[dict]:
        cols = {k: v for k, v in updates.items() if k in _UPDATABLE_DIGEST_COLUMNS}
        if not cols:
            return self.get_digest_config(digest_id)
        if "subscription_ids" in cols and isinstance(cols["subscription_ids"], list):
            cols["subscription_ids"] = json.dumps(cols["subscription_ids"])
        if "enabled" in cols:
            cols["enabled"] = 1 if cols["enabled"] else 0
        cols["updated_at"] = datetime.utcnow().isoformat()
        assignments = ", ".join(f"{k} = ?" for k in cols)
        params = [*cols.values(), digest_id]
        with self._get_conn() as conn:
            cur = conn.execute(
                f"UPDATE digest_configs SET {assignments} WHERE digest_id = ?", params
            )
            if cur.rowcount == 0:
                return None
        return self.get_digest_config(digest_id)

    def delete_digest_config(self, digest_id: str) -> bool:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM digest_runs WHERE digest_id = ?", (digest_id,))
            cur = conn.execute(
                "DELETE FROM digest_configs WHERE digest_id = ?", (digest_id,)
            )
            return cur.rowcount > 0

    def set_digest_last_run(self, digest_id: str, when: Optional[str] = None) -> None:
        ts = when or datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE digest_configs SET last_run_at = ?, updated_at = ? WHERE digest_id = ?",
                (ts, ts, digest_id),
            )

    def list_due_digests(self, *, now: Optional[datetime] = None) -> list[dict]:
        """Enabled configs whose ``last_run_at`` is older than ``schedule_hours``
        (or never run). The runner's tick uses this to decide what to generate."""
        now = now or datetime.utcnow()
        due = []
        for cfg in self.list_digest_configs(enabled_only=True):
            last = cfg.get("last_run_at")
            if not last:
                due.append(cfg)
                continue
            try:
                last_dt = datetime.fromisoformat(last)
            except (ValueError, TypeError):
                due.append(cfg)
                continue
            if now - last_dt >= timedelta(hours=cfg["schedule_hours"]):
                due.append(cfg)
        return due

    # ===== run history =====

    def save_digest_run(
        self,
        run_id: str,
        digest_id: str,
        *,
        status: str,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        episode_count: int = 0,
        claim_count: int = 0,
        synthesis_json: Optional[str] = None,
        markdown: Optional[str] = None,
        model: Optional[str] = None,
        tokens_used: int = 0,
        error: Optional[str] = None,
    ) -> dict:
        now = datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO digest_runs (
                    run_id, digest_id, window_start, window_end, status,
                    episode_count, claim_count, synthesis_json, markdown,
                    model, tokens_used, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, digest_id, window_start, window_end, status,
                    episode_count, claim_count, synthesis_json, markdown,
                    model, tokens_used, error, now,
                ),
            )
        return self.get_digest_run(run_id)

    def get_digest_run(self, run_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM digest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return _run_row_to_dict(row) if row else None

    def list_digest_runs(self, digest_id: str, *, limit: int = 20) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM digest_runs WHERE digest_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (digest_id, limit),
            ).fetchall()
            return [_run_row_to_dict(r) for r in rows]

    def get_latest_digest_run(self, digest_id: str) -> Optional[dict]:
        runs = self.list_digest_runs(digest_id, limit=1)
        return runs[0] if runs else None


def _config_row_to_dict(row) -> dict:
    d = dict(row)
    d["subscription_ids"] = json.loads(d.get("subscription_ids") or "[]")
    d["enabled"] = bool(d.get("enabled"))
    return d


def _run_row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("synthesis_json"):
        try:
            d["synthesis"] = json.loads(d["synthesis_json"])
        except (ValueError, TypeError):
            d["synthesis"] = None
    else:
        d["synthesis"] = None
    return d
