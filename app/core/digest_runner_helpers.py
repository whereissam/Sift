"""Claim gathering for the digest runner — kept separate so it's unit-testable
without spinning up the worker, and to keep the subscription_store import off the
runner's hot path.

The selection: for each subscription in the digest, take its *completed* items
whose download falls inside the window, follow ``subscription_items.job_id`` to
the episode, and pull that episode's claims above the digest's confidence floor.
Claims are deduped by ``claim_id`` (the stable cross-job hash), which collapses
the same claim re-found across overlapping feeds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .job_store import get_job_store
from .subscription_store import SubscriptionItemStatus, get_subscription_store

logger = logging.getLogger(__name__)


def gather_claims_for_digest(
    config: dict,
    *,
    now: Optional[datetime] = None,
    job_store=None,
    subscription_store=None,
) -> tuple[list[dict], int]:
    """Return ``(claims, episode_count)`` for a digest config's window.

    Window = ``[now - window_days, now]``, matched against each item's
    ``downloaded_at`` (falling back to ``published_at`` / ``discovered_at`` when a
    download timestamp is absent). Claims are deduped by ``claim_id``.
    """
    now = now or datetime.utcnow()
    since = (now - timedelta(days=config["window_days"])).isoformat()
    min_conf = config.get("min_confidence", 0.6)

    js = job_store or get_job_store()
    ss = subscription_store or get_subscription_store()

    seen: set = set()
    claims: list[dict] = []
    episode_ids: set = set()

    for sub_id in config.get("subscription_ids", []):
        items = ss.list_items(
            sub_id, status=SubscriptionItemStatus.COMPLETED, limit=500
        )
        for item in items:
            ts = (
                item.get("downloaded_at")
                or item.get("published_at")
                or item.get("discovered_at")
            )
            if ts and ts < since:
                continue
            job_id = item.get("job_id")
            if not job_id:
                continue
            for c in js.get_claims_for_job(job_id, min_confidence=min_conf):
                cid = c.get("claim_id")
                if cid in seen:
                    continue
                seen.add(cid)
                claims.append(c)
                episode_ids.add(job_id)

    return claims, len(episode_ids)
