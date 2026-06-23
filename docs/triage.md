# Roadmap Triage — Open Items

Auto-extracted from [todo.md](todo.md) on 2026-06-23. **314 open items** across 27 sections. Checked items from the roadmap are omitted. Use this to prioritize; the source of truth remains todo.md.

## P0: Smart Metadata & Tagging ✅ COMPLETED › Tasks  (1)

- [ ] Add option to customize filename template (e.g., `{artist} - {title}`)

## P2: Browser Extension ✅ COMPLETED › Tasks  (2)

- [ ] Show notification/toast on successful queue
- [ ] Optional: Show download progress in extension popup

## P3: LLM-Powered Summarization ✅ COMPLETED › Tasks  (2)

- [ ] Cache summaries in database
- [ ] Export summary alongside transcript

## P4: Watch Folders & Subscriptions ✅ COMPLETED › Tasks  (1)

  - [ ] X user's Spaces (if API allows)

## P5: Audio Pre-processing (Voice Isolation) ✅ COMPLETED › Tasks  (2)

  - [ ] DeepFilterNet (ML-based noise reduction)
  - [ ] Silero VAD for voice activity detection

## P7: Sentiment & Vibe Analysis ✅ COMPLETED › Future Enhancements (moved to P13)  (3)

- [ ] Contradiction detection (cross-reference statements)
- [ ] Psychographic mapping (persuasion techniques, topic deflection)
- [ ] Cross-platform speaker tracking

## P8: Social Media Clip Generator ✅ COMPLETED › Tasks  (2)

  - [ ] Consider speaker energy/sentiment in selection (future enhancement)
  - [ ] Download clips as batch (future enhancement)

## P9: AI Translation & Dubbing (Translation ✅ COMPLETED) › Dubbing Tasks (Future)  (18)

- [ ] Text-to-Speech (TTS) integration:
  - [ ] Research TTS options:
    - [ ] Coqui TTS (open source)
    - [ ] OpenVoice (voice cloning)
    - [ ] ElevenLabs API (high quality)
    - [ ] Azure Speech Services
  - [ ] Voice cloning from original speaker
  - [ ] Maintain original pacing and timing
- [ ] Create dubbing service (`app/core/dubber.py`):
  - [ ] Sync translated speech with original timing
  - [ ] Handle speed adjustments for different language lengths
  - [ ] Mix dubbed audio with original background sounds (optional)
- [ ] Web UI dubbing features:
  - [ ] "Generate Dubbed Audio" button
  - [ ] Voice selection/cloning options
- [ ] Export options:
  - [ ] Dubbed audio file
  - [ ] Bilingual subtitle file

## Future Ideas (v1.x Backlog)  (5)

- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox) - In progress
- [ ] Podcast RSS feed generation from downloaded content
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts

## P10: Semantic Indexing & Vector Search › Tasks  (26)

- [ ] Research and select vector database:
  - [ ] ChromaDB (lightweight, Python-native, good for local/self-hosted)
  - [ ] LanceDB (embedded, serverless, good for single-user)
  - [ ] Qdrant (production-grade, supports filtering)
- [ ] Create vector indexing service (`app/core/vector_indexer.py`):
  - [ ] Generate embeddings for transcript segments (sentence-level or paragraph-level)
  - [ ] Support multiple embedding models:
    - [ ] `all-MiniLM-L6-v2` (fast, local, via sentence-transformers)
    - [ ] OpenAI `text-embedding-3-small` (high quality, API)
    - [ ] Ollama embedding models (local, privacy-first)
  - [ ] Store embeddings alongside job metadata (job_id, timestamps, speaker)
  - [ ] Auto-index on transcription completion (pipeline hook)
- [ ] Migrate from plain SQLite to SQLite + vector store:
  - [ ] Keep SQLite for structured data (jobs, settings, subscriptions)
  - [ ] Vector DB for semantic content search
  - [ ] Maintain referential links between the two
- [ ] Concept search API:
  - [ ] `POST /api/search` - Semantic search across all transcripts
  - [ ] `GET /api/search?q=...&job_id=...` - Search within a specific job
  - [ ] Return results with timestamps, speaker labels, relevance scores
  - [ ] Support filters: date range, platform, speaker, job
- [ ] Web UI search interface:
  - [ ] Global search bar in top nav
  - [ ] Results show matching segments with context, clickable timestamps
  - [ ] "Search within this transcript" option on job detail page
- [ ] Incremental re-indexing on transcript edits or new annotations

## P11: Ask Audio (RAG Chat Interface) › Tasks  (22)

- [ ] Create RAG service (`app/core/rag_engine.py`):
  - [ ] Query vector store for relevant transcript segments
  - [ ] Construct context window from top-K results
  - [ ] Send to LLM with grounding prompt (cite timestamps, avoid hallucination)
  - [ ] Return answer with source references (job, timestamp, speaker)
- [ ] Chat modes:
  - [ ] **Single Job**: Chat with one specific transcript
  - [ ] **Library-wide**: Ask questions across all indexed content
  - [ ] **Multi-Job**: Select 2+ jobs and chat across them (e.g., compare two podcast episodes)
- [ ] Web UI chat interface:
  - [ ] Chat panel on job detail page (slide-out or tab)
  - [ ] Global "Ask Audio" page for library-wide queries
  - [ ] Message history with source citations (clickable timestamps)
  - [ ] Suggested questions based on transcript content
- [ ] API endpoints:
  - [ ] `POST /api/ask` - Ask a question (library-wide)
  - [ ] `POST /jobs/{id}/ask` - Ask about a specific job
  - [ ] `GET /jobs/{id}/chat-history` - Retrieve past Q&A for a job
- [ ] Telegram bot integration:
  - [ ] Send a link → bot downloads & indexes → user asks questions → bot answers with timestamps
  - [ ] `/ask <question>` - Query the most recent download
- [ ] Conversation memory: follow-up questions understand prior context

## P12: Agentic Ingest Pipeline › Tasks  (23)

- [ ] Create pipeline orchestrator (`app/core/agentic_pipeline.py`):
  - [ ] Define pipeline stages as composable agents
  - [ ] Support configurable pipeline profiles (e.g., "Quick Summary", "Deep Research", "Full Analysis")
  - [ ] Parallel execution where possible (e.g., summarization + entity extraction run concurrently)
- [ ] Pipeline agents:
  - [ ] **Transcription Agent**: Download → Enhance → Transcribe → Diarize
  - [ ] **Summarization Agent**: Generate 3-bullet summary, chapter markers, key topics
  - [ ] **Entity Agent**: Extract mentioned people, companies, products, tickers; link to external data
  - [ ] **Indexing Agent**: Generate embeddings, store in vector DB, make searchable
  - [ ] **Notification Agent**: Send webhook/Telegram with summary + key findings
- [ ] Pipeline configuration:
  - [ ] Per-job pipeline override (API parameter)
  - [ ] Per-subscription default pipeline
  - [ ] Global default pipeline in settings
- [ ] Web UI pipeline status:
  - [ ] Multi-stage progress indicator (not just a download bar)
  - [ ] "Knowledge Canvas" view: shows extracted entities, summary, topics as the pipeline runs
  - [ ] Pipeline complete notification with quick-access to all outputs
- [ ] API endpoints:
  - [ ] `POST /api/ingest` - Submit URL with pipeline profile
  - [ ] `GET /jobs/{id}/pipeline` - Get pipeline status and partial results
  - [ ] `GET /api/pipelines` - List available pipeline profiles
  - [ ] `POST /api/pipelines` - Create custom pipeline profile

## P13: Psychographic Mapping & Contradiction Detection › Tasks  (20)

- [ ] Extend sentiment analyzer with LLM reasoning layer:
  - [ ] For each flagged segment, generate: *why* the tone shifted, what triggered it
  - [ ] Detect persuasion techniques (appeal to authority, FOMO, etc.)
  - [ ] Identify when speakers deflect questions or change topics abruptly
- [ ] Contradiction detection engine:
  - [ ] Build statement graph: extract key claims with timestamps and speaker attribution
  - [ ] LLM-powered cross-referencing: compare claims pairwise for logical consistency
  - [ ] Confidence scoring for each detected contradiction
  - [ ] Example: *"At 10:12, the speaker claimed they didn't own any $SOL, but at 32:40, they mentioned 'checking their Phantom wallet' during the dip."*
- [ ] Cross-platform social graph (for multi-source analysis):
  - [ ] When the same speaker appears across multiple downloads, track their statements over time
  - [ ] Detect evolving positions or flip-flops across episodes/spaces
- [ ] Web UI:
  - [ ] "Rhetoric Map" view: visual graph of claims, connections, and contradictions
  - [ ] Contradiction cards with side-by-side quotes and timestamps
  - [ ] Credibility score per speaker (based on consistency)
- [ ] API endpoints:
  - [ ] `POST /jobs/{id}/analyze-rhetoric` - Run deep rhetorical analysis
  - [ ] `GET /jobs/{id}/contradictions` - Get contradictions
  - [ ] `GET /jobs/{id}/claims` - Get extracted claims graph

## P14: Content Distiller (Multi-Source Briefing) › Tasks  (19)

- [ ] Create content distiller service (`app/core/distiller.py`):
  - [ ] Accept multiple job IDs or URLs as input
  - [ ] Cross-reference transcripts to find common themes, disagreements, unique insights
  - [ ] Generate unified output formats:
    - [ ] Written briefing (Markdown, 1-2 pages)
    - [ ] Audio briefing (TTS-generated 5-minute summary — future, depends on P9 dubbing)
    - [ ] Structured JSON (topics, per-source positions, consensus/disagreement)
- [ ] Distillation modes:
  - [ ] **Daily Digest**: Combine all downloads from today into one summary
  - [ ] **Topic Deep-Dive**: Filter across library for a specific topic, synthesize all mentions
  - [ ] **Debate Summary**: Compare two opposing viewpoints from different sources
- [ ] Web UI:
  - [ ] "Distill" button to select multiple jobs
  - [ ] Briefing viewer with per-source attribution
  - [ ] Schedule daily/weekly auto-distillation from subscriptions
- [ ] API endpoints:
  - [ ] `POST /api/distill` - Create a distillation from job IDs
  - [ ] `GET /api/distill/{id}` - Get distillation result
  - [ ] `POST /api/distill/schedule` - Schedule recurring distillation

## P15: Neural Audio Reconstruction › Tasks  (19)

- [ ] Research and integrate neural audio models:
  - [ ] **ElevenLabs Speech-to-Speech** (high quality, API-based)
  - [ ] **OpenVoice** (open source voice cloning)
  - [ ] **Resemble.AI** (voice cloning + enhancement)
  - [ ] **AudioSR** (audio super-resolution, open source)
- [ ] Create neural enhancement service (`app/core/neural_enhancer.py`):
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

## P16: Intelligent Webhooks & Agentic Notifications › Tasks  (17)

- [ ] Extend webhook payload with AI-generated content:
  - [ ] Include 3-bullet summary in webhook body
  - [ ] Include detected entities (people, companies, topics)
  - [ ] Include sentiment overview (overall tone, key heated moments)
  - [ ] Include contradiction alerts if any were detected
- [ ] Webhook templates:
  - [ ] **Minimal**: Status + title (current behavior)
  - [ ] **Summary**: Status + AI summary + key topics
  - [ ] **Full Intelligence**: Status + summary + entities + sentiment + contradictions
  - [ ] Custom templates with variable substitution
- [ ] Smart notification routing:
  - [ ] Route different types of content to different webhooks/channels
  - [ ] Example: Financial content → Slack #trading, Tech discussions → Slack #engineering
  - [ ] Urgency detection: flag time-sensitive information for immediate notification
- [ ] API:
  - [ ] `PUT /api/webhooks/{id}` - Update webhook with template selection
  - [ ] `GET /api/webhooks/templates` - List available templates

## P17: Structured Data Extraction › Tasks  (22)

- [ ] Create structured extraction service (`app/core/extractor.py`):
  - [ ] LLM-powered extraction from transcript text
  - [ ] Configurable extraction schemas (user-defined or preset)
- [ ] Built-in extraction presets:
  - [ ] **Meeting Notes**: Attendees, agenda items, decisions, action items, deadlines
  - [ ] **Interview**: Questions asked, answers given, key quotes
  - [ ] **Tutorial**: Steps, tools mentioned, prerequisites, links
  - [ ] **News/Analysis**: Claims, evidence, sources cited, predictions
  - [ ] **Product Review**: Product name, pros, cons, rating, comparisons
- [ ] Output formats:
  - [ ] JSON (structured, machine-readable)
  - [ ] Markdown (human-readable, Obsidian/Notion-ready)
  - [ ] CSV (for spreadsheet import)
  - [ ] Notion page (via API integration)
- [ ] Web UI:
  - [ ] "Extract" button with preset/schema selector
  - [ ] Extracted data viewer with editable fields
  - [ ] Export to various formats
- [ ] API endpoints:
  - [ ] `POST /jobs/{id}/extract` - Extract structured data
  - [ ] `GET /jobs/{id}/extracted` - Get extraction results
  - [ ] `POST /api/extraction-schemas` - Define custom extraction schema

## P18: AI-Friendly Knowledge Schema › Schema (Pydantic models)  (6)

- [ ] **Claim** — `claim_id` (stable hash for cross-job dedup), `episode_id`, `text`, `speaker`, `timestamp_start/end`, `claim_type` (fact / opinion / prediction / question / recommendation), `confidence`, `evidence_excerpt`, `entity_ids[]`, `topic_ids[]`, `extraction_version`, `schema_version`, `source_url`
- [ ] **Entity** — `entity_id` (stable short-hash PK, e.g. `ent_8f3a91c2`), `slug` (human-readable label, e.g. `person:vitalik-buterin`, UNIQUE, mutable/regenerable), `name`, `entity_type` (person / company / ticker / project / product / place), `aliases[]`, `confidence` (LLM self-reported), `created_at`. Embedding lives in the generic `embeddings` table, **not** inline. Claims and mentions reference `entity_id`, never `slug` — merges become pointer updates, not rewrites.
- [ ] **EntityMention** — `entity_id`, `episode_id`, `claim_id` (nullable — entities can exist without a claim reference), `chunk_id`, `raw_text` (surface form as the speaker said it), `start_char`/`end_char` (optional offsets into chunk text for UI highlighting), `timestamp`, `speaker`
- [ ] **Topic** — `topic_id`, `name`, `segments[]` (episode_id + time range), `sentiment_summary`, `frequency_over_time`
- [ ] **Prediction** (extends Claim) — `target_horizon`, `conditions`, `falsifiable_by`, `resolution` (pending / true / false / unresolvable), `resolved_at`
- [ ] **Embedding** (generic, separate table) — `object_type` (episode / segment / claim / entity), `object_id`, `model`, `dim`, `vector_blob` (numpy float32 bytes), `norm` (cached for cosine speed)

## P18: AI-Friendly Knowledge Schema › Tasks  (42)

- [ ] Schema spec doc (`docs/knowledge-schema.md`) with explicit `schema_version` and `extraction_version` policy + re-extraction rules
- [ ] Task preset registry (`app/core/llm_presets.py`):
  - [ ] Map `extract | summarize | synthesize | chat` → provider+model
  - [ ] Default presets in code, overridable via `ai_settings` table (new `task_presets` JSON column)
  - [ ] `get_provider_for_task(task)` helper used by extractor / summarizer / RAG / digest
- [ ] Knowledge extractor service (`app/core/knowledge_extractor.py`):
  - [ ] LLM-powered extraction with structured output (function calling / JSON mode via litellm)
  - [ ] Per-segment processing (~3000 tokens, 200-token overlap) with episode metadata as context
  - [ ] Pulls model from `get_provider_for_task("extract")`, not directly from AI Settings
  - [ ] One unified prompt per chunk → `{claims, entities, topics, predictions}`
  - [ ] Schema validation on every LLM output (malformed → quarantine table, never crash pipeline)
- [ ] Embedding store (`app/core/embedding_store.py`):
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

## P19: Sift MCP Server (Capability Surface) › Tool surface (stable JSON Schema per tool)  (10)

- [ ] **Q&A** (deferred — depends on P10/P11)
  - [ ] `ask_episode(episode_id, question)` — RAG against single episode (depends on P11)
  - [ ] `ask_at_timestamp(episode_id, time_range, question)` — scoped Q&A
  - [ ] `search_library(query, filters?)` — semantic search across all episodes (depends on P10)
- [ ] **Cross-episode synthesis** (deferred — depends on P13/P20)
  - [ ] `compare_episodes(episode_ids[], topic?)` — agreements / disagreements
  - [ ] `find_contradictions(speaker?, topic?, timeframe?)` — surface inconsistencies
  - [ ] `summarize_trend(topic, last_n_days)` — narrative evolution over time
- [ ] **Export** (deferred — depends on P21)
  - [ ] `export_to_vault(episode_id, target, template?)` — Obsidian / Notion / Logseq (depends on P21)

## P19: Sift MCP Server (Capability Surface) › Tasks  (8)

  - [ ] HTTP transport (remote agents, Cursor) — `run_streamable_http_async` exists in the SDK; stdio-only for now
  - [ ] Streaming for long-running tools (`ingest_url`, `ask_episode`) — deferred
- [ ] Reference agent skills (shipped in repo):
  - [ ] **Episode → Obsidian note** (claims + highlights + clickable timestamps)
  - [ ] **Weekly recap** (cross-source synthesis from subscriptions)
  - [ ] **Topic research** (search → claims → contradictions → brief)
  - [ ] **Language learning** (transcript + translation + key vocabulary)
- [ ] Distribution:

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis) › Phase 1 — Subscription-driven brief  (2)

- [ ] Per-subscription pipeline profile (Quick / Deep / Full — reuses P12) — deferred
- [ ] Daily digest **email** per subscription set — deferred (no SMTP infra); webhook channel shipped instead

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis) › Phase 2 — Topic synthesis  (1)

- [ ] Topic-scoped *scheduled* digest (per topic, not per feed) — deferred (on-demand only for now)

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis) › Phase 3 — Reusable intelligence layer  (8)

- [ ] All extracted knowledge written to KB (queryable via P19 MCP tools)
- [ ] Output channels:
  - [ ] Email digest (HTML)
  - [ ] Telegram digest (rich format with episode links)
  - [ ] Webhook JSON (consumes P16 intelligent webhooks)
  - [ ] Notion database row (one row per claim or per episode)
  - [ ] Markdown export → Obsidian vault folder (consumes P21)
- [ ] Inbox UI: pin / mute / follow topics, mark-read, archive

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis) › Cross-cutting  (1)

- [ ] Source ranking (per-user trust weights) — deferred

## P21: Vault & Note-App Export Channels › Tasks  (25)

- [ ] Markdown templater (`app/core/note_exporter.py`):
  - [ ] YAML frontmatter (title, source_url, date, speakers, topics, tags)
  - [ ] Clickable timestamp links (`[12:42](https://youtu.be/...?t=762)`)
  - [ ] Collapsible transcript blocks
  - [ ] Claim cards (one block per extracted claim, with timestamp + confidence)
  - [ ] Highlight blocks (pull quotes)
  - [ ] Embedded chapter ToC
- [ ] Built-in templates:
  - [ ] **Episode note** (full episode → one note)
  - [ ] **Highlights only** (just key quotes + claims)
  - [ ] **Topic note** (cross-episode synthesis on a topic)
  - [ ] **Daily digest** (one note per day, all subscriptions)
- [ ] Output targets:
  - [ ] **Obsidian vault**: write `.md` into configured folder, use `[[wikilinks]]` for normalized entities
  - [ ] **Notion**: create page in configured database, claims as database rows
  - [ ] **Logseq**: journal-friendly format with block references
- [ ] Per-subscription auto-export setting
- [ ] Vault config:
  - [ ] Vault path (Obsidian)
  - [ ] Database ID + integration token (Notion)
  - [ ] Graph path (Logseq)
- [ ] MCP integration: `export_to_vault(episode_id, target, template?)` calls this layer
- [ ] API endpoints:
  - [ ] `POST /jobs/{id}/export` with `target` and `template` params
  - [ ] `GET /api/export-templates`

## v2.0 Backlog (Future Ideas)  (7)

- [ ] **Cross-Platform Social Graph**: Track speakers across downloads, build profiles of their positions over time
- [ ] **Visual Trend Extraction**: For video from 小红书/Instagram, use vision AI to extract aesthetic trends, product placements, visual themes
- [ ] **AI-Generated Podcast Feed**: Auto-create a personal podcast RSS feed from daily distillations
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts (speak a query, find the answer)
- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox)
