"""P20: subscription digest runner — gather → synthesize → persist → emit.

Turns Sift from on-demand tool into an always-on knowledge pipeline. The
background worker mirrors ``knowledge_backfill`` / ``scheduler``: a singleton with
``start`` / ``stop`` / ``tick``. Each tick pulls the *due* digest configs (cadence
elapsed) and generates one cross-episode synthesis per config.

``run_digest`` is the unit-testable seam (the route calls it for run-now too):
it gathers the window's claims across the digest's subscriptions, synthesizes,
persists a ``digest_runs`` row, advances ``last_run_at``, accounts spend against
the shared daily budget, and best-effort emits a webhook. It never raises for an
expected degradation — an empty window or a missing provider becomes a recorded
``empty`` run, not a crash.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from ..config import get_settings
from .digest_runner_helpers import gather_claims_for_digest
from .digest_schema import render_digest_markdown
from .digest_synthesizer import DigestSynthesizer
from .job_store import get_job_store
from .knowledge_budget import estimate_cost_usd, get_budget_tracker
from .webhook_notifier import get_webhook_notifier

logger = logging.getLogger(__name__)


def _new_run_id() -> str:
    return f"dgr_{uuid4().hex[:12]}"


async def run_digest(
    config: dict,
    *,
    synthesizer: Optional[DigestSynthesizer] = None,
    now: Optional[datetime] = None,
    emit: bool = True,
) -> dict:
    """Generate one digest for ``config`` and persist the run. Returns the run row."""
    store = get_job_store()
    settings = get_settings()
    now = now or datetime.utcnow()
    digest_id = config["digest_id"]
    run_id = _new_run_id()

    window_start = (now - timedelta(days=config["window_days"])).isoformat()
    window_end = now.isoformat()
    window_label = f"{window_start[:10]} – {window_end[:10]}"

    claims, episode_count = gather_claims_for_digest(config, now=now)
    tracker = get_budget_tracker()

    # Hard cost stop: record a skipped run and advance the clock so we don't
    # hammer the same config every tick once over budget.
    if tracker.over_global_budget(settings.knowledge_daily_budget_usd):
        run = store.save_digest_run(
            run_id, digest_id, status="skipped",
            window_start=window_start, window_end=window_end,
            episode_count=episode_count, claim_count=len(claims),
            error="Daily LLM budget reached — digest skipped.",
        )
        store.set_digest_last_run(digest_id, window_end)
        return run

    synth = synthesizer or DigestSynthesizer.from_settings()
    result = await synth.synthesize(
        claims, window_label=window_label, max_claims=settings.digest_max_claims
    )

    if result.tokens_used:
        tracker.record(estimate_cost_usd(result.model, result.tokens_used))

    if not result.success:
        run = store.save_digest_run(
            run_id, digest_id, status="empty",
            window_start=window_start, window_end=window_end,
            episode_count=episode_count, claim_count=len(claims),
            model=result.model, tokens_used=result.tokens_used,
            error=result.error,
        )
        store.set_digest_last_run(digest_id, window_end)
        return run

    markdown = render_digest_markdown(
        result.synthesis, title=config["name"], window_label=window_label
    )
    run = store.save_digest_run(
        run_id, digest_id, status="ok",
        window_start=window_start, window_end=window_end,
        episode_count=episode_count, claim_count=len(claims),
        synthesis_json=result.synthesis.model_dump_json(),
        markdown=markdown, model=result.model, tokens_used=result.tokens_used,
    )
    store.set_digest_last_run(digest_id, window_end)

    if emit and config.get("webhook_url"):
        await _emit_webhook(config, run, result)

    logger.info(
        "Digest %s generated: %d claim(s) across %d episode(s)%s",
        digest_id, len(claims), episode_count,
        " → webhook" if (emit and config.get("webhook_url")) else "",
    )
    return run


async def _emit_webhook(config: dict, run: dict, result) -> None:
    """Best-effort digest webhook — a delivery failure never fails the run."""
    try:
        await get_webhook_notifier().notify(
            event="digest_generated",
            payload={
                "digest_id": config["digest_id"],
                "name": config["name"],
                "run_id": run["run_id"],
                "headline": result.synthesis.headline if result.synthesis else "",
                "episode_count": run["episode_count"],
                "claim_count": run["claim_count"],
                "markdown": run["markdown"],
            },
            webhook_url=config["webhook_url"],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Digest webhook delivery failed for %s: %s", config["digest_id"], e)


class DigestRunner:
    """Background worker that generates due digests on a schedule."""

    def __init__(self, *, check_interval: Optional[int] = None):
        s = get_settings()
        self._check_interval = check_interval or s.digest_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        s = get_settings()
        if not s.digest_enabled:
            logger.info("Digest runner is disabled")
            return
        if self._running:
            logger.warning("Digest runner already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Digest runner started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Digest runner stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001
                logger.error("Digest runner tick error: %s", e)
            await asyncio.sleep(self._check_interval)

    async def tick(self) -> int:
        """Generate every due digest. Returns the number processed."""
        store = get_job_store()
        due = store.list_due_digests()
        processed = 0
        for cfg in due:
            try:
                await run_digest(cfg)
                processed += 1
            except Exception as e:  # noqa: BLE001 - one bad digest can't stop the rest
                logger.error("Digest %s failed: %s", cfg.get("digest_id"), e)
        return processed


# ===== module singleton + lifecycle (mirrors scheduler.py) =====

_runner: Optional[DigestRunner] = None


def get_digest_runner() -> DigestRunner:
    global _runner
    if _runner is None:
        _runner = DigestRunner()
    return _runner


async def start_digest_runner() -> None:
    await get_digest_runner().start()


async def stop_digest_runner() -> None:
    global _runner
    if _runner:
        await _runner.stop()
        _runner = None
