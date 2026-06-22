# Knowledge Schema (P18)

The canonical, machine-readable substrate every downstream consumer reads from —
MCP (P19), the Digest pipeline (P20), RAG/search (P10/P11), and intelligent
webhooks (P16). "AI-friendly" here does **not** mean "emit JSON"; it means
**citable, timestamped, speaker-attributed, confidence-scored** records that can
be cross-referenced across episodes.

This document is the contract. If you change a wire format, bump the version (see
[Versioning](#versioning)) and update this file in the same change.

- **Source of truth for models:** `app/core/knowledge_schema.py`
- **Persistence:** `app/core/job_store/` (`_knowledge.py`, `_backfill.py`, `_schema.py`)
- **Extraction:** `app/core/knowledge_extractor.py` (+ `entity_canonicalizer.py`, `topic_canonicalizer.py`, prediction enrichment)
- **Orchestration:** `app/core/knowledge_backfill.py`, auto-run hook in `app/core/workflow.py`

---

## Design principles

1. **Embeddings are generic and backend-swappable.** A single `embeddings`
   table keyed by `(object_type, object_id, model)` stores float32 vectors +
   cached norm for fast cosine. Segments, claims, entities, topics, and episodes
   all embed uniformly. No Chroma/pgvector yet — but the `EmbeddingStore`
   interface makes that a one-file swap when ANN/multi-tenant scale demands it.
2. **LLM selection is task-based, never globally hardcoded.** Presets map a
   *task* to a provider+model, each overridable in `ai_settings.task_presets`.
   See [LLM task presets](#llm-task-presets).
3. **Backfill is lazy, resumable, and never blocking.** New transcripts are
   *enqueued* (not extracted inline) and a background worker drains the queue.
   On-demand reads trigger extraction for small jobs. See [Run-state machine](#run-state-machine).
4. **Confidence: store everything above a sanity floor, filter at the surface.**
   Storage floor is `0.1`; query endpoints filter higher. No early data
   destruction. See [Confidence model](#confidence-model).

---

## Versioning

Two independent integers travel on every claim (and conceptually on every
record):

| Constant | Location | Meaning | Bump when |
|----------|----------|---------|-----------|
| `SCHEMA_VERSION` | `knowledge_schema.py` | Wire format / field shape of a record | A field is added/removed/retyped, or its semantics change |
| `EXTRACTION_VERSION` | `knowledge_schema.py` | Prompt + extractor revision that produced the record | The prompt, chunking, or post-processing changes such that re-running on the same input could yield different/better output |

Both currently `1`.

**Re-extraction policy.** `claim_id` is a stable SHA-256 over the claim's citable
identity (`text` + `episode_id` + `speaker` + `timestamp_start`), so re-running
extraction on the same episode **upserts** rather than duplicates. This makes
re-extraction well-defined:

- Re-running with a higher `EXTRACTION_VERSION` lets you tell *genuinely new*
  claims (new `claim_id`) apart from *re-found* ones (same `claim_id`, possibly
  refined fields).
- `POST /api/jobs/{id}/extract-knowledge` is the manual re-extract trigger; the
  backfill worker bumps `knowledge_version` on the job row on every successful run.
- Operator-set state is never clobbered by re-extraction: a prediction's
  `resolution`/`resolution_note`/`resolved_by` survive re-runs (the enricher only
  refreshes lifecycle *inputs* like `target_horizon`).

`knowledge_version` (on the `jobs` row) is a separate per-job counter advanced by
each successful backfill run — distinct from the per-record `extraction_version`.

---

## Models

All models live in `app/core/knowledge_schema.py` as Pydantic v2 (`extra="ignore"`,
so unexpected LLM keys are dropped rather than crashing the pipeline). Each model
has a `*Draft` sibling = the raw shape the LLM emits, before the canonical IDs
and version stamps are attached.

### Claim

A discrete, citable statement. The atom of the KB.

| Field | Type | Notes |
|-------|------|-------|
| `claim_id` | str | Stable hash (`compute_claim_id`) — cross-job dedup key |
| `episode_id` | str | Source job/episode id |
| `text` | str | Self-contained restatement (understandable without surrounding context) |
| `speaker` | str? | Diarization label if available |
| `timestamp_start` / `timestamp_end` | float | Seconds; `end` clamped to `start` if the LLM inverts them |
| `claim_type` | `ClaimType` | `fact \| opinion \| prediction \| question \| recommendation` |
| `confidence` | float 0–1 | LLM self-reported |
| `evidence_excerpt` | str | Verbatim supporting quote |
| `entity_ids` | str[] | Canonical entity refs (Phase B) |
| `topic_ids` | str[] | Topic refs — denormalized cache of `claim_topics` join (Phase C.1) |
| `source_url` | str? | Source episode URL |
| `extraction_version` / `schema_version` | int | See [Versioning](#versioning) |
| `created_at` | datetime? | Set by the store |

`ClaimDraft` carries `entity_refs: list[str]` — entity **names**, not IDs. The LLM
doesn't know our canonical IDs; names are resolved post-extraction by the
canonicalizer, which is the source of truth.

### Entity

A canonical person / company / ticker / project / product / place. **Dual identity:**

- `entity_id` — stable `ent_<8-char hash>` PK, used as the FK on claims and mentions.
- `slug` — human-readable, type-prefixed kebab label (e.g. `person:vitalik-buterin`),
  UNIQUE and *mutable*. Regenerable on rename.

Claims and mentions reference `entity_id`, never `slug`, so a merge or rename is a
pointer update, not a rewrite. Name/alias **embedding lives in the generic
`embeddings` table**, never inline. Other fields: `name`, `entity_type`
(`EntityType`), `aliases[]`, `confidence`, `created_at`.

Canonicalization (`entity_canonicalizer.py`): normalize → embed → cosine match
against same-type candidates (**≥ 0.85** reuse, merging aliases) → else mint a new
id + slug (sequence-suffixed on slug collision).

### EntityMention

One observation of an entity inside a transcript. Timestamp is the primary anchor;
char offsets are best-effort.

| Field | Type | Notes |
|-------|------|-------|
| `entity_id`, `episode_id` | str | |
| `claim_id` | str? | Nullable — entities can appear without a claim |
| `chunk_id` | str? | e.g. `<episode>:chunk:<idx>` |
| `raw_text` | str | Surface form as spoken (pre-normalization) |
| `start_char` / `end_char` | int? | Offset into chunk text; NULL when unresolvable |
| `timestamp` | float? | |
| `speaker` | str? | |

### Topic

An abstraction over a cluster of claims (Phase C.1, second-pass aggregation). Flat
graph — **no `type`, no `slug`** (topics aren't deep-linked the way entities are).
`description` carries the LLM's abstraction and is embedded alongside `name` for
canonicalization.

| Field | Type | Notes |
|-------|------|-------|
| `topic_id` | str | Stable `top_<8-char hash>` PK |
| `name` | str | Short canonical label |
| `description` | str | Embedded with the name (cosine **≥ 0.90** reuse) |
| `aliases` | str[] | |
| `confidence` | float 0–1 | From the aggregation pass |

The `claim_topics` join table is the **source of truth**; `Claim.topic_ids` is a
denormalized read cache. `ClaimTopicEdge` is the wire shape for those edges.

### Prediction

A `claim_type=prediction` claim enriched with lifecycle fields (Phase C.2). Stored
in a **dedicated `predictions` table** (FK `claim_id`, UNIQUE) — not as nullable
columns on `claims` — because a prediction is the start of a workflow, not a flag.

| Field | Type | Notes |
|-------|------|-------|
| `claim_id` | str | FK to `claims.claim_id` (UNIQUE) |
| `target_horizon` | str? | **Free-form** (date / interval / event / "unspecified"). Stored verbatim — structured parsing is a deliberate non-goal; the LLM is unreliable at dates and we'd rather keep the signal |
| `conditions` | str? | Stated preconditions |
| `falsifiable_by` | str? | What evidence would resolve it |
| `resolution` | `Resolution` | `pending \| true \| false \| unresolvable` |
| `resolution_note` | str? | Operator note at resolution time |
| `resolved_at` / `resolved_by` | datetime? / str? | Set when resolution moves off `pending` |

Operator-set resolution is never overwritten by re-extraction.

### Embedding (generic)

Not a Pydantic model on the wire — a storage row in the `embeddings` table:
`(object_type, object_id, model, dim, vector_blob, norm)`. `object_type` ∈
`episode | segment | claim | entity | topic`. `vector_blob` is numpy float32 bytes;
`norm` is cached for cosine speed. This table also seeds P10 semantic search.

### ExtractionRunResult

The outcome of one extract run for one episode (not persisted; the in-process
return value): `claims`, `entities`, `mentions`, `topics`, `claim_topic_edges`,
`predictions`, plus `chunks_processed` / `chunks_failed` / `failures` /
`tokens_used` / `model` / `provider` / `success`. `success=False` only when *every*
chunk failed, so a partial failure never wipes prior data.

---

## Confidence model

- **Storage floor `0.1`** (`STORAGE_CONFIDENCE_FLOOR` in `knowledge_extractor.py`):
  anything at or above is persisted with its raw value; below is dropped at
  extraction time.
- **Surface thresholds** (applied per query via `min_confidence`): API `0.5`,
  UI `0.6`, digest/alerts `0.7`. Contradiction detection (P13) can opt into the
  long tail down to the floor.
- Confidence (extraction certainty) is **orthogonal** to a speaker-conviction tag
  (hedged vs. asserted) — the latter is future work.

---

## Run-state machine

`knowledge_status` on the `jobs` row (Phase C.3, `_backfill.py`):

```
none ──enqueue──▶ pending ──acquire_lock──▶ running
                                              │
                          ┌───────────────────┤
                          ▼                    ▼
                        ready                failed ──(retry)──▶ pending
                   (knowledge_version++)
```

- `acquire_knowledge_lock` is a single conditional UPDATE — two workers racing
  for the same job can never both win. Locks older than the TTL (crashed worker)
  are reclaimed lazily on acquire and eagerly by `reap_stale_knowledge_locks`.
- The synchronous extract route writes legacy `extracting`/`complete`, treated as
  `running`/`ready` aliases everywhere, so the two paths interoperate.

**Two triggers, one machinery:**

1. **Auto-run (P18 Phase D):** when a transcription completes,
   `WorkflowProcessor._enqueue_knowledge_extraction` flips the job to `pending`
   (gated on `knowledge_auto_extract`, default on). Non-blocking, idempotent,
   best-effort — a KB hiccup never fails the transcription.
2. **Background worker:** `KnowledgeBackfillWorker` ticks every
   `knowledge_backfill_interval`s, drains a priority-ordered batch under locks.
3. **On-demand:** `GET /api/jobs/{id}/knowledge` on a `pending` job runs inline
   when the transcript is ≤ `knowledge_inline_max_segments`, else enqueues and
   returns `202 Accepted`.

**Cost guardrails** (`knowledge_budget.py`): a per-UTC-day in-memory ledger.
`knowledge_daily_budget_usd` is a hard stop; `knowledge_model_downgrade_threshold_usd`
switches to a cheaper same-provider model. Both default to `None` = unlimited. A
process restart never *locks out* extraction (the safe direction for a guardrail).

---

## LLM task presets

`app/core/llm_presets.py` — `get_provider_for_task(task, *, downgrade=False)`.
Resolution chain: `ai_settings.task_presets` override → baked-in default preset
(if the user has a working provider) → user's configured provider.

| Task | Intent |
|------|--------|
| `extract` | Cheap, structured, deterministic — claim/entity extraction |
| `summarize` | Cheap-medium — topic aggregation |
| `synthesize` | Better model allowed — P20 cross-source synthesis |
| `chat` | User-selected — P19 `ask_episode` / RAG |

`downgrade=True` swaps to a cheaper model from the same provider (so resolved
creds/base_url still apply); already-cheap models aren't double-downgraded.

---

## Storage tables

Created/migrated in `app/core/job_store/_schema.py`:

- `claims`, `entities`, `entity_mentions`, `topics`, `claim_topics`, `predictions`
- `embeddings` (generic, see above)
- `extraction_failures` (quarantine — malformed LLM output, captured with
  `raw_output` for prompt-drift debugging; never crashes the pipeline)
- `jobs` columns: `knowledge_status`, `knowledge_version`, `knowledge_locked_at`,
  `knowledge_worker_id`

A single transactional `replace_claims_for_job` writes claims + entities + mentions
+ topics + edges + predictions together, so an episode's knowledge lands or rolls
back atomically.

---

## API surface

All under the `/api` prefix; all require the API key.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/jobs/{id}/extract-knowledge` | Manual (re-)extract; bumps `extraction_version` semantics |
| `GET` | `/jobs/{id}/knowledge?min_confidence=` | All knowledge for an episode; 202 + `run_state` when pending/running; runs inline for small pending jobs |
| `POST` | `/jobs/{id}/knowledge/enqueue` | Idempotent enqueue for a pending job |
| `GET` | `/knowledge/backfill-status` | Pending/running/ready counts, today's spend, downgrades |
| `GET` | `/claims?topic=&speaker=&entity=&since=&type=&min_confidence=` | Library-wide claim query |
| `GET` | `/entities` · `/entities/{id_or_slug}` · `/entities/{id_or_slug}/mentions` | Entity browse (accepts hash id or slug) |
| `GET` | `/topics` · `/topics/{id}` · `/topics/{id}/claims` | Topic browse |
| `GET` | `/predictions?resolution=pending` · `/predictions/{claim_id}` | Prediction browse |
| `POST` | `/predictions/{claim_id}/resolve` | Set resolution (reverting to pending is forced through DELETE) |
| `DELETE` | `/predictions/{claim_id}/resolve` | Revert to pending |

Export formats (claims): JSON, JSONL (one claim per line for LLM consumption), CSV.

---

## Phase history

P18 shipped incrementally; each phase landed on its own so quality regressions stay
attributable to the right surface (prompts vs. schema vs. orchestration).

| Phase | What |
|-------|------|
| A | Claims-only MVP: schema + extractor + `claims`/`embeddings`/`extraction_failures` + preset registry + extract/get/list endpoints |
| B | Entities + canonicalization (`ent_` ids + slugs, cosine ≥ 0.85, mentions) |
| C.1 | Topics aggregation (second pass, cosine ≥ 0.90, `claim_topics` join) |
| C.2 | Predictions lifecycle (dedicated table, resolve/revert) |
| C.3 | Backfill worker + cost guardrails (run-state machine, claim-lock, per-day budget) |
| D | Pipeline auto-run (this hook), this schema doc, coverage |

See `docs/todo.md` (P18 section) for per-phase "what shipped" detail.
