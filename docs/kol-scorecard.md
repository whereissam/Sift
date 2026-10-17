# KOL Prediction Scorecard

Status: **steps 1–2 built** (2026-10-17) — KOLs, speaker mapping, review queue;
due dates, price targets, automatic price resolution. Steps 3–4 are still design.

Track what crypto KOLs predict on X Spaces and podcasts, check the calls when
they come due, and publish a weekly digest and leaderboard. It reuses the
knowledge layer (`claims`, `predictions`, `entities`, contradictions,
subscriptions, digests) and adds only what a public scorecard needs.

## What exists vs. what is missing

| Need | Exists | Missing |
|---|---|---|
| A call with quote + timestamp | `claims` (text, speaker, timestamps, evidence_excerpt, source_url) | — |
| Call lifecycle | `predictions` (target_horizon, conditions, resolution, resolved_by) | a real **due date** — `target_horizon` is free text |
| Who said it | `claims.speaker` (free text / diarization label) | link to a **canonical person** + their handles |
| What exactly was predicted | claim text | **structured target** so price calls resolve automatically |
| Safe to publish | — | **human review** of quote + speaker (defamation guard) |
| Leaderboard | — | **scoring** that can't be gamed |

## Data model additions

```sql
-- A KOL is an `entities` row of type person plus public handles.
CREATE TABLE kol_handles (
    entity_id   TEXT NOT NULL REFERENCES entities(entity_id),
    platform    TEXT NOT NULL,          -- x | youtube | podcast
    handle      TEXT NOT NULL,
    PRIMARY KEY (platform, handle)
);

-- Who is behind a speaker label in one episode.
-- v1: set by hand in review; v2: suggested from host metadata / voice.
CREATE TABLE episode_speakers (
    episode_id   TEXT NOT NULL,
    speaker      TEXT NOT NULL,         -- as it appears on claims.speaker
    entity_id    TEXT NOT NULL REFERENCES entities(entity_id),
    confirmed_by TEXT,                  -- null = suggestion only
    PRIMARY KEY (episode_id, speaker)
);

ALTER TABLE predictions ADD COLUMN due_at TEXT;           -- parsed from target_horizon
ALTER TABLE predictions ADD COLUMN review_status TEXT NOT NULL DEFAULT 'unreviewed';
                                                          -- unreviewed | verified | rejected
ALTER TABLE predictions ADD COLUMN conviction REAL;       -- "for sure"≈0.9 … "maybe"≈0.55

-- Only for calls that can be checked mechanically.
CREATE TABLE prediction_targets (
    claim_id    TEXT PRIMARY KEY REFERENCES predictions(claim_id) ON DELETE CASCADE,
    asset       TEXT NOT NULL,          -- BTC, ETH, SOL …
    metric      TEXT NOT NULL,          -- price | mcap | dominance
    comparator  TEXT NOT NULL,          -- >= | <=
    value       REAL NOT NULL,
    baseline    REAL,                   -- value when the call was made
    evidence    TEXT                    -- snapshot / source at resolution
);
```

Add `void` to `Resolution` for calls whose condition never happened.

## Lifecycle

```
subscription (Space / podcast)
  → transcribe → claims → prediction drafts                 (exists)
  → speaker label → KOL                                     (episode_speakers)
  → parse due_at + structured target                        (extraction)
  → REVIEW QUEUE: quote right? speaker right?               ← nothing public before this
  → published as an open call
  → daily checker after due_at
        price-type → auto-resolve from a price feed, store the snapshot as evidence
        other      → resolve queue: ✅ / ❌ / void / too vague
  → weekly digest + leaderboard
```

## Scoring

- **Score:** Wilson lower bound of the hit rate (penalises small samples);
  show only KOLs with ≥ 5 resolved calls.
- **Boldness:** weight hits by `|target − baseline| / baseline`, capped.
- **Too-vague rate:** share of calls that could not be checked.
- **Calibration (later):** Brier score against `conviction`.

## Weekly digest template

```markdown
# Crypto Calls Weekly — <date range>
Tracking N sources · X new calls · Y came due

## ✅❌ Calls that came due
- ❌ **@kol** — "<quote>" · said <date> [▶ mm:ss]
  <asset> on <due date>: <value> (<source> snapshot)

## 🆕 Boldest new calls
- **@kol**: "<quote>" · conviction: high · due <date> [▶ mm:ss]

## 🔁 Changed their mind            (contradictions by speaker)
- **@kol** said "<a>" (<date> [▶]) → "<b>" (<date> [▶])

## 🤝 Consensus vs. contrarian
- N of M KOLs bullish on <asset>; contrarian: **@kol** [▶]

## 🏆 Leaderboard (min. 5 resolved)
| # | KOL | Resolved | Hit rate | Score | Too vague |

---
AI-assisted, human-reviewed. Every quote links to the exact moment.
Spotted a mistake? → [request a correction]
```

## Safety rules

- Every published claim links to the exact timestamp of the original.
- Nothing is published before quote and speaker are human-verified.
- Label as AI-assisted; keep a visible correction path and act on it fast.
- Store transcripts and claims, not media.

## Build order (~2 weeks)

1. ✅ `kol_handles` + `episode_speakers` + review page (approve quote, assign speaker).
   Shipped as `predictions.review_status` (unreviewed / verified / rejected),
   `/api/kols`, `/api/episodes/{id}/speakers`, `/api/predictions/review-queue`,
   `POST /api/predictions/{id}/review`, and Library → Review calls. Verifying
   requires an assigned speaker. Re-extraction keeps review *and* resolution
   (it previously reset resolution).
2. ✅ `due_at` + structured-target extraction; daily checker with a price feed.
   Built as deterministic parsers (`app/knowledge/prediction_targets.py`) rather
   than an LLM pass — ambiguous text stays unparsed for the reviewer — and
   `app/knowledge/prediction_checker.py` (CoinGecko, every 6 h + `POST
   /api/predictions/check`). Only *verified* calls are resolved; a call resolves
   true the moment the target is hit, false once the due date passes. The
   `conviction` column was deferred to step 3 (it only feeds calibration).
3. Scoring queries; markdown digest from the template
4. Run on ~20 sources, review, publish issue #1, measure sharing
