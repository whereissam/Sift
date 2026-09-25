# Sift Feature Roadmap

## Vision

Sift is evolving from a media utility into an **AI-First Knowledge Extraction Platform**. The user's true intent isn't to own an MP3 — it's to get the *insight* trapped inside that MP3. Downloading is a legacy middle step that becomes invisible as the platform matures.

> **Shipped work** — completed phases and their implementation notes moved to
> [shipped.md](shipped.md). This file is open work only.

## Priority Matrix — 2 open

### Media output (2026-07-15)

- [x] `to-video`: turn an audio file into a YouTube-ready MP4 (still image …
  - [ ] Follow-up: `--image` custom-image CLI flag (Python API already accepts `image`)
  - [ ] Follow-up: direct URL input for `to-video` (currently local files only)

### v2.0 — AI-Native Intelligence (Next)

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| Semantic Indexing & Vector Search | High | Very High | P10 🚧 (Phase 1 shipped) |
| Ask Audio (RAG Chat Interface) | High | Very High | P11 🚧 (Phase 1 shipped) |
| Agentic Ingest Pipeline | Medium | Very High | P12 🚧 (Phase 1 shipped) |
| Psychographic Mapping & Contradiction Detection | Medium | High | P13 🚧 (Contradictions shipped) |
| Content Distiller (Multi-Source Briefing) | Medium | High | P14 🚧 (Phase 1 shipped) |
| Neural Audio Reconstruction | Very High | Medium | P15 |
| Intelligent Webhooks & Agentic Notifications | Low | High | P16 🚧 (Phase 1 shipped) |
| Structured Data Extraction | Medium | High | P17 ✅ (Notion deferred) |

### v2.5 — Capability Surface & Knowledge Pipeline (Planned)

> The shift: from "an app that ships connectors" to "a capability surface". Obsidian, Notion, Logseq become *agent-side targets*, not Sift-side integrations. Single-episode summary becomes a *feature*; continuous cross-source knowledge monitoring becomes the *product*.

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| AI-Friendly Knowledge Schema (Claims, Entities, Predictions) | Medium | Very High | P18 ✅ |
| Sift MCP Server (Capability Surface) | Medium | Very High | P19 🚧 (Phase 1 shipped) |
| Subscription Digest Pipeline (Cross-Episode Synthesis) | High | Very High | P20 🚧 (Phase 1 shipped) |
| Vault & Note-App Export Channels (Obsidian / Notion / Logseq) | Low | High | P21 🚧 (Obsidian/Logseq shipped; Notion deferred) |

**Dependency order:** P18 is the substrate (canonical schema). P19 (MCP) and P20 (Digest) both read from it. P21 (Vault Export) consumes from P19 and P20.

---

## P0: Smart Metadata & Tagging ✅ COMPLETED — 1 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [ ] Add option to customize filename template (e.g., `{artist} - {title}`)

## P2: Browser Extension ✅ COMPLETED — 6 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [ ] Show notification/toast on successful queue
- [ ] Optional: Show download progress in extension popup
### WXT rewrite (2026-07-02)
- [ ] Publish to Chrome Web Store / AMO, then remove `browser-extension/`
### Universal Capture (design + plan ready; not yet built)
- [ ] Phase 1 — server: `Platform.GENERIC`, `GenericDownloader`, `POST /api/capture`
- [ ] Phase 2 — detection engine (content-script DOM scan + `webRequest` sniff + per-tab registry)
- [ ] Phase 3 — capture popup (candidate list, format/quality, poll → `chrome.downloads`)

## P3: LLM-Powered Summarization ✅ COMPLETED — 2 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [ ] Cache summaries in database
- [ ] Export summary alongside transcript

## P4: Watch Folders & Subscriptions ✅ COMPLETED — 1 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
  - [ ] X user's Spaces (if API allows)

## P5: Audio Pre-processing (Voice Isolation) ✅ COMPLETED — 2 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
  - [ ] DeepFilterNet (ML-based noise reduction)
  - [ ] Silero VAD for voice activity detection

## P7: Sentiment & Vibe Analysis ✅ COMPLETED — 3 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Future Enhancements (moved to P13)
- [ ] Contradiction detection (cross-reference statements)
- [ ] Psychographic mapping (persuasion techniques, topic deflection)
- [ ] Cross-platform speaker tracking

## P8: Social Media Clip Generator ✅ COMPLETED — 2 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
  - [ ] Consider speaker energy/sentiment in selection (future enhancement)
  - [ ] Download clips as batch (future enhancement)

## P9: AI Translation & Dubbing (Translation ✅ COMPLETED) — 18 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Dubbing Tasks (Future)
- [ ] Text-to-Speech (TTS) integration:
  - [ ] Research TTS options:
    - [ ] Coqui TTS (open source)
    - [ ] OpenVoice (voice cloning)
    - [ ] ElevenLabs API (high quality)
    - [ ] Azure Speech Services
  - [ ] Voice cloning from original speaker
  - [ ] Maintain original pacing and timing
- [ ] Create dubbing service (`app/ingest/dubber.py`):
  - [ ] Sync translated speech with original timing
  - [ ] Handle speed adjustments for different language lengths
  - [ ] Mix dubbed audio with original background sounds (optional)
- [ ] Web UI dubbing features:
  - [ ] "Generate Dubbed Audio" button
  - [ ] Voice selection/cloning options
- [ ] Export options:
  - [ ] Dubbed audio file
  - [ ] Bilingual subtitle file

## Future Ideas (v1.x Backlog) — 5 open

- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox) - In progress
- [ ] Podcast RSS feed generation from downloaded content
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts
---

# v2.0: AI-Native Intelligence Platform

> The shift: from "Where should I save this file?" to "What do you want to learn from this URL?"

---

## P10: Semantic Indexing & Vector Search 🚧 (Phase 1 shipped) — 8 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
  - [~] Support multiple embedding models:
    - [ ] OpenAI `text-embedding-3-small` (high quality, API) — deferred
    - [ ] Ollama embedding models (local, privacy-first) — deferred
- [ ] Web UI search interface — deferred:
  - [ ] Global search bar in top nav
  - [ ] Results show matching segments with context, clickable timestamps
  - [ ] "Search within this transcript" option on job detail page
- [~] Incremental re-indexing — manual per-job re-index

## P11: Ask Audio (RAG Chat Interface) 🚧 (Phase 1 shipped) — 11 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [~] Chat modes:
  - [ ] **Multi-Job**: Select 2+ jobs and chat across them — deferred
- [ ] Web UI chat interface — deferred:
  - [ ] Chat panel on job detail page (slide-out or tab)
  - [ ] Global "Ask Audio" page for library-wide queries
  - [ ] Message history with source citations (clickable timestamps)
  - [ ] Suggested questions based on transcript content
- [ ] Telegram bot integration — deferred:
  - [ ] Send a link → bot downloads & indexes → user asks questions → bot answers with timestamps
  - [ ] `/ask <question>` - Query the most recent download
- [ ] Conversation memory: follow-up questions understand prior context — deferred

## P12: Agentic Ingest Pipeline 🚧 (Phase 1 shipped) — 11 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [~] Create pipeline orchestrator (`app/pipeline/agentic_pipeline.py`):
  - [ ] Parallel execution where possible — deferred (stages run sequentially)
- [~] Pipeline configuration:
  - [ ] Per-subscription default pipeline — deferred
  - [ ] Global default pipeline in settings — deferred (code default: `deep`)
- [ ] Web UI pipeline status — deferred:
  - [ ] Multi-stage progress indicator (not just a download bar)
  - [ ] "Knowledge Canvas" view: shows extracted entities, summary, topics as the pipeline runs
  - [ ] Pipeline complete notification with quick-access to all outputs
- [~] API endpoints:
  - [ ] `POST /api/pipelines` - Create custom pipeline profile — deferred

## P13: Psychographic Mapping & Contradiction Detection 🚧 (Contradictions shipped) — 12 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [ ] Extend sentiment analyzer with LLM reasoning layer — deferred:
  - [ ] For each flagged segment, generate: *why* the tone shifted, what triggered it
  - [ ] Detect persuasion techniques (appeal to authority, FOMO, etc.)
  - [ ] Identify when speakers deflect questions or change topics abruptly
- [~] Cross-platform social graph (for multi-source analysis):
  - [ ] Track statements over time / evolving-position timeline — deferred
- [ ] Web UI — deferred:
  - [ ] "Rhetoric Map" view: visual graph of claims, connections, and contradictions
  - [ ] Contradiction cards with side-by-side quotes and timestamps
  - [ ] Credibility score per speaker (based on consistency)
- [~] API endpoints:
  - [ ] `POST /jobs/{id}/analyze-rhetoric` - Run deep rhetorical analysis — deferred with the rhetoric layer

## P14: Content Distiller (Multi-Source Briefing) 🚧 (Phase 1 shipped) — 7 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [~] Create content distiller service (`app/knowledge/distiller.py`):
  - [~] Generate unified output formats:
    - [ ] Audio briefing (TTS-generated 5-minute summary — future, depends on P9 dubbing)
- [~] Web UI:
  - [ ] "Distill" button to select multiple jobs — deferred
  - [ ] Briefing viewer with per-source attribution — deferred
- [~] API endpoints:

## P15: Neural Audio Reconstruction — 19 open

**Goal:** Go beyond FFmpeg filters — use AI to re-synthesize low-quality audio into studio-grade clarity.

### Tasks

- [ ] Research and integrate neural audio models:
  - [ ] **ElevenLabs Speech-to-Speech** (high quality, API-based)
  - [ ] **OpenVoice** (open source voice cloning)
  - [ ] **Resemble.AI** (voice cloning + enhancement)
  - [ ] **AudioSR** (audio super-resolution, open source)
- [ ] Create neural enhancement service (`app/ingest/neural_enhancer.py`):
  - [ ] Speaker voice profiling: analyze audio to build speaker voice model
  - [ ] Re-synthesize speech using the voice profile at higher fidelity
  - [ ] Preserve original timing, emphasis, and prosody
  - [ ] Fallback to FFmpeg enhancement when neural models unavailable
- [ ] Enhancement levels:
  - [ ] **Classic**: FFmpeg-based (current, fast, free)
  - [ ] **Neural**: AI-powered reconstruction (slower, higher quality)
  - [ ] **Studio**: Full re-synthesis with noise removal + clarity boost (API-dependent)
- [ ] Web UI:
  - [ ] Enhancement level selector (Classic / Neural / Studio)
  - [ ] A/B comparison player (original vs. enhanced)
- [ ] API endpoints:
  - [ ] `POST /jobs/{id}/enhance` with `mode` parameter (classic/neural/studio)

---

## P16: Intelligent Webhooks & Agentic Notifications 🚧 (Phase 1 shipped) — 8 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [~] Extend webhook payload with AI-generated content:
- [~] Webhook templates:
  - [ ] Custom templates with variable substitution — deferred
- [ ] Smart notification routing — deferred:
  - [ ] Route different types of content to different webhooks/channels
  - [ ] Example: Financial content → Slack #trading, Tech discussions → Slack #engineering
  - [ ] Urgency detection: flag time-sensitive information for immediate notification
- [~] API:

## P17: Structured Data Extraction ✅ (Notion deferred) — 2 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Tasks
- [~] Output formats:
  - [ ] Notion page (via API integration) — deferred

## P18: AI-Friendly Knowledge Schema — 48 open

**Goal:** Standardize a canonical, machine-readable schema for everything Sift extracts, so every downstream system (MCP, Digest, RAG, search, webhooks) reads from the same substrate. AI-friendly is not "output JSON" — it's *citable, timestamped, speaker-attributed, confidence-scored* claims that can be cross-referenced across episodes.

> The substrate that makes P19 (MCP) and P20 (Digest) actually useful, not just plausible. Without this, every consumer reinvents extraction.

### Locked design decisions (v1)

1. **Embeddings: SQLite blob + Python cosine, behind a thin retrieval interface.** Generic `embeddings` table keyed by `(object_type, object_id, model)` so we can embed segments / claims / entities / episodes uniformly. No Chroma / pgvector yet — but the abstraction layer from day 1 makes that swap a one-file change when ANN / multi-tenant scale demands it. Same table seeds P10 Semantic Search later.
2. **LLM: reuse existing AI Settings as the control plane, layered with task-based presets.** No globally hardcoded provider. Presets per task type:
   - `extract` — cheap, structured, deterministic (default: `gpt-4o-mini`-class)
   - `summarize` — cheap-medium
   - `synthesize` — better model allowed (used by P20 cross-source synthesis)
   - `chat` — user-selected (used by P19 `ask_episode`)

   Each preset is overridable in `ai_settings`; user can map any task to any configured provider.
3. **Backfill: lazy and resumable, never blocking.** New jobs run extraction immediately. Existing transcripts get marked `knowledge_status = pending` and a background worker processes them by priority: (1) most recent, (2) user-opened, (3) subscribed / high-value. On-demand extraction kicks in when an API call hits an unextracted job, then caches.
4. **Confidence: store everything above a sanity floor, filter at the surface.** No early data destruction. Storage floor: `0.1`. Default surface thresholds: API=`0.5`, UI=`0.6`, digest/alerts=`0.7+`. Contradiction detection can opt into the long tail. `extraction_version` is tracked per record so re-extraction with improved prompts is well-defined.

### Schema (Pydantic models)

- [ ] **Claim** — `claim_id` (stable hash for cross-job dedup), `episode_id`, `text`, `speaker`, `timestamp_start/end`, `claim_type` (fact / opinion / prediction / question / recommendation), `confidence`, `evidence_excerpt`, `entity_ids[]`, `topic_ids[]`, `extraction_version`, `schema_version`, `source_url`
- [ ] **Entity** — `entity_id` (stable short-hash PK, e.g. `ent_8f3a91c2`), `slug` (human-readable label, e.g. `person:vitalik-buterin`, UNIQUE, mutable/regenerable), `name`, `entity_type` (person / company / ticker / project / product / place), `aliases[]`, `confidence` (LLM self-reported), `created_at`. Embedding lives in the generic `embeddings` table, **not** inline. Claims and mentions reference `entity_id`, never `slug` — merges become pointer updates, not rewrites.
- [ ] **EntityMention** — `entity_id`, `episode_id`, `claim_id` (nullable — entities can exist without a claim reference), `chunk_id`, `raw_text` (surface form as the speaker said it), `start_char`/`end_char` (optional offsets into chunk text for UI highlighting), `timestamp`, `speaker`
- [ ] **Topic** — `topic_id`, `name`, `segments[]` (episode_id + time range), `sentiment_summary`, `frequency_over_time`
- [ ] **Prediction** (extends Claim) — `target_horizon`, `conditions`, `falsifiable_by`, `resolution` (pending / true / false / unresolvable), `resolved_at`
- [ ] **Embedding** (generic, separate table) — `object_type` (episode / segment / claim / entity), `object_id`, `model`, `dim`, `vector_blob` (numpy float32 bytes), `norm` (cached for cosine speed)

### Tasks

- [ ] Schema spec doc (`docs/knowledge-schema.md`) with explicit `schema_version` and `extraction_version` policy + re-extraction rules
- [ ] Task preset registry (`app/knowledge/llm_presets.py`):
  - [ ] Map `extract | summarize | synthesize | chat` → provider+model
  - [ ] Default presets in code, overridable via `ai_settings` table (new `task_presets` JSON column)
  - [ ] `get_provider_for_task(task)` helper used by extractor / summarizer / RAG / digest
- [ ] Knowledge extractor service (`app/knowledge/knowledge_extractor.py`):
  - [ ] LLM-powered extraction with structured output (function calling / JSON mode via litellm)
  - [ ] Per-segment processing (~3000 tokens, 200-token overlap) with episode metadata as context
  - [ ] Pulls model from `get_provider_for_task("extract")`, not directly from AI Settings
  - [ ] One unified prompt per chunk → `{claims, entities, topics, predictions}`
  - [ ] Schema validation on every LLM output (malformed → quarantine table, never crash pipeline)
- [ ] Embedding store (`app/knowledge/embedding_store.py`):
  - [ ] Thin retrieval interface (`embed`, `upsert`, `query_topk`, `cosine`)
  - [ ] SQLite blob backend with cached `norm` for fast cosine
  - [ ] Driver pattern → swap to Chroma / pgvector later without touching callers
  - [ ] Local model: `sentence-transformers/all-MiniLM-L6-v2` (~80MB)
- [ ] Storage (extend `JobStore._init_db`):
  - [ ] Normalized SQLite tables: `claims`, `entities`, `entity_mentions`, `topics`, `predictions`, `claim_entities`, `claim_topics`
  - [ ] Generic `embeddings` table (`object_type`, `object_id`, `model`, `dim`, `vector_blob`, `norm`)
  - [ ] Quarantine table for malformed extractions (`extraction_failures`)
  - [ ] Add `knowledge_status` column on `jobs`: `none | pending | extracting | complete | failed`
- [ ] Cross-job normalization:
  - [ ] Embed entity names; cosine ≥ 0.85 → merge with existing entity, else create new
  - [ ] Speaker matching across episodes (name+show heuristic for v1, voice embedding later)
- [ ] Backfill worker (`app/workers/knowledge_backfill.py`):
  - [ ] On first deploy: mark all existing jobs with transcripts as `knowledge_status = pending`
  - [ ] Process priority queue: recent → user-opened → subscribed → rest
  - [ ] On-demand path: API call to `GET /jobs/{id}/knowledge` on `pending` job triggers immediate extraction (and caches)
  - [ ] Per-feed daily extraction budget (cost guardrail, downgrade model when over)
- [ ] Confidence model:
  - [ ] Storage floor: `0.1` (anything above gets persisted, raw value preserved)
  - [ ] Per-claim model self-reported confidence
  - [ ] Speaker conviction tag (hedged vs. asserted) — orthogonal to extraction confidence
  - [ ] All query endpoints accept `min_confidence` param; defaults: API=`0.5`, UI=`0.6`, digest=`0.7`
- [ ] Export formats: JSON, JSONL (one claim per line for LLM consumption), CSV
- [ ] API endpoints:
  - [ ] `GET /jobs/{id}/knowledge?min_confidence=...` — all knowledge for an episode (triggers on-demand extract if `pending`)
  - [ ] `GET /api/claims?topic=...&speaker=...&entity=...&since=...&type=...&min_confidence=...`
  - [ ] `GET /api/entities/{id}/mentions`
  - [ ] `POST /jobs/{id}/extract-knowledge` — manual trigger / re-extract (bumps `extraction_version`)
  - [ ] `GET /api/topics`
  - [ ] `GET /api/predictions?resolution=pending`

### Phased rollout (within P18)

1. **Phase A — Claims-only MVP** ✅ **SHIPPED**: schema + extractor + `claims` / `embeddings` / `extraction_failures` tables + task preset registry + `POST /jobs/{id}/extract-knowledge` + `GET /jobs/{id}/knowledge` + `GET /api/claims`. New jobs only (manual trigger; backfill in Phase C). 45 new tests, all passing.
2. **Phase B — Entities + canonicalization** ✅ **SHIPPED**: filled `embedding_store.embed()` (sentence-transformers lazy-loaded, module cache, `to_thread` batch), added `entities` + `entity_mentions` tables (dual-ID: `ent_<hash>` PK + UNIQUE slug), shipped `entity_canonicalizer.py` (normalize → cache → cosine ≥0.85 reuse → else mint with slug-collision sequence suffix), extended `LLM_RESPONSE_SCHEMA` to `{claims, entities}` with per-claim `entity_refs`, shipped `GET /api/entities*`. Entities + mentions ride in the same tx as claims. **56 new tests**, 154/154 total green.
3. **Phase C — Topics + Predictions + backfill worker** (split into C.1 / C.2 / C.3 by change kind — classification / schema semantics / control-plane):
   - **C.1 — Topics** ✅ **SHIPPED**: second-pass aggregation over already-extracted claims, `topics` + `claim_topics` tables (join is source of truth; `Claim.topic_ids` JSON kept as denormalized cache for fast per-claim render), `topic_canonicalizer` (reuses Phase B embedding infra, threshold 0.90, lexical-normalize layer with ticker expansion + conservative plural collapse), `GET /api/topics*` endpoints. Gracefully degrades when `summarize` provider missing, `claim_count < 3`, or aggregator throws — topic pass never blocks claims. **54 new tests**, 208/208 suite green.
   - **C.2 — Predictions** ✅ **SHIPPED**: dedicated `predictions` table (FK `claim_id` PK), lifecycle columns (`target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolution_note`, `resolved_at`, `resolved_by`), `PredictionExtractor` second-pass enrichment scoped to `claim_type=prediction`, `/api/predictions` list/get/resolve/revert. Re-extraction refines lifecycle inputs but never clobbers operator-set resolution. **44 new tests**, 252/252 suite green.
   - **C.3 — Backfill worker + cost guardrails** ✅ **SHIPPED**: both-trigger backfill (background worker + route-triggered on-demand), idempotent enqueue with status machine `pending | running | ready | failed` + `knowledge_version` + `locked_at`/`worker_id` claim-lock, stale-lock reaper, in-memory per-UTC-day budget tracker (global daily budget + model-downgrade threshold) + per-subscription override/priority-tier columns, `POST /jobs/{id}/knowledge/enqueue`, `GET /api/knowledge/backfill-status`, 202-on-pending GET behavior. **60 new tests**, 412/412 suite green.
4. **Phase D — Pipeline auto-run + tests + docs** ✅ **SHIPPED**: completed-transcription hook in `workflow.py` auto-enqueues knowledge extraction (gated on `knowledge_auto_extract`, non-blocking, idempotent, best-effort), canonical `docs/knowledge-schema.md` spec doc, `pytest-cov` tooling + coverage lift — the P18 knowledge surface now sits at ~93% with no module below 81%. **35 new tests**, 447/447 suite green.

**Why split Phase C into three passes**: topics = classification layer, predictions = schema semantics (changes claim wire format), backfill = operational control plane. Bundling them produces a release where quality drops can't be attributed to the right surface (prompts vs schema vs orchestration). Each pass has its own tx/schema/test churn and should land on its own.

### Phase B — locked decisions (review-refined)

Defaults from the original proposal, tightened after external review (weak-signal handling, dual-ID, cache, warmup, spans):

1. **One LLM call per chunk — entities treated as weak signals.** Extend `LLM_RESPONSE_SCHEMA` to `{claims, entities}`. Each entity carries its own `confidence`; each claim carries `entity_refs: [name]` (strings, not IDs) resolved post-extraction by name → canonical `entity_id`. Entities may appear without any claim referring to them (LLMs miss/hallucinate refs). Cheaper (1 call/chunk), revertible to two calls if recall drops. *Why weak-signal*: entities are lower-entropy but higher-precision-sensitive than claims — canonicalization (not the LLM) is the source of truth.
2. **Dual identity: stable `entity_id` (PK) + mutable `slug` (label).** `entity_id` = `ent_<8-char hash>` — collision-free, opaque, what claims and mentions reference. `slug` = type-prefixed kebab (`person:vitalik-buterin`) for debug and API surface, UNIQUE, sequence-suffix on slug collision only. No suffix hell on `entity_id`; merges = pointer updates. Rejects the original single-slug-as-PK plan.
3. **Normalize → batch → embed off the event loop, with cache.** `normalize_for_embedding(text)` (lowercase, strip, collapse whitespace) runs before embedding. One `model.encode([normalized_names])` per chunk wrapped in `asyncio.to_thread`. Module-level `embedding_cache[normalized_name] → vector` skips recomputation across chunks/jobs (same entities recur constantly). Amortizes the model invocation cost and kills per-entity overhead.
4. **Lazy model load + optional warmup hook.** `sentence-transformers/all-MiniLM-L6-v2` (~80MB) loaded on first `embed()` call, cached at module level. Optional opt-in `warmup()` hook (env flag or settings toggle) fires a background preload after app boot to dodge the first-request ~1-3s latency spike. Default OFF — don't slow boot for users who never trigger extraction.
5. **Same-transaction persistence.** Entity rows + mention rows + claim updates land inside the existing `replace_claims_for_job` transaction (extended) so a partial failure rolls back together — never leaves orphan mentions pointing at non-existent claims.
6. **Mention-level char spans (best-effort).** `EntityMention` stores `chunk_id`, `raw_text`, and optional `start_char`/`end_char` (populated via string search in the chunk when resolvable, NULL otherwise) in addition to `(entity_id, episode_id, claim_id?, timestamp, speaker)`. Powers future UI highlighting, debug trails, and downstream agent context selection. Timestamp stays the primary anchor; offsets are a bonus when cheap.

### Deferred to later phases (flagged by review, not blocking Phase B)

- **Alias table** + type-aware disambiguation (Apple the company vs. the fruit; Base the chain vs. the word) — Phase C or P13.
- **Rule-based overrides** for known sticky cases (`ETH` ↔ `Ethereum` ↔ `Ether`) — add as a small seed dictionary if cosine proves insufficient; do not design around it yet.
- **Cross-episode entity evolution / role graphs** — P19 MCP territory.

### Phase B — files to ship

**New:**
- `app/knowledge/entity_canonicalizer.py` — `canonicalize(name, entity_type) → entity_id`; pipeline: normalize → cache lookup → embed on miss → `query_topk(object_type="entity", filter by entity_type)` → ≥0.85 cosine reuses (adds surface form to aliases if novel) → else mint new `ent_<8-char hash>` + generate slug (type-prefix + kebab of normalized name, sequence-suffix on slug collision only). Stores normalized form + vector in `embeddings` table keyed by `entity_id`.
- `app/api/entity_routes.py` — `GET /api/entities` (filter by `entity_type`, `since`, `slug`), `GET /api/entities/{id_or_slug}` (accepts either `entity_id` or slug), `GET /api/entities/{id_or_slug}/mentions`

**Extend:**
- `app/knowledge/knowledge_schema.py` — add `Entity` (dual-ID: `entity_id` PK + `slug`), `EntityMention` (with `chunk_id`, `raw_text`, optional `start_char`/`end_char`, nullable `claim_id`), `EntityDraft`, `EntityType` enum; extend `LLM_RESPONSE_SCHEMA` to `{claims, entities}` — each entity has its own `confidence`; claims ref entities by string name via `entity_refs: [name]` (weak-signal, resolved post-extraction)
- `app/knowledge/embedding_store.py` — add `normalize_for_embedding(text)` helper (lowercase, strip, collapse whitespace); fill `embed(texts: list[str]) -> list[list[float]]` (sentence-transformers/all-MiniLM-L6-v2, lazy + module-cached model, off event loop via `to_thread`, batched across the input list); module-level `embedding_cache[normalized_text] → vector`; `query_topk(object_type, model, vector, k=1, filter: dict | None)` for cosine search with type-scoped candidate set; optional `warmup()` entrypoint for opt-in background preload
- `app/store.py` — `entities` (PK `entity_id`, UNIQUE `slug`, indexed on `entity_type`) + `entity_mentions` (char offsets, nullable `claim_id`, indexed on `entity_id` and `episode_id`) tables; `upsert_entity`, `get_entity_by_id`, `get_entity_by_slug`, `list_entities` (type/since filters), `find_entities_by_type` (powers cosine candidate set for canonicalizer), `add_entity_mention`, `get_mentions_for_entity`
- `app/knowledge/knowledge_extractor.py` — after claims validate, walk extracted entities (independently of claim.entity_refs) → canonicalizer → build `name → entity_id` map for the chunk → resolve each claim's `entity_refs` through it to populate `Claim.entity_ids` → emit `EntityMention` rows with chunk span data (best-effort string search for char offsets). Unreferenced entities still persist. Route entities + mentions + claims through the extended `replace_claims_for_job` in one transaction.
- `app/api/__init__.py` — register entity router
- `pyproject.toml` — add `sentence-transformers>=3.0` dependency (pulls torch on first install; ~500MB disk)

**Tests:**
- `tests/test_entity_canonicalizer.py` — normalization; embedding cache hit/miss; cosine ≥0.85 reuse (adds novel surface as alias); below-threshold creates new; slug collision → sequence suffix on slug only; `entity_id` stays hash-based (mock encoder for determinism)
- `tests/test_embedding_store_search.py` — `query_topk` correctness over real numpy vectors; type-scoped filter; normalize_for_embedding helper; cache round-trip
- `tests/test_entity_api.py` — list (by type/since), get by `entity_id`, get by slug, mentions listing
- Extend `tests/test_knowledge_extractor.py` — `{claims, entities}` LLM response → `entity_ids` resolved on claims, mentions written with char offsets when findable; entity-only (no claim ref) path persists; weak-signal tolerance (claim references a name the LLM didn't list as an entity — skip gracefully)
- Extend `tests/test_knowledge_store.py` — entity + mention CRUD; dual-ID lookup (by `entity_id` and by slug); transactional replace including entities + mentions rolls back together

### Phase C.1 — locked decisions (Topics)

1. **Second-pass aggregation, not inline with claims.** Chunk pass stays `{claims, entities}`; a separate per-episode LLM call takes the validated claims as input and emits `{topics}`. *Why:* claims are the distilled semantic units, topics are an abstraction over them. Single-purpose prompts are easier to debug and retry; one episode-level call instead of N chunk-level kitchen-sink prompts.
2. **Hash-only topic IDs (`top_<8-char hash>`), no slug.** Entities earned their slug because they're frequently deep-linked in UI/MCP exports. Topics are fuzzier and the kebab label (`topic:bitcoin-price-action`) reads worse than on entities.
3. **Trigger inline when `claim_count >= 3`.** Below that, aggregation has too little signal to justify an extra LLM call. Above it, cost is bounded to one call per episode.
4. **LLM preset: `summarize` (cheap-medium).** Already configured in `llm_presets.py`. `synthesize` reserved for P20 cross-episode.
5. **Canonicalization threshold 0.90** (vs. 0.85 for entities). Topics drift more on surface form ("Bitcoin price" vs "BTC price action"); over-merging corrupts the graph in ways that are painful to unwind. Erring toward under-merge is safer to tune.
6. **Lexical normalization layer up front**, before embedding:
   - Ticker → name expansion (`btc` → `bitcoin`, `eth` → `ethereum`, `sol` → `solana`, small curated map — extend as the tail grows).
   - Whitespace/case collapse (shared with `normalize_for_embedding`).
   - Conservative last-word plural collapse (strip trailing `-s` only; skip `-ss`/`-es`/`-ies` and tokens under 5 chars).
   - Rationale: topic drift is more often a *naming* problem than a semantic one — cheap normalization catches the common tail without paying a cosine round.
7. **Embedding source: `f"{name}: {description}"`.** Topic names alone are short and ambiguous; description carries the LLM's abstraction. Both stored separately so the recipe can be re-run later without losing source text.
8. **Claim↔topic edges: join table is the source of truth; `claims.topic_ids` JSON is a denormalized cache.** `claim_topics(claim_id, topic_id, confidence)` powers reverse queries (`GET /api/topics/{id}/claims`); JSON column stays populated for cheap per-claim render. Always write both in the same tx; readers treat the join as authoritative.

### Phase C.1 — files to ship ✅ (all shipped in `7d3ce0f`)

**New:**
**Extend:**
**Tests:**
### Phase C.2 — locked decisions (Predictions)

1. **Dedicated `predictions` table, FK `claim_id UNIQUE`.** Physically separate from `claims`. Prediction is semantically a `claim_type`, but the lifecycle columns (`target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolved_at`) aren't "just nullable fields" — they're the start of a lifecycle. Separate table keeps claim rows clean and makes future expansion (resolution events, resolution evidence, confidence recalibration, tracking dashboards) land on a dedicated row instead of adding more nullable columns.
2. Prediction-specific extraction prompts + validation; API endpoints `GET /api/predictions?resolution=pending`, `POST /api/predictions/{id}/resolve`.

### Phase C.2 — tasks ✅ (all shipped)

**Schema:**
**Storage:**
**Extraction:**
**API:**
**Tests:**
**Docs:**
### Phase C.3 — locked decisions (Backfill + cost guardrails)

1. **Both-trigger backfill** (background scheduler + route-triggered on-demand). Background-only feels stale; on-demand-only misses cold inventory. Both is the right default — dedup is the interesting engineering problem.
2. **Status machine: `pending | running | ready | failed`** + `knowledge_version` + `locked_at` / `worker_id` for claim-lock. Idempotent enqueue: calling enqueue twice on the same pending job is a no-op.
3. **Route behavior on `/jobs/{id}/knowledge`:** `ready` → return cached. `running` → return in-progress status (client polls). `pending` → acquire lock, run inline if cheap enough, otherwise enqueue and return `202 Accepted`.
4. **Budgets: global default + per-subscription override.** Global daily extraction budget in settings; optional per-feed override + priority tier; downgrade to cheaper `extract` model when over budget. Top-priority feeds stay on the better model longer.

### Phase C.3 — tasks

**Storage + state machine:**
**Background worker:**
**Route behavior:**
**Budget tiers:**
**API:**
**Tests:**
**Docs:**

## P19: Sift MCP Server (Capability Surface) — 13 open

**Goal:** Expose Sift as an MCP (Model Context Protocol) server so Claude Desktop, Cursor, and custom agents can call Sift primitives directly. This shifts Sift from "an app that ships connectors" to "a capability surface" — Obsidian / Notion / Logseq become *agent-side targets*, not Sift-side integrations.

> The unlock: build N agent skills on top of one MCP server, instead of N×M point-to-point connectors. Inspired by the `podwise-cli` MCP surface, but goes deeper because Sift has the structured knowledge layer (P18) underneath.

> **Phase 1 status (✅ SHIPPED):** the MCP scaffold + every tool backed by P18 / existing routes is live (HTTP-client architecture, `X-API-Key` passthrough, stdio transport). Tools needing unbuilt phases are still unchecked and intentionally *not registered* on the server yet. See "P19 Phase 1 — what shipped" below.

### Tool surface (stable JSON Schema per tool)

- [ ] **Cross-episode synthesis** (deferred — depends on P13/P20)
  - [ ] `compare_episodes(episode_ids[], topic?)` — agreements / disagreements
  - [ ] `summarize_trend(topic, last_n_days)` — narrative evolution over time
- [ ] **Export** (deferred — depends on P21)
  - [ ] `export_to_vault(episode_id, target, template?)` — Obsidian / Notion / Logseq (depends on P21)

### Tasks

- [x] Implement `sift-mcp` server:
  - [ ] HTTP transport (remote agents, Cursor) — `run_streamable_http_async` exists in the SDK; stdio-only for now
  - [ ] Streaming for long-running tools (`ingest_url`, `ask_episode`) — deferred
- [ ] Reference agent skills (shipped in repo):
  - [ ] **Episode → Obsidian note** (claims + highlights + clickable timestamps)
  - [ ] **Weekly recap** (cross-source synthesis from subscriptions)
  - [ ] **Topic research** (search → claims → contradictions → brief)
  - [ ] **Language learning** (transcript + translation + key vocabulary)
- [ ] Distribution:

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis) — 16 open

**Goal:** Turn Sift from on-demand tool into always-on knowledge pipeline. Nightly ingest of subscribed feeds → structured extraction (P18) → cross-episode synthesis → multi-channel digest output. The differentiator vs. single-episode summarizers is *cross-source synthesis*: what 5 podcasts said about the same topic this week, who's repeating which narrative, what's new framing.

> Single-episode summary is a feature; continuous knowledge monitoring is the product.

> **Phase 1 status (✅ SHIPPED):** the cross-episode synthesis core is live — digest configs, the scheduled runner, synchronous run-now, and on-demand topic synthesis. Email/Notion/Obsidian channels, inbox UI, source ranking, and semantic cross-feed dedup are deferred. See "P20 Phase 1 — what shipped" below.

### Phase 1 — Subscription-driven brief

- [ ] Per-subscription pipeline profile (Quick / Deep / Full — reuses P12) — deferred
- [ ] Daily digest **email** per subscription set — deferred (no SMTP infra); webhook channel shipped instead
- [~] Failure handling: empty-window / no-provider / malformed-output all degrade to a recorded run; caption/transcript-quality fallbacks deferred

### Phase 2 — Topic synthesis

- [~] Daily topic answers — the synthesis covers which episodes touched it, cross-source agreement/disagreement, predictions, and narratives; *scheduled* per-topic digests + new-since-yesterday diffing deferred
- [ ] Topic-scoped *scheduled* digest (per topic, not per feed) — deferred (on-demand only for now)

### Phase 3 — Reusable intelligence layer

- [ ] All extracted knowledge written to KB (queryable via P19 MCP tools)
- [ ] Output channels:
  - [ ] Email digest (HTML)
  - [ ] Telegram digest (rich format with episode links)
  - [ ] Webhook JSON (consumes P16 intelligent webhooks)
  - [ ] Notion database row (one row per claim or per episode)
  - [ ] Markdown export → Obsidian vault folder (consumes P21)
- [ ] Inbox UI: pin / mute / follow topics, mark-read, archive

### Cross-cutting

- [~] Dedup across feeds — claims deduped by stable `claim_id` (collapses the same claim re-found across overlapping feeds); *semantic* same-news dedup deferred
- [ ] Source ranking (per-user trust weights) — deferred
- [x] API endpoints:
  - [~] `POST /api/topics` - Track a topic — topics are auto-created by P18 extraction; explicit user-tracked topics deferred

## P21: Vault & Note-App Export Channels — 10 open

**Goal:** First-class output channels for Obsidian / Notion / Logseq — served both directly (write-to-vault) and through MCP (`export_to_vault` tool from P19). Templated markdown with frontmatter, clickable timestamps, claim cards, embedded highlights.

> The "very convenient YouTube → note" UX, but built on primitives instead of a one-off plugin.

> **Phase 1 status (✅ SHIPPED):** the markdown templater, Obsidian + Logseq + plain-markdown targets, the episode + highlights templates, the export API, and the MCP `export_to_vault` tool. Notion (external SDK + token), topic/digest note templates, per-subscription auto-export, and chapter ToC are deferred. See "P21 Phase 1 — what shipped" below.

### Tasks

- [x] Markdown templater (`app/delivery/note_exporter.py`):
  - [ ] Embedded chapter ToC — renderer supports it; the route doesn't fetch chapters yet (would add a summarize LLM call)
- [~] Built-in templates:
  - [~] **Topic note** (renderer `render_synthesis_note` exists; no endpoint yet — feed it P20 `/topics/{id}/synthesis`)
  - [~] **Daily digest** (renderer exists; no endpoint yet — feed it a P20 digest run)
- [~] Output targets:
  - [ ] **Notion**: create page in configured database — deferred (needs `notion-client` + integration token)
- [ ] Per-subscription auto-export setting — deferred
- [~] Vault config:
  - [ ] Database ID + integration token (Notion) — deferred
  - [ ] Graph path (Logseq) — uses the same vault-path mechanism

## P22: Ingestion API Migration (Asset/Artifact Resource Model) — 1 open

Goal: durable asset identity + versioned transcript artifacts behind a
unified async `/v1/ingestions` API, keeping all legacy endpoints working.
(Detailed migration plan is kept as a local working document, not committed.)

### Slice 4 — commercial reliability ✅ (shipped 2026-08-05)

- Tests: `tests/test_principals.py` — **17 new tests** (mint/hash/dedup,
  resolve + deactivate, ledger increment + day isolation, auth flows incl.
  quota 429 + master-key compatibility, management guard, usage scoping,
  signature verification), 833/833 suite green (1 skipped).
- Note (2026-07-12, still open): YouTube bot-blocks unauthenticated requests
  from this network — cookies-from-browser support added
  (`YOUTUBE_COOKIES_FROM_BROWSER`); hosted acquisition will need proxy /
  session infrastructure, as anticipated in the product plan.

### Deferred (Slice 5)
- [~] Evidence retrieval: segment embeddings + semantic search + MCP
      `search_segments` shipped with P10 Phase 1; *hybrid* (keyword+vector)
      search still open

## P23: Subtitle-Grade Line Breaking (SRT/VTT Reflow) ✅ (shipped 2026-08-19) — 5 open

_Shipped — see [shipped.md](shipped.md). Remaining:_

### Phase 2 (not in this pass)
- [ ] Word-level timing: add `words` to `TranscriptionSegment`, plumb `word_timestamps=True` (local faster-whisper + `timestamp_granularities` on the API models), swap `allocate_times` to snap to real word boundaries — segmentation untouched
- [ ] Raise `max_lead_out` above 0 once strict mode is trusted; measure how many `min_duration` violations it clears
- [ ] Burned-in caption output for Social Media Clips (`single_line` + ASS/SSA)
- [ ] Scene-cut alignment — snap cue boundaries to camera cuts (needs the ffmpeg scene-detection work)
- [ ] Surface `SubtitleViolation` counts in the job artifact so an editor UI can highlight unfixable cues

## P24: In-Page Audio Capture (Extension Ingest) — 16 open

**Goal:** let the extension ingest what the server cannot reach. Today it is a URL
forwarder — it detects a supported page and hands the URL to `GET /api/add`, and
the server fetches it with yt-dlp. That fails for exactly the content the user
most wants: auth-walled, private, region-locked, or session-gated media. The
browser is already logged in; the extension should extract the audio there and
upload only that.

> **Why this is the moat and not a feature.** Ingest coverage is the part of Sift
> nobody else wants to maintain, and it is the layer everything else is built on
> (see `app/ingest/`). Every knowledge feature is worth nothing on an episode we
> could not fetch. This closes the one gap a server-side downloader structurally
> cannot.

### The obvious approach is disqualified — say so before anyone tries it

`<video>.captureStream()` + `MediaRecorder` is the first design everyone reaches
for, and it is **wrong for this product**: it records in **real time**. A
60-minute podcast takes 60 minutes, with the tab open and playing. Sift's domain
is long-form audio. Any design whose capture time scales with content duration
is out, which rules out `MediaRecorder`, and rules out intercepting
`SourceBuffer.appendBuffer` as a primary path (it only sees bytes as fast as the
player asks for them).

Capture must run at **network speed, not playback speed**.

### The insight that shrinks the problem

Most adaptive streams **already ship audio as a separate rendition**. An HLS
master playlist or a DASH manifest typically lists an audio-only track, because
players need to switch video quality without re-downloading audio.

So the common path needs **no demuxing at all** — find the manifest, pick the
audio rendition, fetch its segments, concatenate, upload. The hand-written MP4
parser is only needed for the *progressive* case, and even there the trick is
HTTP Range: fetch the `moov` box, read the sample table, then range-fetch only
the byte ranges belonging to the audio track. Never download the video.

Two paths, in priority order:

| Source | Method | Demux needed? |
|---|---|---|
| HLS / DASH with an audio rendition | fetch that rendition's segments | **no** |
| Progressive MP4 | range-fetch `moov`, parse sample table, range-fetch audio samples | yes |
| Anything else | out of scope for v1 — fall back to the existing URL hand-off | — |

### Spike first — one unknown decides the whole design

**Before any of this is built**, settle a single question empirically:

> Can the extension fetch media segment URLs *with the user's session* and get
> the bytes back?

MV3 removed the CORS exemption from content scripts, so cross-origin fetches
have to go through the background service worker under `host_permissions`. What
is **not** established here is whether those requests carry the page's cookies
in a way the origin accepts, across the platforms that matter. If they do not,
the entire premise collapses and the fallback is a different design (asking the
page to fetch on our behalf via a `MAIN`-world script).

Spike deliverable: a throwaway build that, on one auth-walled page, logs the
media URLs seen and reports whether a background-worker `fetch` of one segment
returns 2xx with plausible bytes. Nothing else gets written until that answers
yes or no, and the answer goes in this section.

#### Phase 0 findings (2026-08-27)

**Documented behaviour — resolved.** Chrome's docs state plainly: *"Requests
from an extension to a third-party are treated as same-site if the extension
has host permissions for the third-party. This means `SameSite=Strict` cookies
can be sent."* Two caveats carried forward as risks rather than blockers:

- It *"does not apply if third-party cookies are blocked"* — which is an
  increasingly common browser default, so capture must detect and report that
  case rather than silently returning a login page.
- Content scripts get no such exemption (*"Cross-origin requests are always
  treated as such in content scripts, even if the extension has host
  permissions"*), which settles where the fetching lives: the **service
  worker**, not the content script.

**Audio-rendition assumption — confirmed, and stronger than assumed.** Probing
the real format lists for the platforms Sift supports:

| Platform | Audio source | Demux? |
|---|---|---|
| X / Twitter | `hls-audio-128000` HLS rendition (1.14 MiB) | no |
| YouTube | `139` m4a / `233` HLS, audio only | no |
| Instagram | `dash-…` m4a, audio only | no |
| 喜马拉雅 | m4a audio only, 24k / 64k | no |
| 小宇宙 | a single m4a — already audio | no |

**Not one of them required demuxing.** The muxed-progressive-MP4 case that
Phase 2 exists for did not appear on any supported platform. Phase 2 is
therefore demoted: build it only if a real source turns up that needs it,
rather than on the assumption that one will.

**Still open — needs a browser.** Whether a real origin *accepts* the
worker's credentialed request is not answerable from docs, because it depends
on per-platform Referer/Origin checks and the user's third-party-cookie
setting. The spike extension for this lives at `output/phase0-spike/`
(gitignored); load it unpacked, play media on an auth-walled page, and probe.

### Locked design decisions (pending the spike)

- **Discovery via `chrome.webRequest` observation**, not DOM scraping. Media URLs
  are requested by the player regardless of how the page is built, and observing
  requests survives markup changes that break selectors. Non-blocking
  observation is still available in MV3.
- **The extension never uploads video.** Audio-only is the entire point: ~20x
  less bandwidth, and it keeps video off the server, which is the better privacy
  story for a paid backend.
- **Upload lands on the existing `POST /api/transcribe/upload`.** It already
  accepts m4a/mp4/webm/aac up to 500 MB. It needs provenance fields added
  (source URL, title, platform) — without them the knowledge layer cannot cite
  the episode, and a captured job would be a second-class citizen.
- **Capture is opt-in per page, never automatic.** Silently uploading media from
  whatever the user is viewing is not acceptable behaviour, whatever the
  manifest permits.
- **Existing URL hand-off stays the default.** In-page capture is the fallback
  for what the server cannot fetch, not a replacement — server-side yt-dlp is
  better maintained and handles far more sites. The extension should try the
  server first and offer capture when the server reports it cannot reach the
  content.

### Phasing

- [ ] **Phase 0 — spike.** Answer the fetch-with-session question. Record the
      answer here. Stop if it is no.
- [ ] **Phase 1 — HLS/DASH audio rendition.** Discovery, manifest parse, segment
      fetch, concatenate, upload. No demuxing. Covers the majority case.
- [ ] **Phase 2 — progressive MP4.** Range-fetch `moov`, parse the sample table,
      range-fetch audio samples, repackage to a playable container.
- [ ] **Phase 3 — provenance + UX.** Server-side upload metadata, capture
      progress in the popup, graceful "cannot capture this page" messaging.

### Tasks (Phase 0–1)

- [ ] `extension/utils/media-discovery.ts` — collect candidate media URLs per tab
      from `webRequest`, classified as `hls` / `dash` / `progressive` / `unknown`
- [ ] `extension/utils/hls.ts` — parse a master playlist, select the audio-only
      rendition, expand to a segment list (pure functions, unit-testable without
      the network)
- [ ] `extension/utils/capture.ts` — fetch segments with bounded concurrency,
      report progress, concatenate
- [ ] Background worker: own the fetching (host permissions live there), stream
      to the server, surface progress to the popup
- [ ] Popup: a capture affordance that appears only when the server reports it
      cannot fetch the page itself
- [ ] `manifest`: add `webRequest`; keep `*://*/*` optional and request it at
      capture time rather than up front
- [ ] Server: provenance fields on `POST /api/transcribe/upload`

### Test plan

- [ ] Pure-function tests for manifest parsing: master playlist with and without
      a separate audio rendition, DASH manifest, malformed manifest, a playlist
      whose audio rendition is a relative URL
- [ ] Segment-list expansion: absolute vs relative URIs, `EXT-X-BYTERANGE`,
      encrypted playlists rejected with a clear message rather than garbage
- [ ] Capture orchestration against a stub fetcher: concurrency cap respected,
      one failed segment aborts rather than uploading a corrupt file, progress
      is monotonic
- [ ] Upload: provenance round-trips onto the job so the knowledge layer can
      cite it
- [ ] **A real end-to-end capture on one live auth-walled page**, verified by
      transcribing the result — this is the only test that proves the premise

### Explicitly out of scope

- DRM-protected media. Widevine/FairPlay content is not capturable and must fail
  with a clear message rather than a corrupt file.
- Real-time capture of anything. See above.
- Replacing server-side ingestion for sites yt-dlp already handles well.

## P25: Extractable Ingest Core (library / standalone CLI / local MCP) — 5 open

**Goal:** ship `app/ingest/` as something people can use without the app around
it — a Python library, a standalone CLI, and an MCP server that calls the core
in-process (no REST server, no database). The layer fence already existed; the
remaining coupling was configuration.

- [x] **Phase 1: settings seam** — `app/ingest/settings.py` owns `IngestSettings`
  (download dir, platform cookies, transcription). `app.config.Settings`
  subclasses it and registers itself; library callers pass
  `download_audio(url, settings=IngestSettings(...))` or rely on env.
  - [x] Every platform downloader, `DownloaderFactory`, `download_audio`,
    `get_metadata` and `twitter_ytdlp_cookies` accept `settings`
  - [x] Cloud transcription reads credentials through a registered provider
    (`set_cloud_credentials_provider`, registered by `app.store`) instead of
    opening `JobStore` itself
  - [x] Fixed: cloud transcription never found its key — the old lookup built
    `JobStore(settings.download_dir)` with a `str` and swallowed the error
  - [x] Cloud engine only uses a stored key when the provider is `openai` (the
    only endpoint it calls), so an Anthropic/Groq key is never sent to OpenAI
  - [x] `tests/test_layering.py`: ingest may import nothing from `app.*` outside
    `app.ingest` (closes the `app.store` / `app.config` gap)
- [x] **Phase 2: single platform registry** — `app.ingest.platforms.DOWNLOADERS`
  is the one list, in URL-detection order; `detect_platform`,
  `get_downloader_for_platform` and `get_available_platforms` all read it
  (it used to be hardcoded twice in `fetch/downloader.py`). `PLATFORM` is the
  declared class attribute; the 11 duplicated `platform` properties are gone.
  `tests/test_platform_registry.py` fails if an adapter is written but not listed.
  - Entry-point plugin discovery: **dropped for now.** `Platform` is a closed
    enum persisted in the DB and API schemas, so a plugin could only replace a
    built-in adapter, not add a platform. Revisit only if `Platform` opens up.
- [ ] CLI: `-o episode.m4a` on an Apple Podcasts MP3 saves MP3 data under the
  `.m4a` name instead of converting (seen during the Phase 2 live run)
- [x] README "CLI Usage" examples omit the required `download` subcommand
- [x] **Phase 3: package split** — `packages/sift-core` (import name
  `sift_core`) is a uv workspace member the app depends on. Its base deps are
  only what downloading needs (`httpx`, `pydantic-settings`, `structlog`,
  `tenacity`, `cachetools`, `feedparser`, `mutagen`, `youtube-transcript-api`,
  `yt-dlp`); `[transcribe]` and `[diarize]` extras for the heavy parts.
  `app/ingest/` is now only a deprecation shim re-exporting the top-level names.
  - [x] The CLI moved into the core (`sift_core/cli.py`); `sift` / `xdownloader`
    console scripts come from `sift-core`
  - [x] Dockerfile, Nuitka build (`--include-package=sift_core`), CI ruff path
  - [ ] Delete the `app/ingest` shim after one release
  - [ ] Publish `sift-core` to PyPI (name check, version policy, CI release job)
- [ ] **Phase 4: local MCP server** — in-process tools (`download`, `metadata`,
  `fetch_transcript`, `transcribe`) over the core; keep the HTTP `sift-mcp` for
  the hosted backend (jobs, knowledge, evidence)
- [ ] Rename the `AudioMetadata` / `DownloadResult` public types before the
  package is published, if at all — after that they are an API

## Transcription Engine Ideas — 1 open

- [ ] **Breeze-ASR-25 engine** (MediaTek, Whisper-large-v2 fine-tune) for
      Taiwanese Mandarin + zh/en code-switching — slot into
      `transcription_engine.py` as a new engine; needs CTranslate2 conversion
      for the faster-whisper runtime or the HF transformers pipeline;
      pipeline_version stamping (Slice 2) already records which engine
      produced each artifact

## v2.0 Backlog (Future Ideas) — 7 open

- [ ] **Cross-Platform Social Graph**: Track speakers across downloads, build profiles of their positions over time
- [ ] **Visual Trend Extraction**: For video from 小红书/Instagram, use vision AI to extract aesthetic trends, product placements, visual themes
- [ ] **AI-Generated Podcast Feed**: Auto-create a personal podcast RSS feed from daily distillations
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts (speak a query, find the answer)
- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox)

## Fully shipped

Detail in [shipped.md](shipped.md).

- Security Hardening
- P1: Speaker Diarization (Who Spoke When) ✅ COMPLETED
- P6: AI Provider Manager (LiteLLM Integration) ✅ COMPLETED
- Platform Adapter Ideas
