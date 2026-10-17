"""Parsers that turn a prediction's text into a due date and a price target."""

from datetime import date

import pytest

from app.knowledge.prediction_targets import (
    PriceTarget,
    coin_id_for,
    parse_due_date,
    parse_price_target,
)

MADE = date(2026, 6, 2)  # a Tuesday


@pytest.mark.parametrize(
    "horizon, expected",
    [
        ("2026-12-31", date(2026, 12, 31)),
        ("by March 31, 2027", date(2027, 3, 31)),
        ("31st March 2027", date(2027, 3, 31)),
        ("end of Q3", date(2026, 9, 30)),
        ("Q1", date(2027, 3, 31)),  # Q1 2026 already over
        ("by Q2 next year", date(2027, 6, 30)),
        ("Q4 2026", date(2026, 12, 31)),
        ("Q3 '27", date(2027, 9, 30)),
        ("H2", date(2026, 12, 31)),
        ("within 6 months", date(2026, 12, 2)),
        ("in two weeks", date(2026, 6, 16)),
        ("next 30 days", date(2026, 7, 2)),
        ("in a year", date(2027, 6, 2)),
        ("by end of year", date(2026, 12, 31)),
        ("EOY", date(2026, 12, 31)),
        ("next year", date(2027, 12, 31)),
        ("next month", date(2026, 7, 31)),
        ("this quarter", date(2026, 6, 30)),
        ("next quarter", date(2026, 9, 30)),
        ("by March", date(2027, 3, 31)),  # next March after June
        ("end of September", date(2026, 9, 30)),
        ("by Sept 2027", date(2027, 9, 30)),
        ("by 2028", date(2028, 12, 31)),
    ],
)
def test_due_dates(horizon, expected):
    assert parse_due_date(horizon, MADE) == expected


@pytest.mark.parametrize(
    "horizon", [None, "", "after the next halving", "soon", "eventually", "2026-02-30"]
)
def test_unclear_horizons_stay_unparsed(horizon):
    assert parse_due_date(horizon, MADE) is None


def test_month_rollover_clamps_day():
    assert parse_due_date("in 1 month", date(2026, 1, 31)) == date(2026, 2, 28)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ETH flips 6k by end of Q3", PriceTarget("ETH", "ethereum", ">=", 6000)),
        ("Bitcoin will hit $150,000 next year", PriceTarget("BTC", "bitcoin", ">=", 150000)),
        ("BTC to 200k", PriceTarget("BTC", "bitcoin", ">=", 200000)),
        ("SOL drops to $80", PriceTarget("SOL", "solana", "<=", 80)),
        ("I think ether falls below 2,500", PriceTarget("ETH", "ethereum", "<=", 2500)),
        ("DOGE reaches $1", PriceTarget("DOGE", "dogecoin", ">=", 1)),
        ("LINK to $50", PriceTarget("LINK", "chainlink", ">=", 50)),
        ("btc at 1.5m by 2030", PriceTarget("BTC", "bitcoin", ">=", 1_500_000)),
    ],
)
def test_price_targets(text, expected):
    assert parse_price_target(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "ETH outperforms BTC this cycle",  # two assets, no price
        "Alt season starts this month",  # no asset
        "BTC goes from 100k to 150k",  # two prices
        "ETH up 50% by Q3",  # percentage, not a price
        "SOL 3x within 6 months",  # multiple, not a price
        "BTC new highs in 2027",  # a year is not a price
        "there's a link in my bio, it'll hit 10k followers",  # 'link' as a word
        "a ton of people will buy at 100",  # 'ton' as a word
    ],
)
def test_ambiguous_or_non_price_calls_are_left_alone(text):
    assert parse_price_target(text) is None


def test_coin_id_lookup():
    assert coin_id_for("eth") == "ethereum"
    assert coin_id_for("PEPE") is None
