"""Lexical normalization for topic names — cheap first pass before embedding.

Topic drift is more often a *naming* problem than a semantic one. A tiny
normalization layer catches the common tail (tickers, pluralization,
whitespace) before we pay a cosine round against the embedding index.

Three passes, composed:
  1. `normalize_for_embedding` — lowercase + collapse whitespace (shared
     with `embedding_store`, so the cache key lines up).
  2. Ticker expansion — a small curated map covering the obvious wins
     (crypto tickers, a few common AI acronyms). Extend as the tail grows.
  3. Conservative last-word plural collapse — strip trailing `-s` only
     when the word is long enough, not `-ss`/`-es`/`-ies`, and only on
     the last token.  "AI agents" → "ai agent", but "gas" / "iOS" /
     "business" / "stories" / "analysis" stay intact.

Intentionally does not stem, lemmatize, or strip stop words — those
destroy signal the embedding model was trained to pick up. The whole
point of having the canonicalizer on top is that we can leave semantic
comparison to cosine; normalization just collapses the mechanical tail.
"""

from __future__ import annotations

from .embedding_store import normalize_for_embedding

# Curated ticker / acronym → canonical-name map.
# Keep small and explicit — wrong expansion is worse than no expansion.
# Matching is done per-token on the already-lowercased form.
TICKER_MAP: dict[str, str] = {
    # Crypto tickers
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "ltc": "litecoin",
    "bnb": "binance coin",
    "usdt": "tether",
    "usdc": "usd coin",
    # AI / tech acronyms that read better fully expanded in topic labels.
    # ("ai" alone is intentionally NOT expanded — too many false merges.)
    "llm": "large language model",
    "llms": "large language models",
    "rag": "retrieval augmented generation",
    "mcp": "model context protocol",
}


def _collapse_last_word_plural(text: str) -> str:
    """Conservative singularization of the final token only.

    Rules (all must hold to strip the trailing `s`):
      - Token length >= 5 (avoids collapsing `gas`, `ios`, `us`, etc.)
      - Ends in `s`
      - Does NOT end in `ss` (business, miss)
      - Does NOT end in `us` / `is` / `os` (these look plural but aren't
        — bonus, analysis, kudos)
      - Does NOT end in `ies` (cities → city would need y-restore, which
        we don't want to own in v1 — leave -ies plurals alone)

    Note that simple `-es` plurals like `prices` → `price` and
    `markets` → `market` DO get collapsed via the generic trailing-s
    strip. Genuine -es plurals like `matches` / `churches` become
    `matche` / `churche` — grammatically imperfect but internally
    consistent (both surface forms normalize to the same string, which
    is what the cosine index needs). Topic labels rarely contain such
    words, and the alternative (skipping -es entirely) costs us the
    much more common `prices`/`markets` case.

    Returns the text with the last token singularized when eligible,
    otherwise returns it unchanged.
    """
    if not text:
        return text
    tokens = text.split(" ")
    last = tokens[-1]
    if len(last) < 5:
        return text
    if not last.endswith("s"):
        return text
    for suffix in ("ss", "us", "is", "os", "ies"):
        if last.endswith(suffix):
            return text
    tokens[-1] = last[:-1]
    return " ".join(tokens)


def normalize_topic_for_match(text: str) -> str:
    """Full normalization pipeline used by the topic canonicalizer.

    Output is guaranteed lowercase, whitespace-collapsed, ticker-expanded,
    and conservatively singularized. Same input → same output across
    runs (pure function, no state).
    """
    base = normalize_for_embedding(text)
    if not base:
        return ""
    tokens = base.split(" ")
    tokens = [TICKER_MAP.get(t, t) for t in tokens]
    expanded = " ".join(tokens)
    return _collapse_last_word_plural(expanded)
