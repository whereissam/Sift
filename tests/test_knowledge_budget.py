"""Tests for app/core/knowledge_budget.py (P18 Phase C.3)."""

from __future__ import annotations

import pytest

from app.core.knowledge_budget import (
    KnowledgeBudgetTracker,
    estimate_cost_usd,
    get_budget_tracker,
)


class TestEstimateCost:
    def test_zero_tokens_is_free(self):
        assert estimate_cost_usd("gpt-4o", 0) == 0.0

    def test_missing_model_is_free(self):
        assert estimate_cost_usd(None, 1000) == 0.0

    def test_longest_substring_wins(self):
        # gpt-4o-mini must not be priced as the pricier gpt-4o.
        mini = estimate_cost_usd("gpt-4o-mini", 1_000_000)
        full = estimate_cost_usd("gpt-4o", 1_000_000)
        assert mini < full

    def test_local_model_is_free(self):
        assert estimate_cost_usd("ollama/llama3.2", 1_000_000) == 0.0

    def test_unknown_model_uses_fallback(self):
        # Non-zero so unknown models still count against budget.
        assert estimate_cost_usd("some-mystery-model", 1_000_000) > 0.0

    def test_cost_scales_with_tokens(self):
        one = estimate_cost_usd("gpt-4o", 1000)
        two = estimate_cost_usd("gpt-4o", 2000)
        assert two == pytest.approx(2 * one)


class TestTracker:
    def test_record_and_spent(self):
        t = KnowledgeBudgetTracker()
        t.record(1.5, day="2026-06-22")
        t.record(0.5, day="2026-06-22")
        assert t.spent_today(day="2026-06-22") == pytest.approx(2.0)

    def test_daily_rollover(self):
        t = KnowledgeBudgetTracker()
        t.record(5.0, day="2026-06-21")
        assert t.spent_today(day="2026-06-22") == 0.0

    def test_negative_record_ignored(self):
        t = KnowledgeBudgetTracker()
        t.record(-1.0, day="2026-06-22")
        assert t.spent_today(day="2026-06-22") == 0.0

    def test_per_subscription_isolation(self):
        t = KnowledgeBudgetTracker()
        t.record(1.0, subscription_id="sub-a", day="d")
        t.record(2.0, subscription_id="sub-b", day="d")
        assert t.spent_for_subscription("sub-a", day="d") == pytest.approx(1.0)
        assert t.spent_for_subscription("sub-b", day="d") == pytest.approx(2.0)
        # Both still roll up into the global total.
        assert t.spent_today(day="d") == pytest.approx(3.0)

    def test_over_global_budget(self):
        t = KnowledgeBudgetTracker()
        t.record(2.0, day="d")
        assert t.over_global_budget(2.0, day="d") is True
        assert t.over_global_budget(5.0, day="d") is False

    def test_none_budget_is_unlimited(self):
        t = KnowledgeBudgetTracker()
        t.record(1000.0, day="d")
        assert t.over_global_budget(None, day="d") is False

    def test_should_downgrade_threshold(self):
        t = KnowledgeBudgetTracker()
        t.record(0.9, day="d")
        assert t.should_downgrade(1.0, day="d") is False
        t.record(0.2, day="d")
        assert t.should_downgrade(1.0, day="d") is True

    def test_over_subscription_budget(self):
        t = KnowledgeBudgetTracker()
        t.record(3.0, subscription_id="sub-a", day="d")
        assert t.over_subscription_budget("sub-a", 2.0, day="d") is True
        assert t.over_subscription_budget("sub-a", 10.0, day="d") is False
        assert t.over_subscription_budget("sub-b", 2.0, day="d") is False

    def test_downgrade_counter(self):
        t = KnowledgeBudgetTracker()
        t.note_downgrade(day="d")
        t.note_downgrade(day="d")
        assert t.downgrades_today(day="d") == 2

    def test_reset_clears_everything(self):
        t = KnowledgeBudgetTracker()
        t.record(5.0, subscription_id="sub-a", day="d")
        t.note_downgrade(day="d")
        t.reset()
        assert t.spent_today(day="d") == 0.0
        assert t.spent_for_subscription("sub-a", day="d") == 0.0
        assert t.downgrades_today(day="d") == 0

    def test_singleton_is_stable(self):
        assert get_budget_tracker() is get_budget_tracker()
