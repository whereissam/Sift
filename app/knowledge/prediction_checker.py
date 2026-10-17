"""Resolve price predictions automatically (KOL scorecard step 2).

Each tick:
1. parse a due date from `target_horizon` where none is set yet
2. parse a price target from the claim text where none is set yet
   (a manual target is never replaced)
3. for *verified* price calls, read the price history since the call was
   made from CoinGecko and resolve:
   - target reached at any point in the window  -> true, immediately
   - due date passed without reaching it          -> false
   - otherwise                                     -> stays pending
   Every resolution stores the price evidence and a readable note.

Unverified calls are parsed but never resolved: only what a human checked
can end up on a scorecard.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Protocol

import httpx

from ..config import get_settings
from ..store import get_job_store
from .prediction_targets import parse_due_date, parse_price_target

logger = logging.getLogger(__name__)

RESOLVED_BY = "price-checker"


class PriceFeed(Protocol):
    async def history(self, coin_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        """USD prices between `start` and `end`, oldest first."""


class PriceFeedError(RuntimeError):
    pass


class CoinGeckoFeed:
    """CoinGecko's market_chart/range. Without a key the public API applies a
    low rate limit and only serves roughly the last year of history."""

    BASE = "https://api.coingecko.com/api/v3"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0):
        self._headers = {"accept": "application/json"}
        if api_key:
            self._headers["x-cg-demo-api-key"] = api_key
        self._timeout = timeout

    async def history(self, coin_id: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        params = {
            "vs_currency": "usd",
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
        }
        url = f"{self.BASE}/coins/{coin_id}/market_chart/range"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.get(url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise PriceFeedError(f"CoinGecko request failed: {exc}") from exc
        if response.status_code != 200:
            raise PriceFeedError(f"CoinGecko {response.status_code}: {response.text[:200]}")
        prices = response.json().get("prices") or []
        return [
            (datetime.fromtimestamp(ms / 1000, tz=timezone.utc), float(price))
            for ms, price in prices
        ]


@dataclass
class CheckSummary:
    due_dates_parsed: int = 0
    targets_parsed: int = 0
    checked: int = 0
    resolved_true: int = 0
    resolved_false: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_when(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(value[:10]), datetime.min.time())
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _usd(value: float) -> str:
    return f"${value:,.2f}" if value < 100 else f"${value:,.0f}"


class PredictionChecker:
    def __init__(self, feed: Optional[PriceFeed] = None, *, now: Optional[datetime] = None):
        self._feed = feed or CoinGeckoFeed(get_settings().coingecko_api_key)
        self._now = now

    def _current_time(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    async def run(self) -> CheckSummary:
        store = get_job_store()
        summary = CheckSummary()
        for item in store.list_pending_predictions_for_checker():
            made_at = _parse_when(item["made_at"])
            if made_at is None:
                continue
            if not item["due_source"] and item["target_horizon"]:
                due = parse_due_date(item["target_horizon"], made_at.date())
                if due:
                    store.set_prediction_due(item["claim_id"], due.isoformat(), source="parsed")
                    item["due_at"] = due.isoformat()
                    summary.due_dates_parsed += 1
            if item["target"] is None:
                target = parse_price_target(item["text"])
                if target:
                    item["target"] = store.set_prediction_target(
                        item["claim_id"], asset=target.asset, coin_id=target.coin_id,
                        comparator=target.comparator, value=target.value, source="parsed",
                    )
                    summary.targets_parsed += 1
            if item["target"] and item["review_status"] == "verified":
                try:
                    await self._check(store, item, made_at, summary)
                except PriceFeedError as exc:
                    summary.errors.append(f"{item['claim_id']}: {exc}")
                    logger.warning("Price check failed for %s: %s", item["claim_id"], exc)
        return summary

    async def _check(self, store, item: dict, made_at: datetime, summary: CheckSummary) -> None:
        target = item["target"]
        now = self._current_time()
        due_end = None
        if item["due_at"]:
            due_day = date.fromisoformat(item["due_at"][:10])
            due_end = datetime.combine(due_day + timedelta(days=1), datetime.min.time(),
                                       tzinfo=timezone.utc)
        window_end = min(now, due_end) if due_end else now
        if window_end <= made_at:
            return
        history = await self._feed.history(target["coin_id"], made_at, window_end)
        summary.checked += 1
        if not history:
            return

        if target["baseline"] is None:
            store.record_target_check(item["claim_id"], baseline=history[0][1])

        above = target["comparator"] == ">="
        best_at, best = (max if above else min)(history, key=lambda point: point[1])
        reached = best >= target["value"] if above else best <= target["value"]
        evidence = {
            "source": "coingecko",
            "window_start": made_at.isoformat(),
            "window_end": window_end.isoformat(),
            "extreme": best,
            "extreme_at": best_at.isoformat(),
            "checked_at": now.isoformat(),
        }
        store.record_target_check(item["claim_id"], evidence=evidence)

        goal = f"{target['asset']} {'≥' if above else '≤'} {_usd(target['value'])}"
        if reached:
            store.resolve_prediction(
                item["claim_id"], resolution="true", resolved_by=RESOLVED_BY,
                note=f"{goal}: {target['asset']} hit {_usd(best)} on "
                     f"{best_at.date().isoformat()} (CoinGecko).",
            )
            summary.resolved_true += 1
        elif due_end and now >= due_end:
            store.resolve_prediction(
                item["claim_id"], resolution="false", resolved_by=RESOLVED_BY,
                note=f"{goal} by {item['due_at'][:10]}: "
                     f"{'peaked at' if above else 'bottomed at'} {_usd(best)} "
                     f"(CoinGecko, {made_at.date().isoformat()} → {item['due_at'][:10]}).",
            )
            summary.resolved_false += 1


class PredictionCheckerRunner:
    """Background loop, same lifecycle as the digest runner."""

    def __init__(self, *, check_interval: Optional[int] = None):
        s = get_settings()
        self._check_interval = check_interval or s.prediction_checker_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not get_settings().prediction_checker_enabled:
            logger.info("Prediction checker is disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Prediction checker started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while self._running:
            try:
                summary = await PredictionChecker().run()
                logger.info("Prediction checker: %s", summary)
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                logger.error("Prediction checker tick error: %s", e)
            await asyncio.sleep(self._check_interval)


_runner: Optional[PredictionCheckerRunner] = None


async def start_prediction_checker() -> None:
    global _runner
    if _runner is None:
        _runner = PredictionCheckerRunner()
    await _runner.start()


async def stop_prediction_checker() -> None:
    global _runner
    if _runner:
        await _runner.stop()
        _runner = None
