"""Turn a prediction's free text into something a machine can check.

Two pure parsers, no I/O (KOL scorecard step 2, docs/kol-scorecard.md):

- `parse_due_date(horizon, made_on)` — "end of Q3", "within 6 months",
  "by March 2027" → the last day the call can still come true.
- `parse_price_target(text)` — "ETH flips $6k" → ETH price >= 6000.

Both are deliberately conservative: anything ambiguous (two assets, two
numbers, "after the halving") returns None and is left for the reviewer to
set by hand. A wrong automatic target publishes a wrong ✅/❌ under someone's
name, which is worse than no target at all.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

# ---------- due dates ----------

_MONTHS = {
    name: i
    for i, names in enumerate(
        [(), ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
         ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
         ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
         ("december", "dec")]
    )
    for name in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "eighteen": 18, "twenty-four": 24,
}
_COUNT_RE = r"(\d+|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _year_from(token: Optional[str], made_on: date) -> Optional[int]:
    if not token:
        return None
    token = token.strip().lstrip("'")
    if token == "next year":
        return made_on.year + 1
    if token == "this year":
        return made_on.year
    if token.isdigit():
        year = int(token)
        return 2000 + year if year < 100 else year
    return None


def _first_on_or_after(made_on: date, candidate) -> date:
    """`candidate(year)` for this year, or next year if that is already past."""
    d = candidate(made_on.year)
    return d if d >= made_on else candidate(made_on.year + 1)


def parse_due_date(horizon: Optional[str], made_on: date) -> Optional[date]:
    """The last day a prediction can still come true, or None if unclear.

    `made_on` is when the call was made; relative horizons count from it,
    and a bare "March" or "Q3" means the next one on or after it.
    """
    if not horizon:
        return None
    h = horizon.strip().lower()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", h)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None

    m = re.search(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", h) or \
        re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", h)
    if m:
        a, b, year = m.groups()
        month, day = (_MONTHS[a], int(b)) if a in _MONTHS else (_MONTHS[b], int(a))
        try:
            return date(int(year), month, day)
        except ValueError:
            return None

    m = re.search(r"\bq([1-4])\b(?:\s*(?:of\s+)?('?\d{2,4}\b|next year|this year))?", h)
    if m:
        quarter_end = lambda y: _month_end(y, int(m[1]) * 3)  # noqa: E731
        year = _year_from(m[2], made_on)
        return quarter_end(year) if year else _first_on_or_after(made_on, quarter_end)

    m = re.search(r"\bh([12])\b(?:\s*(?:of\s+)?('?\d{2,4}\b|next year|this year))?", h)
    if m:
        half_end = lambda y: _month_end(y, int(m[1]) * 6)  # noqa: E731
        year = _year_from(m[2], made_on)
        return half_end(year) if year else _first_on_or_after(made_on, half_end)

    m = re.search(rf"\b(?:in|within|next|over the next)?\s*{_COUNT_RE}\s+(day|week|month|year)s?\b", h)
    if m:
        n = int(m[1]) if m[1].isdigit() else _NUMBER_WORDS[m[1]]
        unit = m[2]
        if unit == "day":
            return made_on + timedelta(days=n)
        if unit == "week":
            return made_on + timedelta(weeks=n)
        return _add_months(made_on, n * (12 if unit == "year" else 1))

    if re.search(r"\b(end of (the )?next year|next year)\b", h):
        return date(made_on.year + 1, 12, 31)
    if re.search(r"\b(end of (the |this )?year|eoy|year[- ]end|this year)\b", h):
        return date(made_on.year, 12, 31)
    if re.search(r"\bnext month\b", h):
        nxt = _add_months(made_on.replace(day=1), 1)
        return _month_end(nxt.year, nxt.month)
    if re.search(r"\b(end of (the |this )?month|this month)\b", h):
        return _month_end(made_on.year, made_on.month)
    if re.search(r"\bnext quarter\b", h):
        nxt = _add_months(made_on.replace(day=1), 3)
        return _month_end(nxt.year, ((nxt.month - 1) // 3 + 1) * 3)
    if re.search(r"\b(end of (the |this )?quarter|this quarter)\b", h):
        return _month_end(made_on.year, ((made_on.month - 1) // 3 + 1) * 3)
    if re.search(r"\bnext week\b", h):
        return made_on + timedelta(days=14 - made_on.weekday() - 1)

    m = re.search(rf"\b({_MONTH_RE})\b\.?(?:\s+('?\d{{2,4}}\b|next year|this year))?", h)
    if m:
        month = _MONTHS[m[1]]
        year = _year_from(m[2], made_on)
        if year:
            return _month_end(year, month)
        return _first_on_or_after(made_on, lambda y: _month_end(y, month))

    m = re.search(r"\b(20\d{2})\b", h)
    if m:
        return date(int(m[1]), 12, 31)
    return None


# ---------- price targets ----------


@dataclass(frozen=True)
class PriceTarget:
    asset: str  # ticker, e.g. "ETH"
    coin_id: str  # CoinGecko id, e.g. "ethereum"
    comparator: str  # ">=" or "<="
    value: float
    metric: str = "price"


# ticker -> (CoinGecko id, lowercase aliases, aliases that only count in CAPS).
# "link", "ton" and "hype" are ordinary words, so they need the ticker spelling.
_ASSETS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "BTC": ("bitcoin", ("btc", "bitcoin"), ()),
    "ETH": ("ethereum", ("eth", "ether", "ethereum"), ()),
    "SOL": ("solana", ("sol", "solana"), ()),
    "BNB": ("binancecoin", ("bnb",), ()),
    "XRP": ("ripple", ("xrp", "ripple"), ()),
    "DOGE": ("dogecoin", ("doge", "dogecoin"), ()),
    "ADA": ("cardano", ("ada", "cardano"), ()),
    "AVAX": ("avalanche-2", ("avax", "avalanche"), ()),
    "LINK": ("chainlink", ("chainlink",), ("LINK",)),
    "TON": ("the-open-network", ("toncoin",), ("TON",)),
    "SUI": ("sui", ("sui",), ()),
    "HYPE": ("hyperliquid", ("hyperliquid",), ("HYPE",)),
}

_BELOW_RE = re.compile(
    r"\b(below|under|beneath|drops? to|dips? to|falls? to|crash(?:es)? to|down to|bottoms?"
    r"(?: out)? at|sinks? to|retraces? to)\b",
    re.I,
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_VALUE_RE = re.compile(
    r"(?<![\w.])(\$)?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?"
    r"(k|mm|m|b|thousand|million|billion)?(?![\w%])",
    re.I,
)
# Numbers that are counts or times, not prices.
_NOT_A_PRICE_AFTER = re.compile(
    r"\s*(x\b|%|percent|days?|weeks?|months?|years?|hours?|minutes?|times|people|"
    r"bps|basis)", re.I
)


def _assets_in(text: str) -> set[str]:
    found = set()
    lower = text.lower()
    for ticker, (_, aliases, caps_only) in _ASSETS.items():
        if any(re.search(rf"(?<![\w$]){re.escape(a)}(?!\w)", lower) for a in aliases) or any(
            re.search(rf"(?<![\w$]){re.escape(a)}(?!\w)", text) for a in caps_only
        ):
            found.add(ticker)
    return found


def _prices_in(text: str) -> list[float]:
    values = []
    for m in _VALUE_RE.finditer(text):
        dollar, digits, scale = m[1], m[2], (m[3] or "").lower()
        if _NOT_A_PRICE_AFTER.match(text, m.end()):
            continue
        value = float(digits.replace(",", "")) * _SCALE.get(scale, 1)
        if not dollar and not scale and "," not in digits:
            # A bare number: reject years and quarter/ordinal-sized noise.
            if re.fullmatch(r"(19|20)\d{2}", digits) or value < 10:
                continue
        values.append(value)
    return values


def parse_price_target(text: Optional[str]) -> Optional[PriceTarget]:
    """One asset and one price in the claim, or None.

    Direction defaults to "at or above"; wording like "drops to" / "below"
    flips it. Relative calls ("ETH outperforms BTC") have no price and
    return None.
    """
    if not text:
        return None
    assets = _assets_in(text)
    prices = _prices_in(text)
    if len(assets) != 1 or len(set(prices)) != 1:
        return None
    ticker = assets.pop()
    return PriceTarget(
        asset=ticker,
        coin_id=_ASSETS[ticker][0],
        comparator="<=" if _BELOW_RE.search(text) else ">=",
        value=prices[0],
    )


def coin_id_for(asset: str) -> Optional[str]:
    """CoinGecko id for a ticker the parser knows, for manual targets."""
    entry = _ASSETS.get(asset.strip().upper())
    return entry[0] if entry else None
