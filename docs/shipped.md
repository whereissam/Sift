# Shipped

The engineering log: every completed phase with the notes written when it
landed — locked decisions, what the implementation changed about the plan,
and which files carry it. Kept out of [todo.md](todo.md) so that file stays
a list of work rather than a changelog.

Open work lives in [todo.md](todo.md).

## Security Hardening

Full-codebase security review completed 2026-06-22. Fixed:

- [x] SSRF: route all user/feed-supplied URL fetches through an allowlist
      validator that re-checks every redirect hop (artwork, RSS enclosures,
      Xiaoyuzhou, Apple Podcasts, Discord); closed blocklist gaps (CGNAT,
      Alibaba metadata, IPv4-mapped IPv6, unspecified/multicast)
- [x] API auth on the realtime WebSocket + extract-presets routers; SSRF check
      on AI `base_url`; scope restriction on Obsidian `vault_path`
- [x] Tauri Rust backend: parameterized `get_jobs` SQL, restricted CORS off the
      wildcard, removed the `/bin/sh -c` yt-dlp invocation, RFC 5987
      Content-Disposition, streamed file responses, dropped unused shell caps
- [x] Secrets: warn when the fallback encryption key is used; require `API_KEY`
      in Docker Compose; HSTS + CSP headers; deduped the Twitter bearer token;
      YAML-safe Obsidian frontmatter
- [x] Frontend: nginx CSP/HSTS, removed `TAURI_` from Vite `envPrefix`, added
      `.dockerignore`, gitignore `output/`

Follow-up (completed 2026-06-22):

- [x] Socket-level DNS pinning to close the SSRF DNS-rebinding TOCTOU window —
      a pinning httpx transport connects to the validated IP while keeping the
      hostname for TLS SNI/cert verification
- [x] Allow updating a valid `output_dir` on existing subscriptions (added to
      the column allowlist with path-containment validation)
- [x] Persist + encrypt cloud-provider credentials (stored in the
      `cloud_providers` table, Fernet-encrypted, reloaded on startup)
- [x] Per-endpoint rate limits on expensive download/transcribe/upload routes
      (10/min each)

Second audit (security-audit skill, run 2026-10-12 on 406ba52). Fixed 2026-10-13:

- [x] yt-dlp option injection + SSRF: platform detection checks the parsed
      http(s) host (`url_host_matches`, Rust `url_matches_platform`); `--`
      before the URL in every yt-dlp argv (Python and Tauri)
- [x] RSS enclosures: http(s) only, always fetched through the SSRF-checked
      direct path, never a platform downloader
- [x] Origin guard (independent of `API_KEY`): cross-site writes and WebSocket
      upgrades refused; loopback-only Host when bound to loopback
      (`ALLOWED_HOSTS`); cross-site `GET /api/add` gets a confirmation page;
      same in the Tauri backend
- [x] `/api/cleanup` rejects `max_age_hours < 1`
- [x] Telegram bot limited to `TELEGRAM_ALLOWED_USER_IDS` (fail-closed)
- [x] MCP client percent-encodes ids as one path segment
- [x] Webhooks sent through a DNS-pinned client; `/webhooks/test` no longer
      echoes response bodies
- [x] S3 `endpoint_url` SSRF-validated (`S3_ALLOWED_ENDPOINTS` for private)
- [x] Decoded-byte cap in `safe_get` (64 MiB) and Discord streaming (512 MiB)
- [x] Live transcription: session/message byte caps, attempt-based decode
      throttle, ffmpeg timeout, session limit; batch capped at 500 URLs with
      off-loop inserts and O(1) enqueue dedupe
- [x] Random secrets-at-rest key in `ENCRYPTION_KEY_FILE` instead of
      sha256(DOWNLOAD_DIR); legacy values re-encrypted on startup; DB/backups/
      checkpoints not exportable
- [x] No env LLM key sent to a caller-chosen `base_url`; Whisper/Ollama
      published on loopback only in Compose
- [x] Jobs for the same video share one file name; cleanup, job delete and
      the `output_dir` move no longer remove a file another job still uses
      (`JobStore.file_used_by_other_job`)

Audit follow-ups (2026-10-13):

- [x] Queued jobs ran nowhere: the queue had no processor, so batch and
      scheduled downloads were dropped. Now run via `WorkflowProcessor`;
      startup recovery skips future-scheduled jobs; `scheduled_at` offsets
      are converted to UTC; retry only for failed jobs
- [x] Blank `API_KEY=` is unset; non-ASCII keys are a 401; docs off while
      `API_KEY` is set (`API_DOCS` to override)
- [x] `validate_url_ssrf`: NAT64/6to4/Teredo/`::a.b.c.d` judged by their IPv4
      host; all non-global addresses refused
- [x] `/translate` capped at 100k chars, 5/minute; idempotency keys per
      principal; server-issued single-use OAuth `state`

## P1: Speaker Diarization (Who Spoke When) ✅ COMPLETED

**Goal:** Identify different speakers in transcriptions, especially for X Spaces and Podcasts.

See [diarization-setup.md](./diarization-setup.md) for setup instructions.

### Tasks

- [x] Research and select diarization library:
  - [x] Selected: `pyannote-audio` (most accurate, requires HuggingFace token)
- [x] Add optional dependency group `[diarize]`
- [x] Create diarization service (`app/ingest/transcribe/diarizer.py`)
- [x] Integrate with existing transcription pipeline:
  - [x] Run diarization after transcription
  - [x] Merge speaker labels with transcript segments
- [x] Update output formats:
  - [x] Plain text with speaker labels (`dialogue` format)
  - [x] SRT with speaker prefixes
  - [x] JSON with speaker IDs per segment
- [x] Add Web UI toggle for diarization
- [x] Handle speaker renaming (Speaker 0 → "Host", etc.)
- [x] Add speaker count option (`num_speakers` parameter)

---

## P6: AI Provider Manager (LiteLLM Integration) ✅ COMPLETED

**Goal:** Create an AI-agnostic gateway supporting multiple LLM providers through a unified interface.

### Tasks

- [x] Add `litellm` dependency for universal LLM API translation
- [x] Update `app/knowledge/summarizer.py` to use LiteLLM:
  - [x] Support OpenAI-compatible API format
  - [x] Handle provider-specific authentication
- [x] Supported AI backends:
  - [x] **Ollama** (Local Llama 3) - Privacy-first, free, runs locally
  - [x] **OpenAI** (GPT-4, GPT-4o) - High quality cloud option
  - [x] **Anthropic** (Claude 3.5 Sonnet) - Best for long-form transcript reasoning
  - [x] **Groq** (Cloud Llama 3) - Fast inference (500+ tokens/sec)
  - [x] **DeepSeek** - Budget-friendly for high-volume summarization
  - [x] **Google Gemini** (Gemini 1.5 Flash/Pro) - Google's multimodal AI
  - [x] **Custom OpenAI-compatible endpoints** (LM Studio, etc.)
- [x] Create AI Settings management:
  - [x] `POST /api/ai/settings` - Save AI provider configuration
  - [x] `GET /api/ai/settings` - Get current AI settings
  - [x] `GET /api/ai/providers` - List available providers
  - [x] `POST /api/ai/test` - Test connection to provider
  - [x] Store API keys securely in SQLite `ai_settings` table
- [x] Web UI Settings tab:
  - [x] Provider dropdown (OpenAI, Ollama, Anthropic, Groq, DeepSeek, Gemini, Custom)
  - [x] API key input field (with show/hide toggle)
  - [x] Base URL field (for custom/local endpoints)
  - [x] Model selection per provider
  - [x] Test connection button
- [x] Docker Compose setup for Sift + Ollama together

---

## P10: Semantic Indexing & Vector Search 🚧 (Phase 1 shipped)

**Goal:** Replace keyword search with concept-level retrieval. Turn every transcript into a searchable vector embedding so users can query their entire library by *meaning*.

> **Phase 1 status (✅ SHIPPED):** segment indexing on the P18 embedding
> substrate, auto-index on transcription completion, the filtered search API
> (POST + GET), reindex/status endpoints, and the MCP `search_library` /
> `search_segments` tools. Web UI, extra embedding models, and hybrid
> (keyword+vector) search are deferred. See "P10 Phase 1 — what shipped".

### Tasks

- [x] Research and select vector database — resolved by the P18 locked
      decision: SQLite blobs + Python cosine behind the `EmbeddingStore`
      interface; Chroma/Qdrant/pgvector stays a one-file swap when ANN scale
      demands it (no new dependency for Phase 1)
- [x] Create vector indexing service (`app/knowledge/segment_indexer.py` — reuses
      the P18 embedding infra rather than the roadmap's aspirational
      `vector_indexer.py`):
  - [x] Generate embeddings for transcript chunks (windows of consecutive
        segments, ~700 chars, 1-segment overlap — paragraph-level)
  - [~] Support multiple embedding models:
    - [x] `all-MiniLM-L6-v2` (fast, local, via sentence-transformers)
    - [ ] OpenAI `text-embedding-3-small` (high quality, API) — deferred
    - [ ] Ollama embedding models (local, privacy-first) — deferred
  - [x] Store embeddings alongside job metadata (job_id, timestamps, speaker
        in `search_chunks`; vectors in the generic `embeddings` table)
  - [x] Auto-index on transcription completion (workflow hook, best-effort,
        gated on `search_auto_index`)
- [x] Migrate from plain SQLite to SQLite + vector store — N/A as designed:
      the P18 generic `embeddings` table already is the vector store;
      `search_chunks` keeps the referential link to jobs
- [x] Concept search API:
  - [x] `POST /api/search` - Semantic search across all transcripts
  - [x] `GET /api/search?q=...&job_id=...` - Search within a specific job
  - [x] Return results with timestamps, speaker labels, relevance scores
  - [x] Support filters: date range, platform, speaker, job
- [ ] Web UI search interface — deferred:
  - [ ] Global search bar in top nav
  - [ ] Results show matching segments with context, clickable timestamps
  - [ ] "Search within this transcript" option on job detail page
- [~] Incremental re-indexing — manual per-job re-index
      (`POST /api/jobs/{id}/search-index`, idempotent replace) + bounded bulk
      backfill (`POST /api/search/reindex`); auto re-index on transcript
      edits/annotations deferred

### P10 Phase 1 — what shipped

Built directly on the P18 substrate — the generic `embeddings` table and the
lazy-loaded local MiniLM model were designed for exactly this, so Phase 1 adds
no new dependencies and no LLM cost (embedding is local CPU).

- `app/store/_search.py` (new `_SearchMixin`) + `search_chunks` table
  in `_schema.py` — chunk metadata rows (job_id, ordinal, start_s/end_s,
  speaker, text, embedding_model; UNIQUE job+ordinal).
  `replace_search_chunks_for_job` deletes prior chunk rows *and* their
  orphaned embedding rows in one tx; `list_search_chunk_ids` resolves
  job/speaker filters chunk-side and platform/date filters via a jobs join;
  `get_search_index_stats` / `list_unindexed_search_jobs` power status +
  backfill.
- `app/knowledge/segment_indexer.py` (new) — `build_chunks` windows whole segments
  up to ~700 chars (MiniLM's effective context) with a 1-segment overlap so
  boundary-straddling sentences are findable from either side; dominant-
  speaker attribution by character count. `SegmentIndexer.index_job` resolves
  segments warm/cold via the shared `resolve_segments_for_job`, embeds
  batched off the event loop, and persists chunks + vectors idempotently.
  Stores resolve lazily so the singleton never pins a stale JobStore.
- `app/knowledge/semantic_search.py` (new) — embeds the query with the same model,
  scopes the cosine scan to SQL-resolved candidate IDs when filters are
  present (batched under SQLite's bound-variable ceiling), joins chunk + job
  context (title/source_url/platform), applies `min_score` (default 0.3).
- `app/pipeline/workflow.py` — `_index_search_segments(job_id)` after the P18
  knowledge enqueue: inline (local model, job already COMPLETED), gated on
  `search_auto_index`, best-effort so an embedding hiccup never fails the
  transcription.
- `app/api/search_routes.py` (new) — `POST /api/search` + `GET /api/search`
  (same search, body vs query params), `GET /api/search/status`,
  `POST /api/search/reindex` (bounded cold-inventory sweep, 2/min),
  `POST /api/jobs/{id}/search-index` (per-job re-index, 404 on unknown job);
  503 when sentence-transformers isn't installed. Wired in `app/api/__init__.py`.
- `app/config.py` — `search_auto_index: bool = True`.
- `app/mcp_server/` — `SiftClient.search` + `search_library(query, limit?,
  min_score?, platform?, speaker?)` and `search_segments(episode_id, query,
  limit?)` tools; server instructions updated. The P19 server is now 14 tools.
- `README.md` — Semantic Search section with curl examples; MCP tool list +
  feature bullet updated.
- `tests/` — `test_segment_indexer.py` (14: chunk windowing, overlap,
  speaker attribution, index/reindex idempotency, no-segments),
  `test_search_store.py` (12: chunk CRUD, orphan-embedding cleanup, filter
  queries, stats/backfill listing), `test_search_api.py` (12: index/status/
  reindex endpoints, ranked search, min_score, GET variant, job/platform
  scoping, empty index, validation), +3 MCP search-tool tests (+2 updated) —
  **41 new tests**, 696/696 suite green (1 skipped).

Deferred: Web UI search surface, OpenAI/Ollama embedding model options,
hybrid keyword+vector search (the P22 Slice 5 "evidence retrieval" remainder),
and auto re-index on transcript edits/annotations.

**Example query:** *"Find the part where someone explains the difference between L2s and sidechains"* → Returns the exact 30-second clip from a 3-hour podcast downloaded two months ago.

---

## P11: Ask Audio (RAG Chat Interface) 🚧 (Phase 1 shipped)

**Goal:** Let users chat with their downloads. Ask questions, get answers grounded in transcript content with source timestamps.

> **Phase 1 status (✅ SHIPPED):** the RAG engine over the P10 index, single-
> episode + library-wide ask endpoints with persisted Q&A history, and the MCP
> `ask_episode` / `ask_at_timestamp` tools. Web UI chat, multi-job mode,
> Telegram integration, and conversation memory are deferred. See "P11 Phase 1
> — what shipped".

### Tasks

- [x] Create RAG service (`app/knowledge/rag_engine.py`):
  - [x] Query vector store for relevant transcript segments (P10 search layer)
  - [x] Construct context window from top-K results (numbered sources with
        timestamps, speaker, episode title)
  - [x] Send to LLM with grounding prompt (cite `[n]` sources, refuse to
        answer beyond them) — uses the P18 `chat` task preset
  - [x] Return answer with source references (job, timestamp, speaker) and
        per-source `cited` flags parsed from the answer's citations
- [~] Chat modes:
  - [x] **Single Job**: Chat with one specific transcript (plus
        `start_s`/`end_s` time-range scoping)
  - [x] **Library-wide**: Ask questions across all indexed content
        (platform/speaker filters supported)
  - [ ] **Multi-Job**: Select 2+ jobs and chat across them — deferred
- [ ] Web UI chat interface — deferred:
  - [ ] Chat panel on job detail page (slide-out or tab)
  - [ ] Global "Ask Audio" page for library-wide queries
  - [ ] Message history with source citations (clickable timestamps)
  - [ ] Suggested questions based on transcript content
- [x] API endpoints:
  - [x] `POST /api/ask` - Ask a question (library-wide)
  - [x] `POST /jobs/{id}/ask` - Ask about a specific job
  - [x] `GET /jobs/{id}/chat-history` - Retrieve past Q&A for a job
        (+ `GET /api/ask/history` for the library-wide scope)
- [ ] Telegram bot integration — deferred:
  - [ ] Send a link → bot downloads & indexes → user asks questions → bot answers with timestamps
  - [ ] `/ask <question>` - Query the most recent download
- [ ] Conversation memory: follow-up questions understand prior context — deferred

### P11 Phase 1 — what shipped

Grounded Q&A end to end on the P10 retrieval substrate. No new dependencies:
retrieval is the local embedding model, answering goes through the existing
LiteLLM provider layer via the P18 `chat` task preset (user-mappable in AI
Settings), and spend lands in the same per-UTC-day budget ledger as knowledge
extraction and digests.

- `app/knowledge/rag_engine.py` (new) — `RAGEngine.from_settings()` resolves the
  `chat` preset; `ask(question, job_id?, start_s?/end_s?, platform?,
  speaker?, k, min_score)` retrieves via `semantic_search.search_segments`
  (looser default `min_score=0.2` — weak context the model can ignore beats
  missing context), post-filters to the time range for `ask_at_timestamp`,
  builds a numbered-source prompt (`[n] (start–end, speaker — title, episode
  id): text`), and calls the LLM with a strict grounding system prompt.
  Citations `[n]` are parsed back onto `RAGSource.cited`. Graceful-degradation
  parity with `digest_synthesizer`: no provider / nothing retrieved / LLM
  failure all return a non-success `RAGAnswer` (the empty-retrieval error
  points at the search-index endpoint), never raise.
- `app/store/_chat.py` (new `_ChatMixin`) + `chat_history` table —
  one row per answered question; `job_id NULL` = library-wide, so the two
  scopes share a table but history reads are scope-exact. Malformed persisted
  `sources` JSON degrades to `[]` instead of crashing a read.
- `app/api/ask_routes.py` (new) — `POST /api/ask`, `POST /api/jobs/{id}/ask`
  (404 on unknown job; forwards time-range scoping, which the library route
  deliberately ignores), `GET /api/jobs/{id}/chat-history`,
  `GET /api/ask/history`. 10/min rate limit on the ask routes; 503 when the
  embedding backend is missing. Successful answers record LLM spend via
  `knowledge_budget` and persist history best-effort (a history write failure
  never fails the answer); failed asks are not persisted.
- `app/mcp_server/` — `SiftClient.ask_job` + `ask_episode(episode_id,
  question, limit?)` and `ask_at_timestamp(episode_id, start, end, question,
  limit?)` tools; server instructions updated. The P19 server is now 16 tools.
- `README.md` — Ask Audio section with curl examples; MCP tool list updated.
- `tests/` — `test_rag_engine.py` (10: degradation branches, citation
  parsing, prompt shape, job scoping, time-range filter/empty),
  `test_chat_store.py` (5: CRUD, scope isolation, ordering/limit, malformed
  sources, delete), `test_ask_api.py` (8: answer + history persistence,
  failed-ask not persisted, job scoping + 404s, time-range forwarding, budget
  recording, validation, end-to-end over a real index with a fake LLM), +2
  MCP ask-tool tests — **25 new tests**, 721/721 suite green (1 skipped).

Deferred: Web UI chat surfaces, multi-job mode, Telegram `/ask`, and
conversation memory (each ask is currently single-turn).

**Example:** User sends a YouTube link, then asks *"What did they say about the Fed rate hike?"* → Bot answers with the exact quote and timestamp.

---

## P12: Agentic Ingest Pipeline 🚧 (Phase 1 shipped)

**Goal:** When a user pastes a URL, Sift doesn't just download — it triggers an autonomous multi-agent research loop that extracts maximum value.

> **Phase 1 status (✅ SHIPPED):** the pipeline orchestrator with three
> built-in profiles (quick / deep / full) composing the existing services,
> per-stage status persisted on the job, and the ingest/status/profiles API.
> Custom user-defined profiles, per-subscription defaults, parallel stage
> execution, and the Knowledge Canvas UI are deferred. See "P12 Phase 1 —
> what shipped".

### Tasks

- [~] Create pipeline orchestrator (`app/pipeline/agentic_pipeline.py`):
  - [x] Define pipeline stages as composable agents (stage registry over
        existing services; transcribe is load-bearing, enrichment stages are
        additive and never abort the run)
  - [x] Support configurable pipeline profiles (`quick` / `deep` / `full`)
  - [ ] Parallel execution where possible — deferred (stages run sequentially)
- [x] Pipeline agents (all composed from services that already shipped):
  - [x] **Transcription Agent**: Download → Transcribe (enhance/diarize
        options deferred to keep Phase 1 parameter surface small)
  - [x] **Summarization Agent**: bullet-point summary via the summarizer
        (chapter markers/key topics available through the existing
        `/api/summarize` modes)
  - [x] **Entity Agent**: rides the P18 knowledge extraction stage (claims +
        entities + topics + predictions via the backfill worker)
  - [x] **Indexing Agent**: P10 segment indexer (embeddings → searchable)
  - [x] **Notification Agent**: webhook on completion (Telegram deferred)
- [~] Pipeline configuration:
  - [x] Per-job pipeline override (API parameter `profile`)
  - [ ] Per-subscription default pipeline — deferred
  - [ ] Global default pipeline in settings — deferred (code default: `deep`)
- [ ] Web UI pipeline status — deferred:
  - [ ] Multi-stage progress indicator (not just a download bar)
  - [ ] "Knowledge Canvas" view: shows extracted entities, summary, topics as the pipeline runs
  - [ ] Pipeline complete notification with quick-access to all outputs
- [~] API endpoints:
  - [x] `POST /api/ingest` - Submit URL with pipeline profile
  - [x] `GET /jobs/{id}/pipeline` - Get pipeline status and partial results
  - [x] `GET /api/pipelines` - List available pipeline profiles
  - [ ] `POST /api/pipelines` - Create custom pipeline profile — deferred

### P12 Phase 1 — what shipped

Composition, not construction: every stage delegates to a service that
already has its own suite (WorkflowProcessor, SegmentIndexer, knowledge
backfill, summarizer, sentiment analyzer, clip generator, webhook notifier),
so the orchestrator's own surface is profiles, ordering, state bookkeeping,
and failure policy.

- `app/pipeline/agentic_pipeline.py` (new) — `PIPELINE_PROFILES` (`quick` =
  transcribe + index; `deep` adds knowledge + summarize; `full` adds
  sentiment + clips; every profile ends with `notify`), `PipelineRunner.run`
  (sequential; reads everything from the job row so a crashed run's state is
  inspectable). Failure policy: `transcribe` failure aborts and marks the
  rest `skipped`; enrichment failures are recorded on their stage and the
  run continues (same additive-signal stance as the P18 topic/prediction
  passes). Stages that lack their prerequisite (no LLM provider, no
  webhook_url) end `skipped` with a reason, not `failed`. LLM stages record
  spend in the shared daily budget ledger. The knowledge stage *enqueues*
  (the C.3 backfill worker owns the run) and the status endpoint surfaces
  the live `knowledge_status` alongside; sentiment/clip results also land in
  the existing API caches so the P7/P8 GET endpoints see pipeline-produced
  results.
- `app/store/_pipeline.py` (new `_PipelineMixin`) + `pipeline_state`
  jobs column (migration) — JSON `{profile, started_at, completed_at,
  stages: [{name, status, started_at, completed_at, error, detail}]}`;
  statuses `pending | running | completed | skipped | failed`; per-stage
  `detail` carries partial results (segment counts, chunk counts, summary
  content, clip list).
- `app/api/ingest_routes.py` (new) — `POST /api/ingest` (validates profile,
  creates the job, initializes state, launches the background run; 10/min),
  `GET /api/jobs/{id}/pipeline` (404 distinguishes unknown job vs.
  non-pipeline job), `GET /api/pipelines`. Wired in `app/api/__init__.py`.
- `README.md` — Agentic Ingest section with profile table + curl examples.
- `tests/` — `test_agentic_pipeline.py` (14: state CRUD incl. malformed
  JSON, stage ordering per profile, abort-vs-continue failure policy, skip
  reasons, real index/knowledge/notify stage behavior),
  `test_ingest_api.py` (9: job + state creation, background scheduling,
  default/unknown profile, webhook persistence, status + 404 variants,
  profile listing) — **23 new tests**, 744/744 suite green (1 skipped).

Deferred: custom profiles (`POST /api/pipelines`), per-subscription default
profile, global default in settings, parallel stage execution, diarize/
enhance options on the ingest call, Telegram notification, and the Knowledge
Canvas / multi-stage progress UI.

---

## P13: Psychographic Mapping & Contradiction Detection 🚧 (Contradictions shipped)

**Goal:** Replace simple sentiment analysis with deep rhetorical intelligence. Understand not just *what* was said but the underlying reasoning, persuasion techniques, and logical consistency.

> **Phase 1 status (✅ SHIPPED):** the contradiction detection engine —
> episode-scoped and cross-episode speaker-scoped — with persisted,
> confidence-scored pairs, API + MCP surface, and the P16 webhook alert
> count. The psychographic/rhetoric layer (persuasion, deflection, tone
> reasoning), credibility scores, and the Rhetoric Map UI are deferred.
> See "P13 Phase 1 — what shipped".

### Tasks

- [ ] Extend sentiment analyzer with LLM reasoning layer — deferred:
  - [ ] For each flagged segment, generate: *why* the tone shifted, what triggered it
  - [ ] Detect persuasion techniques (appeal to authority, FOMO, etc.)
  - [ ] Identify when speakers deflect questions or change topics abruptly
- [x] Contradiction detection engine:
  - [x] Build statement graph: extract key claims with timestamps and speaker
        attribution — delivered by P18 (claims are the statement graph)
  - [x] LLM-powered cross-referencing: compare claims pairwise for logical
        consistency (candidate pairs must share an entity or topic; capped;
        batched JSON-mode judging on the `synthesize` preset)
  - [x] Confidence scoring for each detected contradiction (0.1 storage
        floor, 0.5 read default — mirrors the P18 confidence model)
  - [x] Example: *"At 10:12, the speaker claimed they didn't own any $SOL, but at 32:40, they mentioned 'checking their Phantom wallet' during the dip."*
- [~] Cross-platform social graph (for multi-source analysis):
  - [x] Same-speaker cross-episode flip-flop detection
        (`POST /api/contradictions/analyze {speaker}` over `query_claims`)
  - [ ] Track statements over time / evolving-position timeline — deferred
- [ ] Web UI — deferred:
  - [ ] "Rhetoric Map" view: visual graph of claims, connections, and contradictions
  - [ ] Contradiction cards with side-by-side quotes and timestamps
  - [ ] Credibility score per speaker (based on consistency)
- [~] API endpoints:
  - [ ] `POST /jobs/{id}/analyze-rhetoric` - Run deep rhetorical analysis — deferred with the rhetoric layer
  - [x] `POST /jobs/{id}/analyze-contradictions` + `POST /api/contradictions/analyze` (speaker-scoped)
  - [x] `GET /jobs/{id}/contradictions` + `GET /api/contradictions?speaker=&min_confidence=`
  - [x] `GET /jobs/{id}/claims` - delivered by P18 (`GET /jobs/{id}/knowledge`)

### P13 Phase 1 — what shipped

The P18 claims layer is the statement graph, so detection is a judging
problem, not an extraction one. Cost is bounded before the LLM ever runs:
candidate pairs must share ≥1 entity or topic (unrelated claims can't
meaningfully contradict), pairs are ranked by joint confidence and capped
(120/run, 40/prompt), and judging is batched JSON-mode on the `synthesize`
preset with spend recorded in the shared daily ledger.

- `app/knowledge/contradiction_detector.py` (new) — `select_candidate_pairs`
  (entity/topic-overlap filter → joint-confidence ranking → cap),
  `ContradictionDetector.detect` (batched pairwise judging, conservative
  system prompt — hedges/opinions/different-time claims are not
  contradictions), per-record validation (bad index / empty explanation /
  non-numeric or sub-floor confidence dropped), stable order-independent
  `con_<hash>` pair IDs, same-speaker attribution on the stored row.
  Graceful-degradation parity with `digest_synthesizer`; a no-shared-context
  claim set is a *successful* empty result, not an error.
- `app/store/_contradictions.py` (new `_ContradictionsMixin`) +
  `contradictions` table — pair-hash PK so re-analysis upserts (fresher
  explanation/confidence) instead of duplicating; episode filter matches
  either side of the pair; `get_claims_by_ids` hydration helper;
  `count_contradictions_for_episode` for the webhook. `replace_claims_for_job`
  now clears the episode's contradictions in the same tx (the
  claim_topics/predictions orphan-cleanup pattern).
- `app/api/contradiction_routes.py` (new) — `POST /api/jobs/{id}/analyze-contradictions`
  (400 with a pointer at extract-knowledge when the episode has no claims),
  `GET /api/jobs/{id}/contradictions`, `POST /api/contradictions/analyze`
  (speaker-scoped cross-episode), `GET /api/contradictions`. Responses
  hydrate both claims (quote + speaker + timestamps) so every hit is
  verifiable. 5/min on the analyze routes.
- `app/delivery/webhook_intelligence.py` — `contradiction_count` added to the
  full_intelligence knowledge block (stored rows only — the webhook path
  still never runs detection), closing the P16 deferred item.
- `app/mcp_server/` — `find_contradictions(episode_id?, speaker?,
  min_confidence?, analyze?)` tool + three client methods; episode scope
  judges on demand (or reads stored with `analyze=false`), speaker scope
  reads the cross-episode library. The P19 server is now 17 tools.
- `README.md` — Contradiction Detection feature bullet made real.
- `tests/` — `test_contradiction_detector.py` (14: pair selection/ranking/
  caps, stable IDs, all degradation branches, record validation, prompt
  content, cross-speaker attribution), `test_contradiction_api.py` (12:
  upsert/filter/orphan-cleanup store behavior, analyze persist+hydrate+
  budget, 404/400 guards, speaker-scoped analyze, reads), +3 MCP tool tests
  (+1 webhook count assertion) — **29 new tests**, 785/785 suite green
  (1 skipped).

Deferred: persuasion/deflection/tone-reasoning layer (`analyze-rhetoric`),
credibility scores, Rhetoric Map UI, topic/timeframe filters on
`find_contradictions`, statement-evolution timelines.

---

## P14: Content Distiller (Multi-Source Briefing) 🚧 (Phase 1 shipped)

**Goal:** Feed multiple URLs and get a single synthesized output — a "Daily Briefing" that combines insights from all sources.

> **Phase 1 status (✅ SHIPPED):** on-demand distillation over an explicit
> job set, as a thin layer on the P20 synthesis machinery (same synthesizer,
> same markdown renderer — the two paths can't drift). The scheduled/
> subscription case was already delivered by P20 digests; topic deep-dive by
> `GET /api/topics/{id}/synthesis`. Audio briefing (TTS) and the Web UI
> remain deferred. See "P14 Phase 1 — what shipped".

### Tasks

- [~] Create content distiller service (`app/knowledge/distiller.py`):
  - [x] Accept multiple job IDs as input (URLs enter via `POST /api/ingest`
        first — job ids are the stable handle)
  - [x] Cross-reference to find common themes, disagreements, unique
        insights (P18 claims → `DigestSynthesizer`, `synthesize` preset)
  - [~] Generate unified output formats:
    - [x] Written briefing (Markdown) — `GET /api/distill/{id}/markdown`
          (deterministic `render_digest_markdown`)
    - [ ] Audio briefing (TTS-generated 5-minute summary — future, depends on P9 dubbing)
    - [x] Structured JSON (themes, consensus, disagreements, predictions,
          narratives) — the stored `DigestSynthesis`
- [x] Distillation modes:
  - [x] **Daily Digest**: delivered by **P20 digests** (scheduled runner over
        subscription windows)
  - [x] **Topic Deep-Dive**: delivered by **P20's** `GET /api/topics/{id}/synthesis`
  - [x] **Debate Summary**: `mode=debate` — synthesis framing leads with
        disagreements and each side's strongest sourced position
- [~] Web UI:
  - [ ] "Distill" button to select multiple jobs — deferred
  - [ ] Briefing viewer with per-source attribution — deferred
  - [x] Schedule daily/weekly auto-distillation from subscriptions —
        delivered by **P20 digests**
- [~] API endpoints:
  - [x] `POST /api/distill` - Create a distillation from job IDs
  - [x] `GET /api/distill/{id}` - Get distillation result
        (+ `/markdown` rendering + `GET /api/distillations` history)
  - [x] `POST /api/distill/schedule` - delivered by **P20** (`POST /api/digests`
        with a cadence is exactly a scheduled recurring distillation)

### P14 Phase 1 — what shipped

- `app/knowledge/digest_synthesizer.py` — `synthesize(..., framing="")`: optional
  instruction prepended to the prompt so distill modes steer the synthesis
  without forking the pipeline (additive; digests pass nothing).
- `app/knowledge/distiller.py` (new) — `gather_claims_for_jobs` (explicit job
  list, claim_id dedup, confidence floor — mirrors the digest gatherer) and
  `Distiller.distill(job_ids, mode, min_confidence)`: gather → synthesize
  (`synthesis` | `debate` framing) → persist run. No-claims and
  failed-synthesis degrade to `{success: False, error}` without persisting.
- `app/store/_distillations.py` (new `_DistillationsMixin`) +
  `distillations` table — `dst_<id>` runs with job set, mode, synthesis
  JSON, counts, tokens, model.
- `app/api/distill_routes.py` (new) — `POST /api/distill` (min 2 job ids,
  404 on unknown jobs, 400 on unknown mode / no extracted claims,
  synchronous, 5/min, spend recorded in the shared daily ledger),
  `GET /api/distill/{id}`, `GET /api/distill/{id}/markdown`,
  `GET /api/distillations`.
- `README.md` — Distiller paragraph under Subscription Digests.
- `tests/test_distiller.py` — **14 new tests** (gather/dedup/floor, persist,
  debate framing, unknown-mode, degradation without persistence, store
  round-trip/listing, route end-to-end incl. markdown + budget, guards),
  816/816 suite green (1 skipped).

Deferred: audio briefing (needs P9 TTS), the Distill/briefing Web UI.

**Example:** Subscribe to 5 crypto podcasts. Every morning, get a single 5-minute briefing: *"3 of 5 hosts are bullish on ETH, 2 flagged regulatory concerns, 1 mentioned a potential airdrop for Project X."*

---

## P16: Intelligent Webhooks & Agentic Notifications 🚧 (Phase 1 shipped)

**Goal:** Webhooks should deliver *intelligence*, not just status updates. Instead of "Job Complete", send: *"Job Complete. This video contains 3 actionable investment tips and 1 logical fallacy. See attached summary."*

> **Phase 1 status (✅ SHIPPED):** the three payload templates rendered from
> already-extracted data (never a fresh LLM call on the webhook path), the
> global-setting + per-job template selection, and the templates listing
> endpoint. Contradiction alerts (needs P13), custom variable-substitution
> templates, and smart routing/urgency are deferred. See "P16 Phase 1 — what
> shipped".

### Tasks

- [~] Extend webhook payload with AI-generated content:
  - [x] Include AI summary in webhook body (from the P12 summarize stage's
        persisted result when the job ran one — never generated at send time)
  - [x] Include detected entities (people, companies, …) + key topics
        (ranked by claim count from the P18 layer)
  - [x] Include sentiment overview (overall sentiment, heat score, dominant
        emotions from the cached P7 result)
  - [x] Include contradiction alerts — `contradiction_count` in the
        full_intelligence knowledge block (P13 stored rows, never a fresh run)
- [~] Webhook templates:
  - [x] **Minimal**: Status + title (current behavior; stays the default)
  - [x] **Summary**: Status + AI summary + key topics
  - [x] **Full Intelligence**: Status + summary + entities + sentiment +
        claim/prediction/contradiction counts
  - [ ] Custom templates with variable substitution — deferred
- [ ] Smart notification routing — deferred:
  - [ ] Route different types of content to different webhooks/channels
  - [ ] Example: Financial content → Slack #trading, Tech discussions → Slack #engineering
  - [ ] Urgency detection: flag time-sensitive information for immediate notification
- [~] API:
  - [x] Template selection: global `WEBHOOK_TEMPLATE` setting (surfaced in
        `GET /api/webhooks/config`) + per-job `webhook_template` override
        (settable on `POST /api/ingest`) — webhooks are config-based, there
        are no webhook entities to PUT
  - [x] `GET /api/webhooks/templates` - List available templates

### P16 Phase 1 — what shipped

Hard rule: the webhook path assembles, it never generates. Payloads are
built entirely from data other stages already persisted, so a notification
is fast, free, and safe to fire from any worker.

- `app/delivery/webhook_intelligence.py` (new) — template registry (`minimal` /
  `summary` / `full_intelligence`), `resolve_template` (job override → global
  setting → minimal on anything invalid), `build_job_completed_payload`:
  summary comes from the P12 summarize stage's persisted `detail`, topics and
  entities are ranked by claim frequency from the P18 layer (capped 8/10),
  sentiment reads the cached P7 result, plus knowledge status and
  claim/prediction counts. Every enrichment source is individually
  best-effort — a failure drops the field, never the delivery.
- `app/delivery/webhook_notifier.py` — `notify_job_complete` renders through the
  template layer with a fallback to the legacy minimal payload if rendering
  itself crashes (delivery beats enrichment).
- `app/config.py` — `webhook_template: str = "minimal"` (default preserves
  the legacy payload exactly; enriched payloads are opt-in).
- Job store — `webhook_template` column (migration + update allowlist).
- `app/api/webhook_routes.py` — `GET /api/webhooks/templates`; `template`
  surfaced on `GET /api/webhooks/config`.
- `app/api/ingest_routes.py` — `webhook_template` accepted on
  `POST /api/ingest` (validated, 400 on unknown) and persisted per job.
- `README.md` — webhook templates paragraph under Agentic Ingest.
- `tests/` — `test_webhook_intelligence.py` (10: template resolution
  incl. invalid fallback, legacy shape preservation, summary + topic
  ranking, entities/sentiment/counts, broken-source tolerance, notifier
  crash fallback, templates endpoint), +2 ingest-route template tests —
  **12 new tests**, 756/756 suite green (1 skipped).

Deferred: contradiction alerts (P13 substrate), custom variable-substitution
templates, smart per-content routing, urgency detection.

---

## P17: Structured Data Extraction ✅ (Notion deferred)

**Goal:** Transcription output shouldn't just be text — it should be structured, machine-readable data ready for downstream consumption.

> **Status:** the extraction service, five presets, ad-hoc custom schemas,
> the Web UI Extract section, and the JSON surface all shipped in earlier
> work (this section was never checked off). The 2026-08-05 completion pass
> added the two genuinely missing pieces: **saved reusable schemas**
> (`/api/extraction-schemas` CRUD + `schema_id` on the extract call) and
> **deterministic markdown/CSV export**. Notion pages remain deferred (same
> external-integration dependency as P21's Notion target).

### Tasks

- [x] Create structured extraction service (`app/knowledge/extractor.py`):
  - [x] LLM-powered extraction from transcript text *(shipped pre-completion-pass)*
  - [x] Configurable extraction schemas (user-defined or preset) — ad-hoc
        `custom_schema` per request *(earlier)* + saved named schemas via
        `schema_id` *(completion pass)*
- [x] Built-in extraction presets *(all shipped earlier)*:
  - [x] **Meeting Notes**: Attendees, agenda items, decisions, action items, deadlines
  - [x] **Interview**: Questions asked, answers given, key quotes
  - [x] **Tutorial**: Steps, tools mentioned, prerequisites, links
  - [x] **News/Analysis**: Claims, evidence, sources cited, predictions
  - [x] **Product Review**: Product name, pros, cons, rating, comparisons
- [~] Output formats:
  - [x] JSON (structured, machine-readable) *(earlier)*
  - [x] Markdown (human-readable, Obsidian/Notion-ready) —
        `GET /jobs/{id}/extract/export?format=markdown` *(completion pass)*
  - [x] CSV (for spreadsheet import) — `?format=csv`, flattened
        field/index/key/value rows *(completion pass)*
  - [ ] Notion page (via API integration) — deferred
- [x] Web UI *(shipped earlier — `ExtractSection.tsx`)*:
  - [x] "Extract" button with preset/schema selector
  - [x] Extracted data viewer
  - [x] Export to various formats (via the export endpoint)
- [x] API endpoints:
  - [x] `POST /jobs/{id}/extract` - Extract structured data *(earlier;
        now also accepts `schema_id`, 404 on unknown schema)*
  - [x] `GET /jobs/{id}/extract` - Get extraction results *(earlier)* +
        `GET /jobs/{id}/extract/export?format=json|markdown|csv` *(completion pass)*
  - [x] `POST /api/extraction-schemas` - Define custom extraction schema
        (+ GET list, GET one by id-or-name, DELETE; 409 on duplicate name)

### P17 completion pass — what shipped (2026-08-05)

- `app/store/_extraction_schemas.py` (new `_ExtractionSchemasMixin`)
  + `extraction_schemas` table — `xs_<hash>` IDs, UNIQUE name, fields JSON;
  addressable by id or name everywhere.
- `app/api/extract_routes.py` — `/extraction-schemas` CRUD router (409 on
  duplicate name, 422 on empty fields); `POST /jobs/{id}/extract` accepts
  `schema_id` (loads the saved schema, runs it as the CUSTOM preset;
  `preset` is now optional — 400 when neither is given);
  `GET /jobs/{id}/extract/export?format=` renders the cached result with no
  LLM call (404 when nothing cached, 400 on unknown format).
- `app/knowledge/extractor.py` — `render_extraction_markdown` (sections per
  field, bullet lists, object-list flattening) + `render_extraction_csv`.
- `tests/test_extraction_schemas.py` — **17 new tests** (store CRUD +
  duplicate handling, route CRUD flow, renderer output, export route
  formats + guards, schema_id extract path incl. 404/400), 802/802 suite
  green (1 skipped).

---

## P18: AI-Friendly Knowledge Schema

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

### Phase A — what shipped

- `app/knowledge/knowledge_schema.py` — `Claim`, `ClaimDraft`, `ExtractionRunResult`, `ChunkFailure`, `compute_claim_id`, `LLM_RESPONSE_SCHEMA`, `ClaimType` enum, `SCHEMA_VERSION`/`EXTRACTION_VERSION` constants
- `app/knowledge/llm_presets.py` — `TaskType`, `get_provider_for_task` (DB → env → default-preset → user-provider resolution chain), `_DEFAULT_PRESETS` (extract/summarize/synthesize/chat); resolves overrides from new `ai_settings.task_presets` JSON column with `_encrypt_secret`/`_decrypt_secret` round-trip on nested `api_key`s
- `app/knowledge/knowledge_extractor.py` — segment chunking (~3000 tokens, 200 overlap), JSON-mode prompting, defensive parsing (markdown fences + prose-wrapped JSON), per-chunk failure isolation with `raw_output` capture, claim_id-based dedup across overlapping chunks, storage floor 0.1; `success=False` when every chunk fails so callers don't wipe prior data
- `app/knowledge/embedding_store.py` — `EmbeddingStore` (upsert/get/cosine), behind a thin interface so Chroma/pgvector swap is one-file later; sentinel `DEFAULT_TEXT_MODEL`. Phase B fills in `embed()` + `query_topk`.
- `app/store.py` — `claims` / `embeddings` / `extraction_failures` tables; `knowledge_status` column on jobs; `ai_settings.task_presets` column; `upsert_claims`, `replace_claims_for_job` (atomic delete+insert in one tx), `get_claims_for_job`, `query_claims`, `delete_claims_for_job`, `set_/get_knowledge_status`, `record_extraction_failure`, `get_/set_task_presets` (api_key encryption)
- `app/api/knowledge_routes.py` — `POST /api/jobs/{id}/extract-knowledge`, `GET /api/jobs/{id}/knowledge`, `GET /api/claims` with `min_confidence` filter (defaults: 0.5 for both job + library queries); persists per-chunk failures to `extraction_failures` quarantine table on every run
- `tests/` — `test_knowledge_schema.py` (11), `test_knowledge_store.py` (21), `test_knowledge_extractor.py` (15), `test_llm_presets.py` (12) — **59 new tests**, all green

### Phase B — what shipped

- `app/knowledge/knowledge_schema.py` — `Entity`, `EntityDraft`, `EntityMention`, `EntityType` enum; `compute_entity_id` (stable `ent_<8-char hash>`); `normalize_entity_name`, `slugify_entity_name`; `ClaimDraft.entity_refs` list; extended `LLM_RESPONSE_SCHEMA` to `{claims, entities}` with per-claim `entity_refs` strings; `ExtractionRunResult` now carries `entities` + `mentions`
- `app/knowledge/embedding_store.py` — `normalize_for_embedding` (lowercase + collapse whitespace); lazy module-level model load w/ thread-lock; module-level `embed()` + `embed_async()` with in-memory FIFO cache (~10k entries, keyed by normalized text); `EmbeddingStore.query_topk` (type-scoped candidate filter, tolerates stale dim mismatches); opt-in `warmup()`
- `app/knowledge/entity_canonicalizer.py` — `EntityCanonicalizer` (run-cached); `canonicalize(name, type, confidence)` pipeline: normalize → embed-async → cosine match against same-type candidates (≥0.85 reuse) → else mint `compute_entity_id` + type-prefixed kebab slug with sequence-suffix on slug collision; alias merging on reuse; persists embedding to the generic `embeddings` table under `object_type="entity"`
- `app/store.py` — new `entities` (PK `entity_id`, UNIQUE `slug`, indexed on `entity_type`) + `entity_mentions` (FK entity_id, indexed on entity_id + episode_id) tables; `upsert_entity` (merges aliases), `get_entity_by_id`, `get_entity_by_slug`, `slug_exists`, `list_entities`, `find_entity_ids_by_type`, `add_entity_mention`, `get_mentions_for_entity`, `delete_mentions_for_episode`; `replace_claims_for_job(...)` extended to accept optional `entities` + `mentions` and rewrite them inside the same tx
- `app/knowledge/knowledge_extractor.py` — `KnowledgeExtractor` accepts a `canonicalizer`; chunk loop now parses `{claims, entities}`, canonicalizes entities first, resolves `entity_refs` → `entity_ids` through a name→id map (with fallback canonicalization for weak-signal names the LLM didn't also list), emits claim-anchored mentions + chunk-level mentions for unreferenced entities, best-effort `start_char`/`end_char` via `_find_char_span`; overlap dedup now merges `entity_ids` across copies
- `app/api/entity_routes.py` — `GET /api/entities` (filter by type/since/slug), `GET /api/entities/{id_or_slug}` (accepts hash id or slug), `GET /api/entities/{id_or_slug}/mentions`
- `app/api/knowledge_routes.py` — `POST /jobs/{id}/extract-knowledge` now passes entities + mentions into the transactional `replace_claims_for_job`
- `app/api/__init__.py` — entity router wired up
- `pyproject.toml` — `sentence-transformers>=3.0` dependency
- `tests/` — `test_entity_canonicalizer.py` (8), `test_embedding_store_search.py` (11), `test_entity_api.py` (9), +5 Phase B tests in `test_knowledge_extractor.py`, +9 Phase B tests in `test_knowledge_store.py`, +14 Phase B tests in `test_knowledge_schema.py` — **56 new tests**, 154/154 suite green

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
- [x] `app/knowledge/topic_canonicalizer.py` — `canonicalize(name, description) → topic_id`; normalize → embed `"{name}: {description}"` → query_topk against existing topics → ≥0.90 cosine reuse (merge alias, update description if confidence higher) → else mint `top_<hash>`.
- [x] `app/knowledge/topic_aggregator.py` — `aggregate(claims) → (topics, edges)`; numbered-claim prompt, LLM call via `summarize` preset, parses `{topics: [{name, description, confidence, claim_indices: [int]}]}`, resolves indices back to `claim_id`s.
- [x] `app/knowledge/topic_normalization.py` — `TICKER_MAP` + `normalize_topic_for_match(text)`; pure module, no DB.
- [x] `app/api/topic_routes.py` — `GET /api/topics`, `GET /api/topics/{id}`, `GET /api/topics/{id}/claims`.

**Extend:**
- [x] `app/knowledge/knowledge_schema.py` — add `Topic`, `TopicDraft`, `ClaimTopicEdge`, `TOPIC_AGGREGATION_SCHEMA` (separate from `LLM_RESPONSE_SCHEMA`), `compute_topic_id`.
- [x] `app/store.py` — `topics` + `claim_topics` tables; `upsert_topic`, `get_topic_by_id`, `list_topics`, `get_claim_topic_edges`, `get_claims_for_topic`; extend `replace_claims_for_job` to accept `topics` + `claim_topic_edges` and replace both inside the existing tx.
- [x] `app/knowledge/knowledge_extractor.py` — after claims validate, if `len(claims) >= 3` and a `summarize` provider is configured, run `TopicAggregator.aggregate(claims)` → `(topics, edges)`; attach to `ExtractionRunResult`; populate `Claim.topic_ids` from edges as denormalized cache.
- [x] `app/api/knowledge_routes.py` — pass `topics` + `claim_topic_edges` into `replace_claims_for_job`.
- [x] `app/api/__init__.py` — register `topic_router`.

**Tests:**
- [x] `tests/test_topic_canonicalizer.py` — normalization (ticker expand, plural collapse, whitespace); cosine reuse ≥0.90; below-threshold mints new; description merge on reuse.
- [x] `tests/test_topic_aggregator.py` — numbered-claim prompt; LLM response → `(topics, edges)` mapping; claim-index out-of-range handled; empty/malformed LLM output returns empty result.
- [x] `tests/test_topic_api.py` — list/get/claims endpoints (TestClient pattern from `test_entity_api.py`).
- [x] Extend extractor + store + schema tests for topic path.

### Phase C.1 — what shipped

- `app/knowledge/topic_normalization.py` — `TICKER_MAP` (btc/eth/sol/… → names, llm/rag/mcp → expansions), `normalize_topic_for_match` (compose: `normalize_for_embedding` → ticker expand → conservative last-word plural collapse that preserves `-ss`/`-us`/`-is`/`-os`/`-ies` endings)
- `app/knowledge/knowledge_schema.py` — `Topic`, `TopicDraft`, `ClaimTopicEdge`, `compute_topic_id` (stable `top_<8-char hash>` over normalized name), `TOPIC_AGGREGATION_SCHEMA` (separate LLM schema for the second-pass call — one `topics` array, each with `name / description / confidence / claim_indices`); `ExtractionRunResult` carries `topics` + `claim_topic_edges`
- `app/knowledge/topic_canonicalizer.py` — embed `f"{normalized_name}: {description}"`, cosine ≥ **0.90** reuse with alias merge + description replacement on higher-confidence hit, else mint new `top_<hash>` and write the embedding under `object_type="topic"` in the generic `embeddings` table (so Phase B's `query_topk` just works)
- `app/knowledge/topic_aggregator.py` — second-pass service; `aggregate(claims) → (topics, edges, tokens)`; numbered claim prompt, `summarize` task preset, `TOPIC_AGGREGATION_SCHEMA` JSON-mode response; graceful degradation on every failure axis (no provider / no canonicalizer / below `MIN_CLAIMS_FOR_AGGREGATION=3` / malformed JSON / missing `topics` field / out-of-range `claim_indices`); truncates to top-confidence `MAX_CLAIMS_PER_CALL=120` when oversized
- `app/knowledge/knowledge_extractor.py` — optional `topic_aggregator` ctor arg; after claim dedup, if `len(final_claims) >= MIN_CLAIMS_FOR_AGGREGATION` and aggregator is wired, runs the topic pass inside a broad try/except (topic failure never fails the run) and rewrites each claim's `topic_ids` from the edges as the denormalized cache
- `app/store.py` — new `topics` (PK `topic_id`) + `claim_topics` (composite PK `(claim_id, topic_id)` + confidence + FK on both sides) tables; `upsert_topic` (merges aliases), `get_topic_by_id`, `list_topics`, `find_topic_ids`, `add_claim_topic_edge`, `get_claim_topic_edges`, `get_claims_for_topic` (joins through `claim_topics`, not the JSON cache); `replace_claims_for_job(...)` extended with `topics` + `claim_topic_edges` args — explicit `DELETE FROM claim_topics WHERE claim_id IN (...)` before the claim delete closes the orphan-edges hole without flipping `PRAGMA foreign_keys` globally; bogus edges (claim_id not in this run) are logged and dropped rather than crashing the tx
- `app/api/topic_routes.py` — `GET /api/topics` (since/limit/offset), `GET /api/topics/{topic_id}`, `GET /api/topics/{topic_id}/claims` (reads from the join so reverse queries always see source of truth)
- `app/api/knowledge_routes.py` — `POST /jobs/{id}/extract-knowledge` passes `topics` + `claim_topic_edges` into `replace_claims_for_job` so claims / entities / mentions / topics / edges land in one transaction
- `app/api/__init__.py` — topic router wired
- `README.md` — Knowledge Extraction bullet expanded to surface `/api/entities` + `/api/topics` alongside the existing `/api/claims` mention (covered both Phase B + C.1 README drift in one pass)
- `tests/` — `test_topic_canonicalizer.py` (17), `test_topic_aggregator.py` (9), `test_topic_api.py` (7), +15 topic tests in `test_knowledge_schema.py`, +11 topic tests in `test_knowledge_store.py`, +3 topic-pass tests in `test_knowledge_extractor.py` — **54 new tests**, 208/208 suite green

Commit: `7d3ce0f feat(knowledge): P18 Phase C.1 — topics aggregation layer`. Includes post-review polish (docstring accuracy for the `claim_topics` upsert SQL, graceful-degradation branches enumerated on `TopicAggregator.aggregate`).

### Phase C.2 — locked decisions (Predictions)

1. **Dedicated `predictions` table, FK `claim_id UNIQUE`.** Physically separate from `claims`. Prediction is semantically a `claim_type`, but the lifecycle columns (`target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolved_at`) aren't "just nullable fields" — they're the start of a lifecycle. Separate table keeps claim rows clean and makes future expansion (resolution events, resolution evidence, confidence recalibration, tracking dashboards) land on a dedicated row instead of adding more nullable columns.
2. Prediction-specific extraction prompts + validation; API endpoints `GET /api/predictions?resolution=pending`, `POST /api/predictions/{id}/resolve`.

### Phase C.2 — tasks ✅ (all shipped)

**Schema:**
- [x] `app/knowledge/knowledge_schema.py` — `Prediction` + `PredictionDraft` Pydantic models; `Resolution` enum (`pending` | `true` | `false` | `unresolvable`); `target_horizon` kept as a free-form string (date / interval / event-conditional / null) — see "what shipped" for the rationale; extend `ExtractionRunResult` with `predictions: list[Prediction]`.
- [x] `app/knowledge/knowledge_schema.py` — new `PREDICTION_EXTRACTION_SCHEMA` JSON-mode schema for the dedicated prediction-enrichment pass.

**Storage:**
- [x] `app/store.py` — `predictions` table (`claim_id TEXT PK + FK`, lifecycle columns, indexes on `resolution` + `created_at`). Re-extraction cleanup is explicit (`DELETE FROM predictions WHERE claim_id IN (…)` before the claims delete) instead of relying on `PRAGMA foreign_keys=ON`, mirroring the `claim_topics` pattern.
- [x] `app/store.py` — `upsert_prediction`, `get_prediction_by_claim_id`, `list_predictions` (filter by `resolution` + `since`), `resolve_prediction` (handles revert-to-pending separately so resolution metadata gets cleared on revert). Extended `replace_claims_for_job` with optional `predictions=` arg, written in the same tx as claims; bogus rows pointing at unknown claim_ids are dropped rather than crashing the tx.

**Extraction:**
- [x] `app/knowledge/prediction_extractor.py` **(new)** — second-pass service over `claim_type="prediction"` claims; reuses `extract` task preset; full graceful-degradation parity with `TopicAggregator.aggregate`.
- [x] `app/knowledge/knowledge_extractor.py` — optional `prediction_extractor` ctor arg; runs after claim dedup + topic pass; surfaces `result.predictions`.

**API:**
- [x] `app/api/prediction_routes.py` **(new)** — `GET /api/predictions?resolution=&since=&limit=&offset=`, `GET /api/predictions/{claim_id}`, `POST /api/predictions/{claim_id}/resolve`, `DELETE /api/predictions/{claim_id}/resolve` (revert).
- [x] `app/api/knowledge_routes.py` — passes `predictions=` into `replace_claims_for_job`.
- [x] `app/api/__init__.py` — `prediction_router` wired.

**Tests:**
- [x] `tests/test_prediction_extractor.py` — 11 tests covering happy path, filtering, graceful degradation, truncation.
- [x] `tests/test_prediction_api.py` — 10 tests covering list / get / resolve / revert / 404s / pending-via-POST guard.
- [x] Extend `tests/test_knowledge_store.py` — 10 prediction-CRUD + transactional-replace tests (including operator-set resolution surviving re-extraction).
- [x] Extend `tests/test_knowledge_schema.py` — `Prediction` model, `Resolution` enum, `PredictionDraft` defaults, `PREDICTION_EXTRACTION_SCHEMA` shape (10 tests).
- [x] Extend `tests/test_knowledge_extractor.py` — 3 tests for prediction-pass wiring (happy / failure / no-extractor).

**Docs:**
- [x] `docs/todo.md` — "Phase C.2 — what shipped" block below.
- [x] `README.md` — `/api/predictions` surfaced + lifecycle-metadata sentence added under the Knowledge Extraction bullet.

### Phase C.2 — what shipped

- `app/knowledge/knowledge_schema.py` — `Prediction` (full lifecycle row: `claim_id` FK, `target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolution_note`, `resolved_at`, `resolved_by`, `created_at`, `updated_at`), `PredictionDraft` (LLM-only fields), `Resolution` string enum (`pending|true|false|unresolvable`), `PREDICTION_EXTRACTION_SCHEMA` (one record per `claim_index` with nullable lifecycle fields), `ExtractionRunResult.predictions`. Decision: `target_horizon` stays a free-form string instead of a structured `TargetHorizon` union — LLMs are unreliable at parsing precise dates and we'd rather store source text verbatim than throw away signal trying to canonicalize it. Structured-date parsing can land in Phase D as a separate column without a wire-format break.
- `app/store.py` — `predictions` table (`claim_id` PK + FK to `claims`), indexes on `resolution` + `created_at`; `_upsert_prediction_row` (ON CONFLICT updates *only* lifecycle-input fields, deliberately leaves `resolution`/`resolution_note`/`resolved_at`/`resolved_by` alone so re-extraction never clobbers operator state); `upsert_prediction`, `get_prediction_by_claim_id`, `list_predictions(resolution, since, limit, offset)`, `resolve_prediction` (forks revert-to-pending to wipe resolution metadata vs. set-resolved to record `resolved_at`/`resolved_by`). `replace_claims_for_job` extended: explicit `DELETE FROM predictions WHERE claim_id IN (SELECT … WHERE episode_id=?)` before the claim delete (same FK-PRAGMA-off workaround as `claim_topics`), and bogus prediction rows pointing at non-run claim_ids are logged + dropped rather than crashing the tx.
- `app/knowledge/prediction_extractor.py` — `PredictionExtractor` (one instance per run), `enrich(claims) → (predictions, tokens)`. Filters to `claim_type=PREDICTION` internally so callers can pass the full claims list. `MAX_PREDICTIONS_PER_CALL=60` truncation by descending confidence. Drops drafts where every lifecycle field is null (no signal beyond the claim itself). Full graceful-degradation parity with `TopicAggregator`: missing provider / no prediction-type claims → `([], 0)` without calling LLM; LLM throws / unparseable → `([], 0)`; `predictions` field missing → `([], tokens)` so cost surfaces; out-of-range `claim_index` / malformed draft → skipped, rest still lands.
- `app/knowledge/knowledge_extractor.py` — `KnowledgeExtractor.__init__` gains optional `prediction_extractor`; `from_settings()` wires both `TopicAggregator` and `PredictionExtractor` when their providers are available; the prediction pass runs after the topic pass with the same broad try/except (additive signal must never block the run). `result.predictions` + per-pass token cost folded into `tokens_used`.
- `app/api/prediction_routes.py` — `GET /api/predictions` (filter by `resolution` + `since`), `GET /api/predictions/{claim_id}`, `POST /api/predictions/{claim_id}/resolve` (body: `{resolution, note?, resolved_by?}`), `DELETE /api/predictions/{claim_id}/resolve`. POST with `resolution=pending` returns 400 — operators end up clearing resolution metadata they didn't mean to; force them through the DELETE endpoint that exists for exactly this.
- `app/api/knowledge_routes.py` — `POST /jobs/{id}/extract-knowledge` now threads `predictions=` into `replace_claims_for_job` so claims / entities / mentions / topics / edges / predictions land in one transaction.
- `app/api/__init__.py` — `prediction_router` wired under `/api`.
- `README.md` — Knowledge Extraction bullet expanded to surface `/api/predictions` and the lifecycle-tracking story.
- `tests/` — `test_prediction_extractor.py` (11), `test_prediction_api.py` (10), +10 prediction tests in `test_knowledge_store.py`, +10 prediction tests in `test_knowledge_schema.py`, +3 prediction-pass tests in `test_knowledge_extractor.py` — **44 new tests**, 252/252 suite green.

---

### Phase C.3 — locked decisions (Backfill + cost guardrails)

1. **Both-trigger backfill** (background scheduler + route-triggered on-demand). Background-only feels stale; on-demand-only misses cold inventory. Both is the right default — dedup is the interesting engineering problem.
2. **Status machine: `pending | running | ready | failed`** + `knowledge_version` + `locked_at` / `worker_id` for claim-lock. Idempotent enqueue: calling enqueue twice on the same pending job is a no-op.
3. **Route behavior on `/jobs/{id}/knowledge`:** `ready` → return cached. `running` → return in-progress status (client polls). `pending` → acquire lock, run inline if cheap enough, otherwise enqueue and return `202 Accepted`.
4. **Budgets: global default + per-subscription override.** Global daily extraction budget in settings; optional per-feed override + priority tier; downgrade to cheaper `extract` model when over budget. Top-priority feeds stay on the better model longer.

### Phase C.3 — tasks

**Storage + state machine:**
- [x] `app/store/_schema.py` — migration: add `knowledge_version INTEGER DEFAULT 0`, `knowledge_locked_at TEXT`, `knowledge_worker_id TEXT` to `jobs` table + `idx_knowledge_status` index; documented the `none|pending|running|ready|failed` enum (legacy `extracting`/`complete` accepted as aliases).
- [x] `app/store/_backfill.py` **(new mixin)** — `acquire_knowledge_lock(job_id, worker_id, ttl_seconds)` (atomic conditional UPDATE, reclaims stale locks), `release_knowledge_lock`, `reap_stale_knowledge_locks`, `enqueue_knowledge_job`, `mark_jobs_pending_for_backfill`, `list_pending_knowledge_jobs` (priority-ordered), `count_pending_knowledge_jobs`, `get_knowledge_status_counts`, `get_knowledge_version`.

**Background worker:**
- [x] `app/knowledge/knowledge_backfill.py` **(new — `app/ingest/`, matching the existing worker convention rather than the nonexistent `app/workers/`)** — `KnowledgeBackfillWorker.tick`/`process_job`, priority queue (reuses the 1-10 `priority` column), per-day budget check, model-downgrade on threshold, stale-lock reaper each tick; shared `resolve_segments_for_job` (warm in-memory → cold persisted `transcription_result`), `persist_extraction_result`, `quarantine_failures`.
- [x] Register worker in `app/main.py` lifespan (start after storage manager, stop before it); gated on `knowledge_backfill_enabled`, optional `knowledge_seed_on_startup`.

**Route behavior:**
- [x] `app/api/knowledge_routes.py` — `GET /jobs/{id}/knowledge` returns 202 + `run_state` when `pending`/`running`; runs inline through the worker when the transcript is ≤ `knowledge_inline_max_segments` and a provider is available; returns cached rows otherwise.

**Budget tiers:**
- [x] `app/config.py` — `knowledge_backfill_enabled`/`_interval`/`_batch_size`, `knowledge_lock_ttl_seconds`, `knowledge_seed_on_startup`, `knowledge_daily_budget_usd`, `knowledge_model_downgrade_threshold_usd`, `knowledge_inline_max_segments`.
- [x] Subscription model — optional `knowledge_budget_override_usd` + `knowledge_priority_tier` per subscription (migration + allowlist).
- [x] `app/knowledge/llm_presets.py` — `downgrade_model` + `get_provider_for_task(task, downgrade=True)`; `app/knowledge/knowledge_budget.py` blended price table + per-UTC-day spend tracker singleton.

**API:**
- [x] `POST /api/jobs/{id}/knowledge/enqueue` — idempotent enqueue for a pending job.
- [x] `GET /api/knowledge/backfill-status` — stats endpoint (pending/running/ready counts, today's spend, downgrades applied).

**Tests:**
- [x] `tests/test_knowledge_backfill_store.py` (19) — enqueue, lock acquire/release, stale-lock reaper, priority ordering, status counts.
- [x] `tests/test_knowledge_budget.py` (17) — pricing, daily rollover, per-sub isolation, budget/threshold decisions.
- [x] `tests/test_knowledge_backfill.py` (13) — happy path, no-segments, lock-lost, no-provider requeue, downgrade, tick batch/budget/reap, segment resolution.
- [x] `tests/test_knowledge_backfill_api.py` (8) — 202 paths, inline run, cached read, enqueue idempotency/404, backfill-status. (+3 in `test_llm_presets.py`.)

**Docs:**
- [x] `docs/todo.md` — "Phase C.3 — what shipped" summary (below).
- [x] `README.md` — on-demand + background backfill behavior.

### Phase C.3 — what shipped

- `app/store/_schema.py` — three new migrated columns (`knowledge_version`, `knowledge_locked_at`, `knowledge_worker_id`) + `idx_knowledge_status`. The `knowledge_status` vocabulary is `none|pending|running|ready|failed`; the synchronous extract route's legacy `extracting`/`complete` are still written and treated as `running`/`ready` aliases everywhere (acquire, counts) so the two extraction paths interoperate without a breaking migration.
- `app/store/_backfill.py` (new `_BackfillMixin`, wired into the composed `JobStore`) — the claim-lock state machine. `acquire_knowledge_lock` is a single conditional UPDATE that wins atomically and lazily reclaims locks older than the TTL (crashed workers); `reap_stale_knowledge_locks` is the eager sweep so status reporting stays honest. `enqueue_knowledge_job` is idempotent (`none|failed → pending` only). `list_pending_knowledge_jobs` orders by `priority DESC, created_at DESC` and excludes jobs with no persisted transcript (nothing to extract from).
- `app/knowledge/knowledge_budget.py` (new) — `estimate_cost_usd(model, tokens)` blended $/1K table (longest-substring match; local models free; unknown → non-zero fallback so they still count) + `KnowledgeBudgetTracker`, a thread-safe per-UTC-day ledger (global + per-subscription spend + downgrade counter) held as a process singleton. In-memory by design — a restart never *locks out* extraction, the safe direction for a guardrail. Decision helpers (`over_global_budget`/`should_downgrade`/`over_subscription_budget`) keep the worker declarative.
- `app/knowledge/llm_presets.py` — `MODEL_DOWNGRADES` map + `downgrade_model` (longest-substring, no double-downgrade of already-cheap models); `get_provider_for_task(task, *, downgrade=False)` swaps to a cheaper *same-provider* model when set, so resolved creds/base_url still apply.
- `app/knowledge/knowledge_extractor.py` — `from_settings(downgrade=False)` threads the flag to the primary `extract` provider only; the additive topic/prediction passes stay on their normal presets.
- `app/knowledge/knowledge_backfill.py` (new) — `KnowledgeBackfillWorker` mirrors the `scheduler.py` lifecycle (singleton + `start`/`stop`). `tick()` reaps stale locks, checks the daily budget, and processes a priority batch; `process_job()` acquires the lock, resolves segments (warm→cold), builds a (possibly downgraded) extractor, records spend, persists via the shared `persist_extraction_result`, and releases the lock `ready`(+version bump)/`failed`/`pending`. The orchestration loop is thin; `tick`/`process_job` are the unit-testable seam (injectable `extractor_factory`). `resolve_segments_for_job` + `persist_extraction_result` + `quarantine_failures` are shared with the route so the inline and background paths can't drift.
- `app/api/knowledge_routes.py` — `GET /jobs/{id}/knowledge` now returns `run_state` and HTTP 202 for `running`/`pending`-deferred; small pending jobs run inline through the worker (identical persistence + budget accounting). `POST /jobs/{id}/knowledge/enqueue` (idempotent, 404 on unknown job) and `GET /knowledge/backfill-status` (counts + today's spend + downgrades + configured budgets) added. The synchronous `extract-knowledge` route was refactored onto the shared `persist_extraction_result`/`quarantine_failures` helpers and now records spend against the same daily budget.
- `app/config.py` — backfill worker + cost-guardrail settings (all default-safe: worker on, budgets `None` = unlimited, seed-on-startup off).
- `app/store/subscription_store.py` — `knowledge_budget_override_usd` + `knowledge_priority_tier` columns (migration + update allowlist). The tracker supports per-subscription budgets today; job→subscription enforcement in the worker is deferred to P20's digest runner, which owns the feed→job mapping.
- `app/main.py` — backfill worker started/stopped in the app lifespan.
- `tests/` — `test_knowledge_backfill_store.py` (19), `test_knowledge_budget.py` (17), `test_knowledge_backfill.py` (13), `test_knowledge_backfill_api.py` (8), +3 in `test_llm_presets.py` — **60 new tests**, 412/412 suite green.

Scope notes: the worker lives in `app/ingest/` (not the roadmap's aspirational `app/workers/`, which doesn't exist) to match `scheduler.py`/`subscription_worker.py`. Per-subscription budget *enforcement* is wired at the tracker layer but not yet applied per-job in the worker — jobs carry no `subscription_id`, and the clean mapping lives in P20's digest runner.

### Phase D — what shipped

- `app/pipeline/workflow.py` — `WorkflowProcessor._enqueue_knowledge_extraction(job_id)`, called right after a transcription is persisted + marked `COMPLETED`. It only flips the job to `knowledge_status='pending'` via the Phase C.3 `enqueue_knowledge_job` state machine (the background worker does the actual extraction), so transcription latency is unchanged. Gated on `knowledge_auto_extract`; wrapped best-effort so a KB hiccup can never fail the transcription that just succeeded. This closes the P18 loop — new episodes flow into the KB with no manual trigger.
- `app/config.py` — `knowledge_auto_extract: bool = True` (Phase D auto-run toggle).
- `docs/knowledge-schema.md` (new) — the canonical schema contract every consumer (P19 MCP, P20 Digest, P10/P11 RAG, P16 webhooks) reads from: versioning + re-extraction policy, every model (Claim / Entity / EntityMention / Topic / Prediction / Embedding) with field tables, the confidence model, the run-state machine (with both triggers), LLM task presets, storage tables, and the full `/api` surface.
- `pyproject.toml` — `pytest-cov>=5.0.0` dev dependency (both `[project.optional-dependencies].dev` and `[tool.uv].dev-dependencies`). Measure with `uv run pytest --cov=app --cov-report=term-missing`.
- `tests/` — `test_workflow_knowledge_autorun.py` (6: hook flag gating, idempotency, best-effort error swallow, end-to-end via a fake transcriber), `test_knowledge_extract_route.py` (6: synchronous extract route success / total-failure-doesn't-overwrite / all guard branches), `test_embedding_store_unit.py` (15: storage round-trip, cosine ranking + helper, dim-mismatch skip, singleton), `test_knowledge_backfill_lifecycle.py` (8: start/stop/run-loop, seed-on-startup, default extractor factory, process_job exception path) — **35 new tests**, 447/447 suite green. The P18 knowledge surface is ~93% covered; every knowledge module ≥81%.

Scope notes: `workflow.py`'s overall coverage stays low (28%) because its download/convert/transcribe pipeline predates the knowledge work and is out of P18 scope — the new auto-run hook itself is fully covered. The auto-run path *enqueues* rather than extracting inline (even for tiny transcripts) so the transcription request returns immediately; the on-demand GET route still runs small jobs inline for interactive reads.

---

## P19: Sift MCP Server (Capability Surface)

**Goal:** Expose Sift as an MCP (Model Context Protocol) server so Claude Desktop, Cursor, and custom agents can call Sift primitives directly. This shifts Sift from "an app that ships connectors" to "a capability surface" — Obsidian / Notion / Logseq become *agent-side targets*, not Sift-side integrations.

> The unlock: build N agent skills on top of one MCP server, instead of N×M point-to-point connectors. Inspired by the `podwise-cli` MCP surface, but goes deeper because Sift has the structured knowledge layer (P18) underneath.

> **Phase 1 status (✅ SHIPPED):** the MCP scaffold + every tool backed by P18 / existing routes is live (HTTP-client architecture, `X-API-Key` passthrough, stdio transport). Tools needing unbuilt phases are still unchecked and intentionally *not registered* on the server yet. See "P19 Phase 1 — what shipped" below.

### Tool surface (stable JSON Schema per tool)

- [x] **Ingest & retrieval**
  - [x] `ingest_url(url, profile?)` — submit URL, return `episode_id` + pipeline status (profile=P12, not yet wired)
  - [x] `get_transcript(episode_id, format?)` — text / JSON-with-timestamps / formatted
  - [x] `get_chapters(episode_id)` — auto-generated chapter markers
  - [x] `get_segment(episode_id, start, end)` — pull a specific time range (composed client-side)
  - [x] `get_clips(episode_id, criteria?)` — viral / insightful / topic-filtered clips
- [x] **Understanding**
  - [x] `get_summary(episode_id, mode?)` — bullets / chapters / topics / action items
  - [x] `get_highlights(episode_id)` — pull-quote-grade excerpts with timestamps (derived from clips)
  - [x] `get_claims(episode_id)` — structured claims (reads from P18)
  - [x] `get_entities(episode_id)` — people / companies / tickers / projects (composed from claims)
  - [x] `get_topics(episode_id)` — topic graph (composed from claims)
  - [x] `get_predictions(episode_id)` — falsifiable forward-looking claims (composed from claims)
- [x] **Q&A** (shipped with P10 + P11 Phase 1)
  - [x] `ask_episode(episode_id, question)` — RAG against single episode (P11 Phase 1)
  - [x] `ask_at_timestamp(episode_id, time_range, question)` — scoped Q&A (P11 Phase 1)
  - [x] `search_library(query, filters?)` — semantic search across all episodes (P10 Phase 1; plus per-episode `search_segments`)
- [ ] **Cross-episode synthesis** (deferred — depends on P13/P20)
  - [ ] `compare_episodes(episode_ids[], topic?)` — agreements / disagreements
  - [x] `find_contradictions(episode_id?, speaker?, analyze?)` — surface inconsistencies (P13 Phase 1; topic/timeframe filters deferred)
  - [ ] `summarize_trend(topic, last_n_days)` — narrative evolution over time
- [ ] **Export** (deferred — depends on P21)
  - [ ] `export_to_vault(episode_id, target, template?)` — Obsidian / Notion / Logseq (depends on P21)

### Tasks

- [x] Implement `sift-mcp` server:
  - [x] stdio transport (Claude Desktop, local agents)
  - [ ] HTTP transport (remote agents, Cursor) — `run_streamable_http_async` exists in the SDK; stdio-only for now
  - [x] Auth via Sift API key (passthrough)
  - [ ] Streaming for long-running tools (`ingest_url`, `ask_episode`) — deferred
- [x] Schema-first: every tool ships with a stable JSON Schema (FastMCP derives it from typed signatures + docstrings)
- [ ] Reference agent skills (shipped in repo):
  - [ ] **Episode → Obsidian note** (claims + highlights + clickable timestamps)
  - [ ] **Weekly recap** (cross-source synthesis from subscriptions)
  - [ ] **Topic research** (search → claims → contradictions → brief)
  - [ ] **Language learning** (transcript + translation + key vocabulary)
- [ ] Distribution:
  - [x] install path (`uv sync --extra mcp` + `uv run sift-mcp`; `sift-mcp` console script registered)
  - [x] Claude Desktop config snippet in README
  - [x] Cursor MCP config snippet
  - [x] Test suite covering the tool surface + HTTP client (raw MCP client via `FastMCP.call_tool`)

### P19 Phase 1 — what shipped

Architecture: the MCP server is an **HTTP client of the Sift REST API** (`X-API-Key` passthrough), so it works against a local or remote Sift and carries no DB coupling. Scope: only the tools backed by P18 + existing routes are registered; phase-dependent tools (P10/P11/P13/P20/P21) are intentionally omitted, not stubbed.

- `app/mcp_server/config.py` — `MCPConfig` + `load_config()` from env (`SIFT_API_URL`, `SIFT_API_KEY`, `SIFT_MCP_TIMEOUT`); decoupled from the heavy `app.config`.
- `app/mcp_server/client.py` — `SiftClient` (async httpx wrapper): one method per endpoint, `X-API-Key` header, `SiftAPIError` normalization (server `detail` + status; transport failures), and `get_knowledge` returns `(status, body)` so a 202 (extraction pending) isn't an error. `httpx.AsyncClient` is injectable for tests.
- `app/mcp_server/server.py` — `build_server()` returns a `FastMCP` with 11 tools. Per-episode `get_entities`/`get_topics`/`get_predictions` are **composed** from `get_claims` (the API only offers global entity/topic/prediction lists): collect `entity_ids`/`topic_ids` / prediction-type `claim_id`s from the episode's claims, fetch each, skip 404s. 202 → uniform `{status: "pending", run_state, message}`.
- `app/mcp_server/__main__.py` — `sift-mcp` entry point; stdio transport.
- `pyproject.toml` — `mcp>=1.2.0` (extra `[mcp]` + uv dev), `sift-mcp` console script.
- `README.md` — MCP Server section with Claude Desktop + Cursor config snippets and the deferred-tools note.
- `tests/` — `test_mcp_client.py` (8: path/params/headers, 202 non-raise, 404 + transport error mapping), `test_mcp_server_tools.py` (16: registration incl. deferred-tools-absent, transcript formats, segment slicing, summary mode validation, highlights ranking, knowledge composition + dedup + 404-skip, 202-pending) — **24 new tests**, 471/471 suite green.

Deferred: HTTP/streamable transport (SDK supports it; stdio covers Claude Desktop + local Cursor today), streaming for long tools, and the reference agent skills (Obsidian note / weekly recap / topic research / language learning) — those want P20/P21 substrate to be worth shipping.

---

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis)

**Goal:** Turn Sift from on-demand tool into always-on knowledge pipeline. Nightly ingest of subscribed feeds → structured extraction (P18) → cross-episode synthesis → multi-channel digest output. The differentiator vs. single-episode summarizers is *cross-source synthesis*: what 5 podcasts said about the same topic this week, who's repeating which narrative, what's new framing.

> Single-episode summary is a feature; continuous knowledge monitoring is the product.

> **Phase 1 status (✅ SHIPPED):** the cross-episode synthesis core is live — digest configs, the scheduled runner, synchronous run-now, and on-demand topic synthesis. Email/Notion/Obsidian channels, inbox UI, source ranking, and semantic cross-feed dedup are deferred. See "P20 Phase 1 — what shipped" below.

### Phase 1 — Subscription-driven brief

- [x] Scheduled digest runner (`app/knowledge/digest_runner.py` — `app/ingest/` to match the worker convention, not the aspirational `app/workers/`)
- [ ] Per-subscription pipeline profile (Quick / Deep / Full — reuses P12) — deferred
- [x] Auto-extract structured knowledge per new episode (delivered by P18 Phase D auto-run; the digest reads the resulting claims)
- [ ] Daily digest **email** per subscription set — deferred (no SMTP infra); webhook channel shipped instead
- [x] Cost guardrails (shared per-UTC-day LLM budget; runner records spend + skips when over)
- [~] Failure handling: empty-window / no-provider / malformed-output all degrade to a recorded run; caption/transcript-quality fallbacks deferred

### Phase 2 — Topic synthesis

- [x] On-demand cross-source synthesis for a topic (`GET /api/topics/{id}/synthesis`)
- [~] Daily topic answers — the synthesis covers which episodes touched it, cross-source agreement/disagreement, predictions, and narratives; *scheduled* per-topic digests + new-since-yesterday diffing deferred
  - [x] Which episodes mentioned it
  - [x] New claims / predictions on this topic
  - [x] Cross-source agreement / disagreement
  - [x] Repeated-narrative detection (who is amplifying which framing)
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
  - [x] `POST /api/digests` - Create / configure a digest
  - [x] `GET /api/digests/{id}` - Get config + latest digest output (+ `GET /api/digests`, `PATCH`, `DELETE`, `POST /{id}/run`, `GET /{id}/runs`)
  - [~] `POST /api/topics` - Track a topic — topics are auto-created by P18 extraction; explicit user-tracked topics deferred
  - [x] `GET /api/topics/{id}/synthesis` - Cross-source synthesis for a topic

### P20 Phase 1 — what shipped

The differentiator — **cross-episode synthesis** — end to end. A *digest config* is a first-class entity (a named set of subscriptions + window + cadence + optional webhook), deliberately more general than per-subscription so a digest can span feeds ("what 5 podcasts said this week"). The subscription→episode link uses the existing `subscription_items.job_id` (no new column on `jobs`).

- `app/knowledge/digest_schema.py` — `DigestSynthesis` (headline, themes, consensus, disagreements, predictions, narratives) + sub-models + `DigestRunResult`; `render_digest_markdown` (deterministic, no-LLM rendering for channels/preview); `DIGEST_SCHEMA_VERSION`.
- `app/knowledge/digest_synthesizer.py` — `DigestSynthesizer.from_settings()` resolves the `synthesize` task preset (better model allowed). `synthesize(claims, …)` formats source-attributed claim lines (confidence-ordered, capped), JSON-mode prompt, defensive parse. Graceful degradation: too-few-claims / no-provider / malformed-output / provider-exception all return a non-success `DigestRunResult` instead of raising.
- `app/store/_digest.py` (new `_DigestMixin`) + tables in `_schema.py` (`digest_configs`, `digest_runs`) — config CRUD, `list_due_digests` (cadence-elapsed selection), run persistence + history + latest-run. `subscription_ids` stored as a JSON array.
- `app/knowledge/digest_runner.py` + `digest_runner_helpers.py` — `gather_claims_for_digest` (window-filter via `downloaded_at`, dedup by `claim_id`, min-confidence floor) and `run_digest` (gather → synthesize → persist run → advance `last_run_at` → record spend → best-effort webhook). Background `DigestRunner` worker (singleton start/stop/tick mirroring `scheduler`/`knowledge_backfill`), over-budget skip. Registered in `app/main.py` lifespan.
- `app/api/digest_routes.py` — `POST/GET/PATCH/DELETE /api/digests`, `GET /api/digests/{id}` (config + latest run), `POST /api/digests/{id}/run` (synchronous, rate-limited), `GET /api/digests/{id}/runs`, `GET /api/topics/{id}/synthesis` (on-demand, library-wide topic synthesis). Wired in `app/api/__init__.py`.
- `app/config.py` — `digest_enabled` / `digest_interval` / `digest_max_claims` (all default-safe).
- `README.md` — Subscription Digests section with curl examples + endpoint list.
- `tests/` — `test_digest_synthesis.py` (9: markdown render, claim formatting/cap, degradation paths, structured + fenced-JSON success, malformed handling), `test_digest_store.py` (15: config CRUD, due-selection, runs), `test_digest_runner.py` (11: gather window/dedup/min-conf, run ok/empty/over-budget, worker tick + lifecycle), `test_digest_api.py` (11: CRUD, run-now, topic synthesis) — **46 new tests**, 512/512 suite green.

Deferred: email/Notion/Obsidian delivery (email has no infra; Notion/Obsidian land with **P21**), inbox UI, per-user source ranking, semantic cross-feed dedup, P12 pipeline profiles, and *scheduled* per-topic digests (topic synthesis is on-demand for now).

---

## P21: Vault & Note-App Export Channels

**Goal:** First-class output channels for Obsidian / Notion / Logseq — served both directly (write-to-vault) and through MCP (`export_to_vault` tool from P19). Templated markdown with frontmatter, clickable timestamps, claim cards, embedded highlights.

> The "very convenient YouTube → note" UX, but built on primitives instead of a one-off plugin.

> **Phase 1 status (✅ SHIPPED):** the markdown templater, Obsidian + Logseq + plain-markdown targets, the episode + highlights templates, the export API, and the MCP `export_to_vault` tool. Notion (external SDK + token), topic/digest note templates, per-subscription auto-export, and chapter ToC are deferred. See "P21 Phase 1 — what shipped" below.

### Tasks

- [x] Markdown templater (`app/delivery/note_exporter.py`):
  - [x] YAML frontmatter (title, source, date, speakers, topics, entities, tags) — YAML-safe
  - [x] Clickable timestamp links (`[12:42](https://youtu.be/...?t=762s)` for YouTube; plain otherwise)
  - [x] Collapsible transcript blocks (Obsidian `> [!note]-` callout; bullets elsewhere)
  - [x] Claim cards (one block per claim, with timestamp + confidence + evidence)
  - [x] Highlight blocks (pull quotes — the `highlights` template, confidence-ranked)
  - [ ] Embedded chapter ToC — renderer supports it; the route doesn't fetch chapters yet (would add a summarize LLM call)
- [~] Built-in templates:
  - [x] **Episode note** (full episode → one note)
  - [x] **Highlights only** (just key quotes + claims)
  - [~] **Topic note** (renderer `render_synthesis_note` exists; no endpoint yet — feed it P20 `/topics/{id}/synthesis`)
  - [~] **Daily digest** (renderer exists; no endpoint yet — feed it a P20 digest run)
- [~] Output targets:
  - [x] **Obsidian vault**: write `.md` into configured/given folder, `[[wikilinks]]` for entities
  - [ ] **Notion**: create page in configured database — deferred (needs `notion-client` + integration token)
  - [x] **Logseq**: outline-bullet markdown with `[[links]]` (full block-reference graph not attempted)
- [ ] Per-subscription auto-export setting — deferred
- [~] Vault config:
  - [x] Vault path — reuses the existing Obsidian vault setting (or per-request `vault_path`), scope-restricted to home/download dir
  - [ ] Database ID + integration token (Notion) — deferred
  - [ ] Graph path (Logseq) — uses the same vault-path mechanism
- [x] MCP integration: `export_to_vault(episode_id, target, template?, preview?)` calls this layer
- [x] API endpoints:
  - [x] `POST /api/jobs/{id}/export` with `target` + `template` (+ `write`/`vault_path`/`subfolder`/`min_confidence`)
  - [x] `GET /api/export-templates`

### P21 Phase 1 — what shipped

Generalized the one-off Obsidian transcript exporter into a multi-target note templater built on Sift's primitives (transcript + P18 knowledge). Deterministic rendering — no LLM — since the knowledge is already extracted.

- `app/delivery/note_exporter.py` — `NoteTarget` (obsidian/logseq/markdown) + `NoteTemplate` (episode/highlights/topic/digest) enums; `render_episode_note` (frontmatter + entity wikilinks + claim cards + clickable timestamps + collapsible transcript), `render_highlights_note` (confidence-ranked claims), `render_synthesis_note` (wraps a P20 topic/digest synthesis); `write_note_to_vault` — the secure filesystem writer (vault validation, `..`/absolute path-containment, filename sanitization, dedup) generalized from `ObsidianExporter`. YAML-safe frontmatter preserved (anti-injection).
- `app/api/export_routes.py` — `GET /api/export-templates`; `POST /api/jobs/{id}/export` gathers the episode (transcript segments + claims + resolved entities/topics) → renders → writes into the configured (or given) vault, or returns the rendered content when `write=false` (preview). Reuses the Obsidian vault-path scope check (home/download dir only). Topic/digest templates are rejected on the job route with a 400.
- `app/mcp_server/` — `export_to_vault(episode_id, target, template?, vault_path?, preview?)` tool + `SiftClient.export_job`. The P19 server is now 12 tools.
- `app/api/__init__.py` — export router wired.
- `README.md` — Vault Export section with curl + preview examples; MCP tool list updated.
- `tests/` — `test_note_exporter.py` (17: timestamp links, wikilinks per target, frontmatter safety, claim cards, highlights ranking, vault write + containment + dedup), `test_export_api.py` (9: templates list, write + preview, highlights, 404/400 guards, vault-scope rejection), +3 MCP export-tool tests — **29 new tests**, 541/541 suite green.

Deferred: **Notion** (external `notion-client` + integration token + database), topic/digest *export endpoints* (renderers exist, just need wiring to P20 synthesis), per-subscription auto-export, and chapter ToC fetching (avoids an extra summarize LLM call on export).

---

## Platform Adapter Ideas

- [x] **Desktop: Spotify podcast episodes via RSS resolution** (2026-07-12):
      Spotify streams are DRM-protected (yt-dlp refuses by design), and
      spotDL's YouTube-matching is wrong for podcasts (matched a random music
      track for a Web3 101 episode). Implemented the reliable pipeline in the
      Rust backend (`frontend/src-tauri/src/backend/spotify.rs`): Spotify
      oEmbed (episode title) → iTunes Search API (`entity=podcastEpisode`) →
      RSS enclosure MP3 streamed to disk. Music tracks/albums fail with a
      clear DRM message. Unit tests + live resolution test (`cargo test --
      --ignored`).
- [x] **Web backend: same RSS resolution in `SpotifyDownloader`** (2026-07-12):
      `/episode/` URLs resolve via oEmbed → iTunes search → SSRF-safe
      enclosure streaming (`safe_get`/`safe_stream`); spotDL kept for music
      only (clear install hint when missing); removed the dead yt-dlp
      fallback (always DRM-failed). Verified live: Web3 101 E82, 102 MB,
      correct title/show/duration. 10 tests (`tests/test_spotify_episode_rss.py`).

## P23: Subtitle-Grade Line Breaking (SRT/VTT Reflow) ✅ (shipped 2026-08-19)

**Goal:** Turn raw ASR segments into cues that are actually readable as subtitles — width-capped lines, ≤2 lines per cue, sane durations, breaks at punctuation and never mid-word, CJK-aware. One shared module behind *every* SRT/VTT path (local Whisper, remote whisper service, API models, fetched YouTube/Spotify captions, diarized output).

> Today `format_as_srt` emits one cue per raw segment. Whisper segments run 10–30 s and overflow any player; fetched YouTube auto-captions run 2–3 words per cue and flicker. Same bug in opposite directions — nobody is enforcing subtitle constraints.

> **Why it earns a day:** deterministic, no LLM cost, improves an output every user already touches, and it is the prerequisite for clip captioning (Social Media Clips) and any future editor-format export.

### The constraint model (decide this first — everything else follows)

Text is immutable and (by default) cues may not leave their source time envelope. Under those two locks, **some ASR output cannot satisfy every subtitle rule** — no algorithm can fix it, so the spec must not pretend otherwise.

The proof: a segment of 60 characters spanning 2.0 s reads at 30 cps. Split it anywhere and each half still reads at 30 cps. **Splitting cannot lower reading speed** — reading speed is a property of source density, not of segmentation. Likewise a 0.4 s `"Okay."` can never reach a 833 ms minimum while staying inside its own envelope.

So constraints are tiered, and `reflow()` neither throws nor silently cheats:

| Tier | Constraint | On conflict |
|---|---|---|
| **Hard** (invariant — never violated) | text preserved · timestamps monotonic · no overlap · `max_lines` · line capacity · no mid-word Latin split (except over-long tokens) · `max_duration` · speaker boundaries · cue within `[source_start, source_end + max_lead_out]` | restructure until satisfied |
| **Soft** (target — best effort, then reported) | reading speed · minimum duration · minimum gap | emit the best achievable cue **and** record a `SubtitleViolation` |

Hard constraints are always reachable: worst case you hard-cut on width and the cue is ugly but legal. Soft ones are not, so they get measured and logged instead of enforced.

### Locked design decisions (v1)

- **New module** `app/ingest/transcribe/subtitles.py` — pure functions, zero I/O, no transcriber import. Segments in, cues out. Keeps `transcriber.py` from growing and makes the whole thing table-testable.
- **Structural segmentation and timing are separate responsibilities.** `split_text()` decides where the breaks go; `allocate_times()` decides when cues start and end. The public entry point stays `split_segment(seg, style)`, but internally they must not be one function — Phase 2 (word timestamps) replaces *only* `allocate_times`, swapping width interpolation for word-boundary snapping, and leaves segmentation untouched.
- **Splitting runs before merging** so the merger never receives cues that already violate hard spatial or maximum-duration constraints. Minimum duration and reading speed are handled as best-effort timing concerns *after* structural segmentation — a post-split cue is spatially legal, not globally legal.
- **No word timestamps in v1.** `TranscriptionSegment` has no `words` field and `word_timestamps` defaults to `False` on every path. Split times are interpolated proportional to display width across the source span. Documented as approximate (±~150 ms); word-accurate timing is Phase 2.
- **Line capacity is measured per script profile, not by one universal `width` number.** East-asian width and Netflix's CJK character limits are different units and mixing them is off by 2×: `display_width("你好") == 4`, so `max_width = 16` would allow only 8 Chinese characters instead of 16.
- **The script profile is chosen from the candidate chunk's own text**, not from the job's declared language and not from the whole parent segment — a Chinese episode quoting English API terminology must be able to switch profile mid-segment.
- **Merging is triggered by undershoot, not by legality.** Merge only cues that are materially too short or too fragmentary; never merge simply because the merged result would also be legal. This is what makes reflow idempotent.
- **Text is never altered.** Reflow inserts line breaks and cue boundaries; whitespace normalization is the sole permitted mutation. The preservation invariant is checked against cue text *excluding* any rendered speaker prefix, which is presentation, not source.
- **Behaviour flag** `subtitle_reflow: bool = True` — on by default, because the current output *is* the bug, but one setting restores the raw-segment path for anyone diffing against old artifacts. Risk is low: no existing test asserts SRT text (only `test_mcp_server_tools.py:45` passes `output_format="srt"`), though the flip does change bytes in newly written artifacts.

### Pipeline

```text
normalize source segments      strip, drop empties, clamp end<=start, sort
        ↓
split_text                     hard spatial + max_duration only
        ↓
merge_fragments                undershoot-triggered, respects speaker + gap
        ↓
allocate_times                 width-proportional interpolation (Phase 2: word snapping)
        ↓
refine_timing                  best-effort extend into available slack
        ↓
validate                       assert hard invariants, collect soft violations
```

### Cue model — "parent segment" stops existing after a merge

A merged cue has two sources, so a single `parent` reference is wrong:

```python
@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    lines: tuple[str, ...]          # already broken; len() <= style.max_lines
    speaker: str | None
    source_segment_indices: tuple[int, ...]
    source_start: float             # min start of contributing segments
    source_end: float               # max end of contributing segments
```

Merging `seg[4] 1.0–1.8` with `seg[5] 1.9–2.7` gives `source_segment_indices=(4, 5)`, `source_start=1.0`, `source_end=2.7`. The envelope invariant then states precisely, and tests trivially:

```text
cue.start >= cue.source_start
cue.end   <= cue.source_end + style.max_lead_out
```

### Timing: one "extend into slack" operation, two purposes

Minimum duration and reading speed are both improved by the same move — giving a cue more time when time is available. So there is no `enforce_min_duration()`, only:

```python
desired_end = max(start + style.min_duration, start + needed_for_reading_speed)
actual_end  = min(
    desired_end,
    next_cue.start - style.min_gap,      # never overlap the neighbour
    cue.source_end + style.max_lead_out, # never outrun the audio
)
```

`cue.duration < style.min_duration` is an accepted outcome when no legal slack exists; it becomes a reported violation, not an exception.

**`max_lead_out` defaults to `0.0` in v1** (strict envelope), which keeps the invariant clean and the output faithful to the audio. Raising it is the single knob that makes minimum duration achievable far more often, and it is the natural follow-up once the strict version is shipped and trusted.

### Line measurement

```python
def line_capacity_ok(text: str, profile: ScriptProfile, style: SubtitleStyle) -> bool:
    if profile is ScriptProfile.CJK:
        return cjk_equivalent_chars(text) <= style.cjk_max_chars      # 16
    return display_width(text) <= style.latin_max_display_width       # 42
```

- `display_width` — `unicodedata.east_asian_width`, `W`/`F` = 2, else 1. Used for Latin-dominant and as the tiebreaker for mixed text.
- `cjk_equivalent_chars` — a CJK character costs 1 unit; run-length ASCII costs ~0.5–1 unit per character (calibrate against real 小宇宙 / 小红书 transcripts, then freeze the constant). Capacity is 16 CJK-equivalent characters.
- **Profile resolution, chicken-and-egg resolved:** seed capacity from the profile of the whole segment to generate break candidates, then re-measure each candidate chunk under *its own* profile and reject any that overflow. Two passes, terminating, and mixed zh/en lands on the right rule per chunk.

### Break scoring — additive, not a strict hierarchy

A pure priority ladder produces `"I went," / "to the store because I needed some milk."` — it takes the comma because a comma outranks whitespace, and wrecks the line balance. Score instead:

```text
score = punctuation_score
      + balance_score            # how close to an even two-line split
      + target_width_score       # prefer ~70–90% of capacity, not a full line
      - orphan_penalty           # a 1–2 char / 1-word fragment
      - bad_syntactic_break_penalty
```

Netflix's own template guidance asks that breaks respect syntactic units — don't separate an article from its noun, or a subject from its verb. v1 does not need a parser, only two word lists:

```python
AVOID_BREAK_AFTER   = {"a", "an", "the", "to", "of", "in", "for"}
PREFER_BREAK_BEFORE = {"but", "because", "although", "and", "so", "which"}
```

CJK gets the analogous treatment: penalize breaking before a trailing particle (的/了/嗎/呢) or between a number and its measure word.

### Hard rules and their explicit exceptions

- Never split inside a Latin word — **unless a single token itself exceeds line capacity** (URL, hash, UUID, unbroken identifier), in which case a hard width cut is permitted. Without this exception the `single_line` preset plus an 80-character URL has no legal output at all.
- Scripts with neither spaces nor CJK width (Thai, Lao) fall back to a hard width cut.
- Never merge across a speaker change (`seg.speaker`), across a silence gap > 1.5 s, or when the merged result would violate a hard constraint.
- **Speaker prefix is capacity, applied before reflow, never prepended after.** The writer must not append `"SPEAKER_01: "` to already-validated lines — that breaks the width invariant retroactively. Segmentation receives `first_line_capacity = capacity - display_width(prefix)` and full capacity for line two.
- Output invariants: cues sorted, non-overlapping, within the source envelope, concatenated text equal to input modulo whitespace (prefix excluded). No text lost, none duplicated.

### Presets

Defaults are **inspired primarily by Netflix timed-text constraints**, with product-specific presets — not a claim of conformance. General requirements (min 5/6 s, max 7 s, max 2 lines) and the Chinese guides (16 chars/line, adult ≤9 cps) are well-supported; the Latin reading-speed number is not one single Netflix value — the current English guides say 20 cps adult / 17 cps children, while the template guidance still shows 17 cps cases. So the Netflix-derived preset uses 20 and the more comfortable 17 lives under a differently-named preset rather than borrowing the brand for a number it doesn't specify.

| preset | latin width | cjk chars | max lines | latin cps | cjk cps | notes |
|---|---|---|---|---|---|---|
| `broadcast` | 42 | 16 | 2 | 20 | 9 | Netflix-derived defaults |
| `balanced` *(default)* | 42 | 16 | 2 | 17 | 9 | slower, more comfortable Latin pacing |
| `youtube` | 42 | 16 | 2 | 20 | 9 | aggressive fragment merging for auto-captions |
| `single_line` | 32 | 12 | 1 | 20 | 9 | burned-in / clip captions |

References: [General Requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617), [Chinese (Traditional)](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215994807), [English (USA)](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977), [Subtitle Templates](https://partnerhelp.netflixstudios.com/hc/en-us/articles/219375728).

### Tasks

- [x] `app/ingest/transcribe/subtitles.py`:
  - [x] `SubtitleStyle` dataclass + `broadcast` / `balanced` / `youtube` / `single_line` presets
  - [x] `SubtitleCue` (with `source_segment_indices` / `source_start` / `source_end`)
  - [x] `display_width`, `cjk_equivalent_chars`, `profile_for_text` (two-pass candidate resolution)
  - [x] `split_text(text, capacity, style)` — additive break scoring, long-token exception
  - [x] `merge_fragments(cues, style)` — undershoot-triggered only
  - [x] `allocate_times(...)` — width-proportional; the Phase 2 swap point
  - [x] `refine_timing(...)` — the single extend-into-slack operation
  - [x] `validate(cues, style)` → `list[SubtitleViolation]`; hard invariants assert, soft ones report
  - [x] `reflow(segments, style)` orchestrating the pipeline
  - [x] `format_srt(cues)` / `format_vtt(cues)` — the single canonical writer
- [x] Soft-violation reporting:
  - [x] `SubtitleViolation(cue_index, kind: Literal["reading_speed","min_duration","min_gap"], actual, limit)`
  - [x] `reflow` returns cues + violations; callers log a one-line summary (`"12 cues exceed reading speed"`), never fail the transcription
- [x] Wire the one writer everywhere:
  - [x] `transcriber.format_as_srt` / `format_as_vtt` / `format_as_srt_with_speakers` delegate to it (speaker becomes capacity, not a post-prepend)
  - [x] `app/api/transcript_fetch_routes.py` — delete the duplicated `_format_srt` / `_format_vtt` (a second, already-drifting implementation) and call the shared module, so fetched YouTube/Spotify cues get merged too
  - [x] `app/pipeline/workflow.py` + `app/api/transcription_routes.py` pass the configured style
- [x] `app/config.py`: `subtitle_reflow: bool = True`, `subtitle_style_preset: str = "balanced"`
- [x] Optional per-request `subtitle_style` on the transcription + transcript-fetch schemas
- [x] `tests/test_subtitles.py` (below)
- [x] README: short subsection under Transcription

### Test plan (`tests/test_subtitles.py`)

- [x] Table-driven splits: long Latin sentence · long CJK sentence · mixed zh/en switching profile mid-segment · punctuation vs balance tradeoff (the `"I went,"` case must **not** win) · never-mid-word · 80-char URL token takes the hard-cut exception · no-space script fallback
- [x] Line capacity: 16 Chinese characters fit one CJK line (regression against the `display_width`/`cjk_max_chars` 2× confusion)
- [x] Merge: 2-word YouTube auto-caption cues coalesce; two already-conformant cues 80 ms apart are **not** merged; no merge across speaker change or a 3 s gap
- [x] Timing: extension never overlaps the next cue; never exceeds `source_end + max_lead_out`; `max_duration` respected
- [x] **Impossible-input tests** — the ones that would have been bugs: 60 chars in 2.0 s emits legal cues plus a `reading_speed` violation and does not raise; `"Okay."` at 10.0–10.4 emits a 0.4 s cue plus a `min_duration` violation
- [x] **Invariant test across every fixture**: monotonic, non-overlapping, inside `[source_start, source_end + max_lead_out]`, text preserved exactly (whitespace-normalized, prefix excluded), `len(lines) <= max_lines`, every line within capacity
- [x] **Idempotency**: `reflow(reflow(x)) == reflow(x)` over the whole fixture set
- [x] Speaker prefix: first line honours reduced capacity; the writer prepends nothing
- [x] Degenerate input: empty text, `end <= start`, one segment spanning 300 s
- [x] Route level: SRT from `/api/transcript/fetch` and from a transcription job both come back reflowed; `subtitle_reflow=False` reproduces the old raw-segment output

### Phase 2 (not in this pass)

- [ ] Word-level timing: add `words` to `TranscriptionSegment`, plumb `word_timestamps=True` (local faster-whisper + `timestamp_granularities` on the API models), swap `allocate_times` to snap to real word boundaries — segmentation untouched
- [ ] Raise `max_lead_out` above 0 once strict mode is trusted; measure how many `min_duration` violations it clears
- [ ] Burned-in caption output for Social Media Clips (`single_line` + ASS/SSA)
- [ ] Scene-cut alignment — snap cue boundaries to camera cuts (needs the ffmpeg scene-detection work)
- [ ] Surface `SubtitleViolation` counts in the job artifact so an editor UI can highlight unfixable cues

### P23 — what shipped

`app/ingest/transcribe/subtitles.py` (pure, no I/O, no transcriber import) plus 69 tests in
`tests/test_subtitles.py`. Every SRT/VTT path now runs through one writer: the
duplicated `_format_srt` / `_format_vtt` in `transcript_fetch_routes.py` are
gone, and `transcriber.format_as_srt` / `format_as_vtt` /
`format_as_srt_with_speakers` delegate. `subtitle_reflow=False` still reaches
the verbatim one-cue-per-segment path, which is covered by a test.

Five places where writing the code changed the spec:

- **`_split_text` is two-phase, and that is load-bearing.** Chunk extent (how
  much text one cue holds) is decided by max-fill; line layout inside a chunk
  is decided by scoring. Running the scorer against a stream instead of a
  settled chunk breaks idempotency — the balance term looks at the tail, so
  re-flowing an already-flowed cue picked a *different* break than the first
  pass. Caught by the round-trip test on the `speakers` fixture.
- **Reading speed never shortens a cue.** The first `_refine_timing` used
  `start + max(min_duration, needed_for_speed)` as the end, which pulled a
  4.19 s cue back to 2.71 s and opened a 1.5 s dead gap in the middle of
  continuous speech. Reading speed is a *maximum*, so it only ever raises the
  extension target — never caps an already-long cue.
- **`max_duration` divides, it does not clamp.** Clamping a 9.2 s cue to 7 s
  drops the caption while the words are still being spoken. `_divide_over_long`
  re-splits at a legal break near the middle and allocates time proportionally,
  recursing until every cue fits; only indivisible text (a single token) falls
  back to clamping.
- **`min_gap` is actively created.** It was only ever an upper bound, so
  contiguous cues from one segment reported a violation on every cue.
  `_refine_timing` now pulls the end back to `next.start - min_gap` when the
  cue can afford it, and reports the gap only when pulling back would starve
  the cue.
- **`allocate_times` runs inside the split stage, not between split and
  merge.** The merger needs timings to test the silence gap and
  `max_duration`, so the order is: normalize → (split_text + allocate_times +
  divide) per segment → merge → refine → validate. The responsibilities stay
  separate — Phase 2 still swaps only `allocate_times`.

Wired: `subtitle_reflow` / `subtitle_style_preset` in `app/config.py`, an
optional `subtitle_style` on `TranscribeRequest` and `FetchTranscriptRequest`,
and `reflow` returning `ReflowResult(cues, violations)` so unmet soft targets
are logged (`"12 cues, unmet targets: 3 reading_speed"`) and never fail a
transcription.
