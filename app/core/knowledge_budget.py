"""P18 Phase C.3: cost estimation + a daily spend tracker for knowledge extraction.

The backfill worker is the one place in Sift that can spend money unattended
(LLM calls over the whole back catalogue), so it needs a guardrail. This module
provides two things:

  1. ``estimate_cost_usd(model, tokens)`` — a rough blended price per model, used
     to turn the extractor's ``tokens_used`` into dollars. We only get a total
     token count back (not split input/output), so the table is a single blended
     $/1K rate per model family. Good enough for a budget *guardrail* — we're
     deciding "keep going on the good model vs. downgrade", not billing.

  2. ``KnowledgeBudgetTracker`` — an in-memory, per-UTC-day ledger of spend
     (global + per-subscription) plus a downgrade counter. Held as a process
     singleton via ``get_budget_tracker()``. In-memory by design: spend resets
     at process restart, which is the safe direction for a guardrail (a restart
     never *locks out* extraction). The daily rollover means yesterday's spend
     never blocks today.

Budget decisions live here too (``over_global_budget`` / ``should_downgrade`` /
``over_subscription_budget``) so the worker stays declarative.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Blended USD per 1K tokens, keyed by a substring of the litellm model string.
# Longest-matching key wins so "gpt-4o-mini" beats "gpt-4o". Values are
# deliberately conservative (rounded up) — over-estimating spend errs toward
# downgrading sooner, which is the safe direction for a guardrail.
_MODEL_PRICE_PER_1K: dict[str, float] = {
    "gpt-4o-mini": 0.0004,
    "gpt-4o": 0.0075,
    "gpt-4.1-mini": 0.0006,
    "gpt-4.1": 0.006,
    "o4-mini": 0.0022,
    "claude-3-haiku": 0.0008,
    "claude-3-5-haiku": 0.0024,
    "claude-3-5-sonnet": 0.009,
    "claude-3-sonnet": 0.009,
    "claude-3-opus": 0.045,
    "deepseek": 0.0006,
    "llama": 0.0,  # local (ollama/groq-free tier) — treat as free
    "gemini-1.5-flash": 0.0004,
    "gemini-1.5-pro": 0.0035,
}

# Fallback when no key matches — assume a mid-cheap cloud model rather than 0
# so an unknown model still counts against the budget.
_DEFAULT_PRICE_PER_1K = 0.001


def estimate_cost_usd(model: Optional[str], tokens: int) -> float:
    """Estimate the USD cost of ``tokens`` on ``model`` (blended rate).

    Returns 0.0 for non-positive token counts or a missing model. Matching is
    case-insensitive longest-substring against the price table.
    """
    if not model or tokens <= 0:
        return 0.0
    m = model.lower()
    best_key: Optional[str] = None
    for key in _MODEL_PRICE_PER_1K:
        if key in m and (best_key is None or len(key) > len(best_key)):
            best_key = key
    price = _MODEL_PRICE_PER_1K[best_key] if best_key else _DEFAULT_PRICE_PER_1K
    return (tokens / 1000.0) * price


def _today() -> str:
    return datetime.utcnow().date().isoformat()


class KnowledgeBudgetTracker:
    """Thread-safe, per-UTC-day ledger of extraction spend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # day -> total USD
        self._global: dict[str, float] = {}
        # day -> {subscription_id -> USD}
        self._per_sub: dict[str, dict[str, float]] = {}
        # day -> downgrade count
        self._downgrades: dict[str, int] = {}

    def record(
        self,
        usd: float,
        *,
        subscription_id: Optional[str] = None,
        day: Optional[str] = None,
    ) -> None:
        if usd <= 0:
            return
        day = day or _today()
        with self._lock:
            self._global[day] = self._global.get(day, 0.0) + usd
            if subscription_id:
                bucket = self._per_sub.setdefault(day, {})
                bucket[subscription_id] = bucket.get(subscription_id, 0.0) + usd

    def note_downgrade(self, *, day: Optional[str] = None) -> None:
        day = day or _today()
        with self._lock:
            self._downgrades[day] = self._downgrades.get(day, 0) + 1

    def spent_today(self, *, day: Optional[str] = None) -> float:
        day = day or _today()
        with self._lock:
            return self._global.get(day, 0.0)

    def spent_for_subscription(
        self, subscription_id: str, *, day: Optional[str] = None
    ) -> float:
        day = day or _today()
        with self._lock:
            return self._per_sub.get(day, {}).get(subscription_id, 0.0)

    def downgrades_today(self, *, day: Optional[str] = None) -> int:
        day = day or _today()
        with self._lock:
            return self._downgrades.get(day, 0)

    # ===== Budget decisions =====

    def over_global_budget(
        self, daily_budget_usd: Optional[float], *, day: Optional[str] = None
    ) -> bool:
        """True when today's global spend meets/exceeds the daily budget.

        ``None`` budget means "unlimited" — never over.
        """
        if daily_budget_usd is None or daily_budget_usd <= 0:
            return False
        return self.spent_today(day=day) >= daily_budget_usd

    def should_downgrade(
        self, threshold_usd: Optional[float], *, day: Optional[str] = None
    ) -> bool:
        """True once today's spend crosses the model-downgrade threshold.

        ``None`` threshold means "never downgrade".
        """
        if threshold_usd is None or threshold_usd <= 0:
            return False
        return self.spent_today(day=day) >= threshold_usd

    def over_subscription_budget(
        self,
        subscription_id: str,
        override_usd: Optional[float],
        *,
        day: Optional[str] = None,
    ) -> bool:
        """True when a subscription's own spend meets/exceeds its override budget."""
        if override_usd is None or override_usd <= 0:
            return False
        return self.spent_for_subscription(subscription_id, day=day) >= override_usd

    def reset(self) -> None:
        """Clear all ledgers (test hook / manual flush)."""
        with self._lock:
            self._global.clear()
            self._per_sub.clear()
            self._downgrades.clear()


_tracker: Optional[KnowledgeBudgetTracker] = None


def get_budget_tracker() -> KnowledgeBudgetTracker:
    """Process-wide singleton tracker."""
    global _tracker
    if _tracker is None:
        _tracker = KnowledgeBudgetTracker()
    return _tracker
