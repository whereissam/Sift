# Sift Feature Roadmap

## Vision

Sift is evolving from a media utility into an **AI-First Knowledge Extraction Platform**. The user's true intent isn't to own an MP3 — it's to get the *insight* trapped inside that MP3. Downloading is a legacy middle step that becomes invisible as the platform matures.

## Priority Matrix

### v1.5 — Desktop App (Complete)

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| Tauri v2 Desktop Shell | Medium | Very High | P0 ✅ |
| Rust Backend (axum) | High | Very High | P1 ✅ |
| Parallel HLS Downloads (16x) | Low | High | P2 ✅ |
| SQLite Job Persistence (Rust) | Medium | High | P3 ✅ |
| Platform Detection (10 platforms) | Low | High | P4 ✅ |

### v1.x — Utility Foundation (Complete)

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| Metadata Tagging | Low | High | P0 ✅ |
| Speaker Diarization | High | Very High | P1 ✅ |
| Browser Extension | Medium | High | P2 ✅ |
| LLM Summarization | Medium | Medium | P3 ✅ |
| Watch Folders & Subscriptions | Medium | High | P4 ✅ |
| Audio Pre-processing | Medium | Medium | P5 ✅ |
| AI Provider Manager | Medium | High | P6 ✅ |
| Sentiment & Vibe Analysis | Medium | Medium | P7 ✅ |
| Social Media Clip Generator | High | High | P8 ✅ |
| AI Translation & Dubbing | Very High | Very High | P9 (Translation ✅) |

### v1.x — Multi-Engine Transcription (Complete)

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| Multi-Engine Architecture | Medium | High | P9.5 ✅ |
| SenseVoice (FunASR) Backend | Medium | High | P9.5 ✅ |
| Apple Speech (macOS) Backend | Low | Medium | P9.5 ✅ |
| Cloud API Backend (OpenAI) | Low | Medium | P9.5 ✅ |
| Engine Auto-Selection | Low | High | P9.5 ✅ |
| Frontend Engine Selector | Low | Medium | P9.5 ✅ |

### v2.0 — AI-Native Intelligence (Next)

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| Semantic Indexing & Vector Search | High | Very High | P10 |
| Ask Audio (RAG Chat Interface) | High | Very High | P11 |
| Agentic Ingest Pipeline | Medium | Very High | P12 |
| Psychographic Mapping & Contradiction Detection | Medium | High | P13 |
| Content Distiller (Multi-Source Briefing) | Medium | High | P14 |
| Neural Audio Reconstruction | Very High | Medium | P15 |
| Intelligent Webhooks & Agentic Notifications | Low | High | P16 |
| Structured Data Extraction | Medium | High | P17 |

---

## P0: Smart Metadata & Tagging ✅ COMPLETED

**Goal:** Automatically fetch and embed ID3 tags (Title, Artist, Album Art, Year) for all platforms.

### Tasks

- [x] Add `mutagen` dependency for ID3 tag manipulation
- [x] Create metadata service (`app/core/metadata_tagger.py`)
- [x] Platform-specific metadata extractors:
  - [x] X Spaces: Scrape Space title, Host handle as "Artist"
  - [x] YouTube: Extract title, channel name, thumbnail
  - [x] Apple Podcasts: Pull from RSS feed (title, description, artwork)
  - [x] Spotify: Use spotDL metadata (already has some)
  - [x] 小宇宙: Extract episode metadata from API
- [x] Embed metadata into downloaded files:
  - [x] Title
  - [x] Artist/Author
  - [x] Album (show name for podcasts)
  - [x] Album Art (thumbnail/cover)
  - [x] Year/Date
  - [x] Description in "Comments" tag
- [ ] Add option to customize filename template (e.g., `{artist} - {title}`)
- [x] Add `embed_metadata` option in API (default: true)

---

## P1: Speaker Diarization (Who Spoke When) ✅ COMPLETED

**Goal:** Identify different speakers in transcriptions, especially for X Spaces and Podcasts.

See [diarization-setup.md](./diarization-setup.md) for setup instructions.

### Tasks

- [x] Research and select diarization library:
  - [x] Selected: `pyannote-audio` (most accurate, requires HuggingFace token)
- [x] Add optional dependency group `[diarize]`
- [x] Create diarization service (`app/core/diarizer.py`)
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

## P2: Browser Extension ✅ COMPLETED

**Goal:** One-click download from browser to Sift Web UI.

### Tasks

- [x] Create Chrome extension manifest v3
- [x] Create Firefox extension manifest
- [x] Extension features:
  - [x] Detect supported URLs (X Spaces, YouTube, etc.)
  - [x] Show Sift icon when on supported page
  - [x] Click to send URL to Sift API
  - [x] Configuration page for Sift server URL
- [x] Create simple bookmarklet alternative:
  ```javascript
  javascript:(function(){var s='http://localhost:8000';window.open(s+'/api/add?url='+encodeURIComponent(window.location.href)+'&action=transcribe')})()
  ```
- [x] Add `/add` endpoint to API for browser integration
- [ ] Show notification/toast on successful queue
- [ ] Optional: Show download progress in extension popup

---

## P3: LLM-Powered Summarization ✅ COMPLETED

**Goal:** Generate summaries and chapters for long transcriptions.

### Tasks

- [x] Create summarization service (`app/core/summarizer.py`)
- [x] Support multiple LLM backends:
  - [x] Ollama (local, free)
  - [x] OpenAI API
  - [x] Anthropic API
  - [x] OpenAI-compatible endpoints (LM Studio, etc.)
- [x] Add API key configuration in settings
- [x] Summarization types:
  - [x] Bullet-point summary
  - [x] Chapter markers with timestamps
  - [x] Key topics/themes extraction
  - [x] Action items (for meeting-style content)
  - [x] Full comprehensive summary
- [x] Add "Summarize" button in Web UI transcription view
- [x] Chunking strategy for long transcripts (context window limits)
- [ ] Cache summaries in database
- [ ] Export summary alongside transcript

---

## P4: Watch Folders & Subscriptions ✅ COMPLETED

**Goal:** Automated archiving of RSS feeds and channels.

### Tasks

- [x] Create subscription model in database
- [x] Subscription types:
  - [x] RSS feed URL
  - [x] YouTube channel/playlist
  - [ ] X user's Spaces (if API allows)
- [x] Background worker for checking subscriptions:
  - [x] Configurable check interval (default: 1 hour)
  - [x] Track last checked timestamp
  - [x] Track downloaded episode IDs to avoid duplicates
- [x] Subscription management API endpoints:
  - [x] `POST /subscriptions` - Add subscription
  - [x] `GET /subscriptions` - List subscriptions
  - [x] `DELETE /subscriptions/{id}` - Remove subscription
  - [x] `POST /subscriptions/{id}/check` - Force check now
- [x] Web UI subscription management page
- [x] Auto-transcribe option per subscription
- [x] Download limit (e.g., keep last N episodes)
- [x] Notification on new downloads (webhook/email)

---

## P5: Audio Pre-processing (Voice Isolation) ✅ COMPLETED

**Goal:** Improve transcription accuracy for noisy recordings.

### Tasks

- [x] Research audio enhancement options:
  - [ ] DeepFilterNet (ML-based noise reduction)
  - [x] FFmpeg filters (high-pass, low-pass, noise gate)
  - [ ] Silero VAD for voice activity detection
- [x] Create audio enhancement service (`app/core/enhancer.py`)
- [x] Enhancement presets:
  - [x] Light (basic noise reduction)
  - [x] Medium (voice isolation)
  - [x] Heavy (aggressive filtering for very noisy audio)
- [x] Add "Enhance Audio" toggle in Web UI
- [x] Option to keep both original and enhanced versions
- [x] Apply enhancement before transcription (optional pipeline step)
- [x] Preview enhancement before full processing

---

## P6: AI Provider Manager (LiteLLM Integration) ✅ COMPLETED

**Goal:** Create an AI-agnostic gateway supporting multiple LLM providers through a unified interface.

### Tasks

- [x] Add `litellm` dependency for universal LLM API translation
- [x] Update `app/core/summarizer.py` to use LiteLLM:
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

## P7: Sentiment & Vibe Analysis ✅ COMPLETED

**Goal:** Generate an emotional intelligence layer for audio content — detect heated moments, sentiment shifts, and emotional arcs.

### Tasks

- [x] Create sentiment analysis service (`app/core/sentiment_analyzer.py`)
- [x] LLM-based sentiment analysis (via configured AI provider)
- [x] Sentiment tagging types:
  - [x] Polarity (positive/negative/neutral)
  - [x] Energy level (0-100)
  - [x] Heat score for identifying intense moments
  - [x] Dominant emotions per segment
- [x] Analyze transcript segments:
  - [x] Process segments with configurable time window aggregation
  - [x] Identify heated moments and debates
  - [x] Generate emotional arc summary with peak moments
- [x] Web UI visualization:
  - [x] Sentiment section in transcription results (`SentimentSection.tsx`, `SentimentTimeline.tsx`)
  - [x] Emotional timeline/heatmap
  - [x] Heated moments display
- [x] API endpoints:
  - [x] `POST /jobs/{id}/analyze-sentiment` - Run sentiment analysis
  - [x] `GET /jobs/{id}/sentiment` - Get cached sentiment results
  - [x] `GET /jobs/{id}/sentiment/timeline` - Emotional heatmap timeline
  - [x] `GET /jobs/{id}/sentiment/heated-moments` - Top intense moments

### Future Enhancements (moved to P13)
- [ ] Contradiction detection (cross-reference statements)
- [ ] Psychographic mapping (persuasion techniques, topic deflection)
- [ ] Cross-platform speaker tracking

---

## P8: Social Media Clip Generator ✅ COMPLETED

**Goal:** Automatically identify viral-worthy moments and generate clips for social media.

### Tasks

- [x] Create clip generator service (`app/core/clip_generator.py`)
- [x] AI-powered clip identification:
  - [x] Feed transcript to LLM with prompt for finding hook-worthy segments
  - [x] Identify most controversial/insightful 15-60 second segments
  - [x] Score clips by "viral potential" (0.0-1.0)
  - [ ] Consider speaker energy/sentiment in selection (future enhancement)
- [x] Clip metadata generation:
  - [x] Auto-generate catchy captions
  - [x] Suggest relevant hashtags (5-10 per clip)
  - [x] Create hook text for the first 3 seconds
- [x] Clip extraction:
  - [x] Extract audio segment with FFmpeg (`app/core/clip_exporter.py`)
  - [x] Generate timestamps for video editing (start_time, end_time in response)
  - [x] Support multiple aspect ratios (platform-specific via compatible_platforms)
- [x] Web UI "Generate Viral Clips" feature:
  - [x] Button in transcription view (`ClipsSection.tsx`)
  - [x] Preview suggested clips with timestamps
  - [x] Edit/adjust clip boundaries (API: `PATCH /jobs/{id}/clips/{clip_id}`)
  - [x] Download clips individually
  - [ ] Download clips as batch (future enhancement)
  - [x] Copy caption/hashtags to clipboard
- [x] API endpoints:
  - [x] `POST /jobs/{id}/clips` - Generate clip suggestions
  - [x] `GET /jobs/{id}/clips` - List generated clips
  - [x] `POST /jobs/{id}/clips/{clip_id}/export` - Export specific clip
- [x] Platform-specific formatting:
  - [x] TikTok (9:16, max 3 min / 180s)
  - [x] Instagram Reels (9:16, max 90 sec)
  - [x] YouTube Shorts (9:16, max 60 sec)
  - [x] Twitter/X (16:9, max 2:20 / 140s)

---

## P9: AI Translation & Dubbing (Translation ✅ COMPLETED)

**Goal:** Translate transcripts and re-voice content in different languages while preserving speaker characteristics.

### Translation Tasks ✅

- [x] Create translation service (`app/core/translator.py`)
- [x] Translation pipeline using **TranslateGemma** (via Ollama):
  - [x] Use existing transcription as source
  - [x] High-quality translation (55 languages supported)
  - [x] Preserve original text for comparison
- [x] Supported languages (55 total):
  - [x] Chinese (Simplified/Traditional) ↔ English
  - [x] Japanese ↔ English
  - [x] Korean ↔ English
  - [x] Spanish, French, German, Italian, Portuguese
  - [x] Arabic, Hindi, Thai, Vietnamese, Indonesian
  - [x] And 40+ more languages
- [x] Web UI translation features:
  - [x] "Translate" section in transcription result view
  - [x] Searchable language selector dropdown (Radix UI)
  - [x] Copy translated text button
  - [x] Translation Settings page (model size, default language)
- [x] API endpoints:
  - [x] `POST /api/translate` - Translate text
  - [x] `POST /api/translate/job` - Translate a transcription job
  - [x] `GET /api/translate/languages` - List supported languages
  - [x] `GET /api/translate/available` - Check TranslateGemma status
- [x] Language selector in transcription form (specify audio language for better accuracy)

### Dubbing Tasks (Future)

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

---

## Future Ideas (v1.x Backlog)

- [x] Batch download from URL list/file ✅
- [x] Download queue priority levels ✅
- [x] Scheduled downloads (download at specific time) ✅
- [x] Storage management (auto-cleanup old files) ✅
- [ ] Multi-language UI
- [x] Mobile-responsive Web UI improvements
- [x] Docker Compose with GPU support for transcription ✅
- [x] Webhook notifications for job completion ✅
- [ ] Export to cloud storage (S3, Google Drive, Dropbox) - In progress
- [x] Collaborative annotations on transcripts ✅
- [x] Real-time transcription (live audio streams) ✅
- [ ] Podcast RSS feed generation from downloaded content
- [ ] Audio fingerprinting for duplicate detection
- [x] Integration with note-taking apps (Obsidian ✅, Notion - future)
- [ ] Voice search within transcripts
- [x] Telegram bot full upgrade (all 10 platforms, format selection, transcribe, webhook mode) ✅

---

# v2.0: AI-Native Intelligence Platform

> The shift: from "Where should I save this file?" to "What do you want to learn from this URL?"

---

## P10: Semantic Indexing & Vector Search

**Goal:** Replace keyword search with concept-level retrieval. Turn every transcript into a searchable vector embedding so users can query their entire library by *meaning*.

### Tasks

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

**Example query:** *"Find the part where someone explains the difference between L2s and sidechains"* → Returns the exact 30-second clip from a 3-hour podcast downloaded two months ago.

---

## P11: Ask Audio (RAG Chat Interface)

**Goal:** Let users chat with their downloads. Ask questions, get answers grounded in transcript content with source timestamps.

### Tasks

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

**Example:** User sends a YouTube link, then asks *"What did they say about the Fed rate hike?"* → Bot answers with the exact quote and timestamp.

---

## P12: Agentic Ingest Pipeline

**Goal:** When a user pastes a URL, Sift doesn't just download — it triggers an autonomous multi-agent research loop that extracts maximum value.

### Tasks

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

---

## P13: Psychographic Mapping & Contradiction Detection

**Goal:** Replace simple sentiment analysis with deep rhetorical intelligence. Understand not just *what* was said but the underlying reasoning, persuasion techniques, and logical consistency.

### Tasks

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

---

## P14: Content Distiller (Multi-Source Briefing)

**Goal:** Feed multiple URLs and get a single synthesized output — a "Daily Briefing" that combines insights from all sources.

### Tasks

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

**Example:** Subscribe to 5 crypto podcasts. Every morning, get a single 5-minute briefing: *"3 of 5 hosts are bullish on ETH, 2 flagged regulatory concerns, 1 mentioned a potential airdrop for Project X."*

---

## P15: Neural Audio Reconstruction

**Goal:** Go beyond FFmpeg filters — use AI to re-synthesize low-quality audio into studio-grade clarity.

### Tasks

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

---

## P16: Intelligent Webhooks & Agentic Notifications

**Goal:** Webhooks should deliver *intelligence*, not just status updates. Instead of "Job Complete", send: *"Job Complete. This video contains 3 actionable investment tips and 1 logical fallacy. See attached summary."*

### Tasks

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

---

## P17: Structured Data Extraction

**Goal:** Transcription output shouldn't just be text — it should be structured, machine-readable data ready for downstream consumption.

### Tasks

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

---

## v2.0 Backlog (Future Ideas)

- [ ] **Cross-Platform Social Graph**: Track speakers across downloads, build profiles of their positions over time
- [ ] **Visual Trend Extraction**: For video from 小红书/Instagram, use vision AI to extract aesthetic trends, product placements, visual themes
- [ ] **AI-Generated Podcast Feed**: Auto-create a personal podcast RSS feed from daily distillations
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts (speak a query, find the answer)
- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox)
- [ ] Notion integration for structured data export
- [ ] MCP server for LLM agent integration (expose Sift as a tool for AI agents)
