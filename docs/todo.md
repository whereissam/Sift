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

### v2.5 — Capability Surface & Knowledge Pipeline (Planned)

> The shift: from "an app that ships connectors" to "a capability surface". Obsidian, Notion, Logseq become *agent-side targets*, not Sift-side integrations. Single-episode summary becomes a *feature*; continuous cross-source knowledge monitoring becomes the *product*.

| Feature | Difficulty | Impact | Priority |
|---------|------------|--------|----------|
| AI-Friendly Knowledge Schema (Claims, Entities, Predictions) | Medium | Very High | P18 |
| Sift MCP Server (Capability Surface) | Medium | Very High | P19 |
| Subscription Digest Pipeline (Cross-Episode Synthesis) | High | Very High | P20 |
| Vault & Note-App Export Channels (Obsidian / Notion / Logseq) | Low | High | P21 |

**Dependency order:** P18 is the substrate (canonical schema). P19 (MCP) and P20 (Digest) both read from it. P21 (Vault Export) consumes from P19 and P20.

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

### Phased rollout (within P18)

1. **Phase A — Claims-only MVP** ✅ **SHIPPED**: schema + extractor + `claims` / `embeddings` / `extraction_failures` tables + task preset registry + `POST /jobs/{id}/extract-knowledge` + `GET /jobs/{id}/knowledge` + `GET /api/claims`. New jobs only (manual trigger; backfill in Phase C). 45 new tests, all passing.
2. **Phase B — Entities + canonicalization** ✅ **SHIPPED**: filled `embedding_store.embed()` (sentence-transformers lazy-loaded, module cache, `to_thread` batch), added `entities` + `entity_mentions` tables (dual-ID: `ent_<hash>` PK + UNIQUE slug), shipped `entity_canonicalizer.py` (normalize → cache → cosine ≥0.85 reuse → else mint with slug-collision sequence suffix), extended `LLM_RESPONSE_SCHEMA` to `{claims, entities}` with per-claim `entity_refs`, shipped `GET /api/entities*`. Entities + mentions ride in the same tx as claims. **56 new tests**, 154/154 total green.
3. **Phase C — Topics + Predictions + backfill worker** (split into C.1 / C.2 / C.3 by change kind — classification / schema semantics / control-plane):
   - **C.1 — Topics** ✅ **SHIPPED**: second-pass aggregation over already-extracted claims, `topics` + `claim_topics` tables (join is source of truth; `Claim.topic_ids` JSON kept as denormalized cache for fast per-claim render), `topic_canonicalizer` (reuses Phase B embedding infra, threshold 0.90, lexical-normalize layer with ticker expansion + conservative plural collapse), `GET /api/topics*` endpoints. Gracefully degrades when `summarize` provider missing, `claim_count < 3`, or aggregator throws — topic pass never blocks claims. **54 new tests**, 208/208 suite green.
   - **C.2 — Predictions** (**NEXT**): dedicated `predictions` table, FK `claim_id UNIQUE`, prediction lifecycle columns (`target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolved_at`), prediction-specific API + prompts. Separate table (not nullable columns on claims) because this is the start of a prediction lifecycle, not a flag — future expansion (multiple resolution events, resolution evidence, confidence recalibration, tracking dashboards) lands cleanly on a dedicated row.
   - **C.3 — Backfill worker + cost guardrails**: both-trigger backfill (background worker + route-triggered on-demand), idempotent enqueue with status machine `pending | running | ready | failed` + `knowledge_version` + `locked_at`/`worker_id`, global default daily budget + per-subscription override + priority tier + model-downgrade policy.
4. **Phase D — Pipeline auto-run + tests + docs** (~1 day): hook into `workflow.py`, write `docs/knowledge-schema.md`, raise coverage to 80%+.

**Why split Phase C into three passes**: topics = classification layer, predictions = schema semantics (changes claim wire format), backfill = operational control plane. Bundling them produces a release where quality drops can't be attributed to the right surface (prompts vs schema vs orchestration). Each pass has its own tx/schema/test churn and should land on its own.

### Phase A — what shipped

- `app/core/knowledge_schema.py` — `Claim`, `ClaimDraft`, `ExtractionRunResult`, `ChunkFailure`, `compute_claim_id`, `LLM_RESPONSE_SCHEMA`, `ClaimType` enum, `SCHEMA_VERSION`/`EXTRACTION_VERSION` constants
- `app/core/llm_presets.py` — `TaskType`, `get_provider_for_task` (DB → env → default-preset → user-provider resolution chain), `_DEFAULT_PRESETS` (extract/summarize/synthesize/chat); resolves overrides from new `ai_settings.task_presets` JSON column with `_encrypt_secret`/`_decrypt_secret` round-trip on nested `api_key`s
- `app/core/knowledge_extractor.py` — segment chunking (~3000 tokens, 200 overlap), JSON-mode prompting, defensive parsing (markdown fences + prose-wrapped JSON), per-chunk failure isolation with `raw_output` capture, claim_id-based dedup across overlapping chunks, storage floor 0.1; `success=False` when every chunk fails so callers don't wipe prior data
- `app/core/embedding_store.py` — `EmbeddingStore` (upsert/get/cosine), behind a thin interface so Chroma/pgvector swap is one-file later; sentinel `DEFAULT_TEXT_MODEL`. Phase B fills in `embed()` + `query_topk`.
- `app/core/job_store.py` — `claims` / `embeddings` / `extraction_failures` tables; `knowledge_status` column on jobs; `ai_settings.task_presets` column; `upsert_claims`, `replace_claims_for_job` (atomic delete+insert in one tx), `get_claims_for_job`, `query_claims`, `delete_claims_for_job`, `set_/get_knowledge_status`, `record_extraction_failure`, `get_/set_task_presets` (api_key encryption)
- `app/api/knowledge_routes.py` — `POST /api/jobs/{id}/extract-knowledge`, `GET /api/jobs/{id}/knowledge`, `GET /api/claims` with `min_confidence` filter (defaults: 0.5 for both job + library queries); persists per-chunk failures to `extraction_failures` quarantine table on every run
- `tests/` — `test_knowledge_schema.py` (11), `test_knowledge_store.py` (21), `test_knowledge_extractor.py` (15), `test_llm_presets.py` (12) — **59 new tests**, all green

### Phase B — what shipped

- `app/core/knowledge_schema.py` — `Entity`, `EntityDraft`, `EntityMention`, `EntityType` enum; `compute_entity_id` (stable `ent_<8-char hash>`); `normalize_entity_name`, `slugify_entity_name`; `ClaimDraft.entity_refs` list; extended `LLM_RESPONSE_SCHEMA` to `{claims, entities}` with per-claim `entity_refs` strings; `ExtractionRunResult` now carries `entities` + `mentions`
- `app/core/embedding_store.py` — `normalize_for_embedding` (lowercase + collapse whitespace); lazy module-level model load w/ thread-lock; module-level `embed()` + `embed_async()` with in-memory FIFO cache (~10k entries, keyed by normalized text); `EmbeddingStore.query_topk` (type-scoped candidate filter, tolerates stale dim mismatches); opt-in `warmup()`
- `app/core/entity_canonicalizer.py` — `EntityCanonicalizer` (run-cached); `canonicalize(name, type, confidence)` pipeline: normalize → embed-async → cosine match against same-type candidates (≥0.85 reuse) → else mint `compute_entity_id` + type-prefixed kebab slug with sequence-suffix on slug collision; alias merging on reuse; persists embedding to the generic `embeddings` table under `object_type="entity"`
- `app/core/job_store.py` — new `entities` (PK `entity_id`, UNIQUE `slug`, indexed on `entity_type`) + `entity_mentions` (FK entity_id, indexed on entity_id + episode_id) tables; `upsert_entity` (merges aliases), `get_entity_by_id`, `get_entity_by_slug`, `slug_exists`, `list_entities`, `find_entity_ids_by_type`, `add_entity_mention`, `get_mentions_for_entity`, `delete_mentions_for_episode`; `replace_claims_for_job(...)` extended to accept optional `entities` + `mentions` and rewrite them inside the same tx
- `app/core/knowledge_extractor.py` — `KnowledgeExtractor` accepts a `canonicalizer`; chunk loop now parses `{claims, entities}`, canonicalizes entities first, resolves `entity_refs` → `entity_ids` through a name→id map (with fallback canonicalization for weak-signal names the LLM didn't also list), emits claim-anchored mentions + chunk-level mentions for unreferenced entities, best-effort `start_char`/`end_char` via `_find_char_span`; overlap dedup now merges `entity_ids` across copies
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
- `app/core/entity_canonicalizer.py` — `canonicalize(name, entity_type) → entity_id`; pipeline: normalize → cache lookup → embed on miss → `query_topk(object_type="entity", filter by entity_type)` → ≥0.85 cosine reuses (adds surface form to aliases if novel) → else mint new `ent_<8-char hash>` + generate slug (type-prefix + kebab of normalized name, sequence-suffix on slug collision only). Stores normalized form + vector in `embeddings` table keyed by `entity_id`.
- `app/api/entity_routes.py` — `GET /api/entities` (filter by `entity_type`, `since`, `slug`), `GET /api/entities/{id_or_slug}` (accepts either `entity_id` or slug), `GET /api/entities/{id_or_slug}/mentions`

**Extend:**
- `app/core/knowledge_schema.py` — add `Entity` (dual-ID: `entity_id` PK + `slug`), `EntityMention` (with `chunk_id`, `raw_text`, optional `start_char`/`end_char`, nullable `claim_id`), `EntityDraft`, `EntityType` enum; extend `LLM_RESPONSE_SCHEMA` to `{claims, entities}` — each entity has its own `confidence`; claims ref entities by string name via `entity_refs: [name]` (weak-signal, resolved post-extraction)
- `app/core/embedding_store.py` — add `normalize_for_embedding(text)` helper (lowercase, strip, collapse whitespace); fill `embed(texts: list[str]) -> list[list[float]]` (sentence-transformers/all-MiniLM-L6-v2, lazy + module-cached model, off event loop via `to_thread`, batched across the input list); module-level `embedding_cache[normalized_text] → vector`; `query_topk(object_type, model, vector, k=1, filter: dict | None)` for cosine search with type-scoped candidate set; optional `warmup()` entrypoint for opt-in background preload
- `app/core/job_store.py` — `entities` (PK `entity_id`, UNIQUE `slug`, indexed on `entity_type`) + `entity_mentions` (char offsets, nullable `claim_id`, indexed on `entity_id` and `episode_id`) tables; `upsert_entity`, `get_entity_by_id`, `get_entity_by_slug`, `list_entities` (type/since filters), `find_entities_by_type` (powers cosine candidate set for canonicalizer), `add_entity_mention`, `get_mentions_for_entity`
- `app/core/knowledge_extractor.py` — after claims validate, walk extracted entities (independently of claim.entity_refs) → canonicalizer → build `name → entity_id` map for the chunk → resolve each claim's `entity_refs` through it to populate `Claim.entity_ids` → emit `EntityMention` rows with chunk span data (best-effort string search for char offsets). Unreferenced entities still persist. Route entities + mentions + claims through the extended `replace_claims_for_job` in one transaction.
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

### Phase C.1 — files to ship

**New:**
- `app/core/topic_canonicalizer.py` — `canonicalize(name, description) → topic_id`; normalize → embed `"{name}: {description}"` → query_topk against existing topics → ≥0.90 cosine reuse (merge alias, update description if confidence higher) → else mint `top_<hash>`.
- `app/core/topic_aggregator.py` — `aggregate(claims) → (topics, edges)`; numbered-claim prompt, LLM call via `summarize` preset, parses `{topics: [{name, description, confidence, claim_indices: [int]}]}`, resolves indices back to `claim_id`s.
- `app/core/topic_normalization.py` — `TICKER_MAP` + `normalize_topic_for_match(text)`; pure module, no DB.
- `app/api/topic_routes.py` — `GET /api/topics`, `GET /api/topics/{id}`, `GET /api/topics/{id}/claims`.

**Extend:**
- `app/core/knowledge_schema.py` — add `Topic`, `TopicDraft`, `ClaimTopicEdge`, `TOPIC_AGGREGATION_SCHEMA` (separate from `LLM_RESPONSE_SCHEMA`), `compute_topic_id`.
- `app/core/job_store.py` — `topics` + `claim_topics` tables; `upsert_topic`, `get_topic_by_id`, `list_topics`, `get_claim_topic_edges`, `get_claims_for_topic`; extend `replace_claims_for_job` to accept `topics` + `claim_topic_edges` and replace both inside the existing tx.
- `app/core/knowledge_extractor.py` — after claims validate, if `len(claims) >= 3` and a `summarize` provider is configured, run `TopicAggregator.aggregate(claims)` → `(topics, edges)`; attach to `ExtractionRunResult`; populate `Claim.topic_ids` from edges as denormalized cache.
- `app/api/knowledge_routes.py` — pass `topics` + `claim_topic_edges` into `replace_claims_for_job`.
- `app/api/__init__.py` — register `topic_router`.

**Tests:**
- `tests/test_topic_canonicalizer.py` — normalization (ticker expand, plural collapse, whitespace); cosine reuse ≥0.90; below-threshold mints new; description merge on reuse.
- `tests/test_topic_aggregator.py` — numbered-claim prompt; LLM response → `(topics, edges)` mapping; claim-index out-of-range handled; empty/malformed LLM output returns empty result.
- `tests/test_topic_api.py` — list/get/claims endpoints (TestClient pattern from `test_entity_api.py`).
- Extend extractor + store + schema tests for topic path.

### Phase C.1 — what shipped

- `app/core/topic_normalization.py` — `TICKER_MAP` (btc/eth/sol/… → names, llm/rag/mcp → expansions), `normalize_topic_for_match` (compose: `normalize_for_embedding` → ticker expand → conservative last-word plural collapse that preserves `-ss`/`-us`/`-is`/`-os`/`-ies` endings)
- `app/core/knowledge_schema.py` — `Topic`, `TopicDraft`, `ClaimTopicEdge`, `compute_topic_id` (stable `top_<8-char hash>` over normalized name), `TOPIC_AGGREGATION_SCHEMA` (separate LLM schema for the second-pass call — one `topics` array, each with `name / description / confidence / claim_indices`); `ExtractionRunResult` carries `topics` + `claim_topic_edges`
- `app/core/topic_canonicalizer.py` — embed `f"{normalized_name}: {description}"`, cosine ≥ **0.90** reuse with alias merge + description replacement on higher-confidence hit, else mint new `top_<hash>` and write the embedding under `object_type="topic"` in the generic `embeddings` table (so Phase B's `query_topk` just works)
- `app/core/topic_aggregator.py` — second-pass service; `aggregate(claims) → (topics, edges, tokens)`; numbered claim prompt, `summarize` task preset, `TOPIC_AGGREGATION_SCHEMA` JSON-mode response; graceful degradation on every failure axis (no provider / no canonicalizer / below `MIN_CLAIMS_FOR_AGGREGATION=3` / malformed JSON / missing `topics` field / out-of-range `claim_indices`); truncates to top-confidence `MAX_CLAIMS_PER_CALL=120` when oversized
- `app/core/knowledge_extractor.py` — optional `topic_aggregator` ctor arg; after claim dedup, if `len(final_claims) >= MIN_CLAIMS_FOR_AGGREGATION` and aggregator is wired, runs the topic pass inside a broad try/except (topic failure never fails the run) and rewrites each claim's `topic_ids` from the edges as the denormalized cache
- `app/core/job_store.py` — new `topics` (PK `topic_id`) + `claim_topics` (composite PK `(claim_id, topic_id)` + confidence + FK on both sides) tables; `upsert_topic` (merges aliases), `get_topic_by_id`, `list_topics`, `find_topic_ids`, `add_claim_topic_edge`, `get_claim_topic_edges`, `get_claims_for_topic` (joins through `claim_topics`, not the JSON cache); `replace_claims_for_job(...)` extended with `topics` + `claim_topic_edges` args — explicit `DELETE FROM claim_topics WHERE claim_id IN (...)` before the claim delete closes the orphan-edges hole without flipping `PRAGMA foreign_keys` globally; bogus edges (claim_id not in this run) are logged and dropped rather than crashing the tx
- `app/api/topic_routes.py` — `GET /api/topics` (since/limit/offset), `GET /api/topics/{topic_id}`, `GET /api/topics/{topic_id}/claims` (reads from the join so reverse queries always see source of truth)
- `app/api/knowledge_routes.py` — `POST /jobs/{id}/extract-knowledge` passes `topics` + `claim_topic_edges` into `replace_claims_for_job` so claims / entities / mentions / topics / edges land in one transaction
- `app/api/__init__.py` — topic router wired
- `README.md` — Knowledge Extraction bullet expanded to surface `/api/entities` + `/api/topics` alongside the existing `/api/claims` mention (covered both Phase B + C.1 README drift in one pass)
- `tests/` — `test_topic_canonicalizer.py` (17), `test_topic_aggregator.py` (9), `test_topic_api.py` (7), +15 topic tests in `test_knowledge_schema.py`, +11 topic tests in `test_knowledge_store.py`, +3 topic-pass tests in `test_knowledge_extractor.py` — **54 new tests**, 208/208 suite green

Commit: `7d3ce0f feat(knowledge): P18 Phase C.1 — topics aggregation layer`. Includes post-review polish (docstring accuracy for the `claim_topics` upsert SQL, graceful-degradation branches enumerated on `TopicAggregator.aggregate`).

### Phase C.2 — locked decisions (Predictions, future)

1. **Dedicated `predictions` table, FK `claim_id UNIQUE`.** Physically separate from `claims`. Prediction is semantically a `claim_type`, but the lifecycle columns (`target_horizon`, `conditions`, `falsifiable_by`, `resolution`, `resolved_at`) aren't "just nullable fields" — they're the start of a lifecycle. Separate table keeps claim rows clean and makes future expansion (resolution events, resolution evidence, confidence recalibration, tracking dashboards) land on a dedicated row instead of adding more nullable columns.
2. Prediction-specific extraction prompts + validation; API endpoints `GET /api/predictions?resolution=pending`, `POST /api/predictions/{id}/resolve`.

### Phase C.3 — locked decisions (Backfill + cost guardrails, future)

1. **Both-trigger backfill** (background scheduler + route-triggered on-demand). Background-only feels stale; on-demand-only misses cold inventory. Both is the right default — dedup is the interesting engineering problem.
2. **Status machine: `pending | running | ready | failed`** + `knowledge_version` + `locked_at` / `worker_id` for claim-lock. Idempotent enqueue: calling enqueue twice on the same pending job is a no-op.
3. **Route behavior on `/jobs/{id}/knowledge`:** `ready` → return cached. `running` → return in-progress status (client polls). `pending` → acquire lock, run inline if cheap enough, otherwise enqueue and return `202 Accepted`.
4. **Budgets: global default + per-subscription override.** Global daily extraction budget in settings; optional per-feed override + priority tier; downgrade to cheaper `extract` model when over budget. Top-priority feeds stay on the better model longer.

---

## P19: Sift MCP Server (Capability Surface)

**Goal:** Expose Sift as an MCP (Model Context Protocol) server so Claude Desktop, Cursor, and custom agents can call Sift primitives directly. This shifts Sift from "an app that ships connectors" to "a capability surface" — Obsidian / Notion / Logseq become *agent-side targets*, not Sift-side integrations.

> The unlock: build N agent skills on top of one MCP server, instead of N×M point-to-point connectors. Inspired by the `podwise-cli` MCP surface, but goes deeper because Sift has the structured knowledge layer (P18) underneath.

### Tool surface (stable JSON Schema per tool)

- [ ] **Ingest & retrieval**
  - [ ] `ingest_url(url, profile?)` — submit URL, return `episode_id` + pipeline status
  - [ ] `get_transcript(episode_id, format?)` — text / SRT / JSON with timestamps
  - [ ] `get_chapters(episode_id)` — auto-generated chapter markers
  - [ ] `get_segment(episode_id, start, end)` — pull a specific time range
  - [ ] `get_clips(episode_id, criteria?)` — viral / insightful / topic-filtered clips
- [ ] **Understanding**
  - [ ] `get_summary(episode_id, mode?)` — bullets / chapters / topics / action items
  - [ ] `get_highlights(episode_id)` — pull-quote-grade excerpts with timestamps
  - [ ] `get_claims(episode_id)` — structured claims (reads from P18)
  - [ ] `get_entities(episode_id)` — people / companies / tickers / projects
  - [ ] `get_topics(episode_id)` — topic graph
  - [ ] `get_predictions(episode_id)` — falsifiable forward-looking claims
- [ ] **Q&A**
  - [ ] `ask_episode(episode_id, question)` — RAG against single episode (depends on P11)
  - [ ] `ask_at_timestamp(episode_id, time_range, question)` — scoped Q&A
  - [ ] `search_library(query, filters?)` — semantic search across all episodes (depends on P10)
- [ ] **Cross-episode synthesis**
  - [ ] `compare_episodes(episode_ids[], topic?)` — agreements / disagreements
  - [ ] `find_contradictions(speaker?, topic?, timeframe?)` — surface inconsistencies
  - [ ] `summarize_trend(topic, last_n_days)` — narrative evolution over time
- [ ] **Export**
  - [ ] `export_to_vault(episode_id, target, template?)` — Obsidian / Notion / Logseq (depends on P21)

### Tasks

- [ ] Implement `sift-mcp` server:
  - [ ] stdio transport (Claude Desktop, local agents)
  - [ ] HTTP transport (remote agents, Cursor)
  - [ ] Auth via Sift API key (passthrough)
  - [ ] Streaming for long-running tools (`ingest_url`, `ask_episode`)
- [ ] Schema-first: every tool ships with a stable JSON Schema and example call
- [ ] Reference agent skills (shipped in repo):
  - [ ] **Episode → Obsidian note** (claims + highlights + clickable timestamps)
  - [ ] **Weekly recap** (cross-source synthesis from subscriptions)
  - [ ] **Topic research** (search → claims → contradictions → brief)
  - [ ] **Language learning** (transcript + translation + key vocabulary)
- [ ] Distribution:
  - [ ] `uvx sift-mcp` install path
  - [ ] Claude Desktop config snippet in README
  - [ ] Cursor MCP config snippet
  - [ ] Test suite covering Claude Desktop + Cursor + raw MCP client

---

## P20: Subscription Digest Pipeline (Cross-Episode Synthesis)

**Goal:** Turn Sift from on-demand tool into always-on knowledge pipeline. Nightly ingest of subscribed feeds → structured extraction (P18) → cross-episode synthesis → multi-channel digest output. The differentiator vs. single-episode summarizers is *cross-source synthesis*: what 5 podcasts said about the same topic this week, who's repeating which narrative, what's new framing.

> Single-episode summary is a feature; continuous knowledge monitoring is the product.

### Phase 1 — Subscription-driven brief

- [ ] Cron-driven nightly ingest job (`app/workers/digest_runner.py`)
- [ ] Per-subscription pipeline profile (Quick / Deep / Full — reuses P12)
- [ ] Auto-extract structured knowledge per new episode (depends on P18)
- [ ] Daily digest email per subscription set
- [ ] Cost guardrails (per-feed daily budget, model downgrade when over)
- [ ] Failure handling: caption-missing fallback, low-quality transcript flag, retry queue

### Phase 2 — Topic synthesis

- [ ] User-defined topic tracking (BTC, AI agents, ETH ETF, stablecoins, etc.)
- [ ] Daily topic answers:
  - [ ] Which episodes mentioned it
  - [ ] New claims / predictions on this topic
  - [ ] Cross-source agreement / disagreement
  - [ ] Repeated-narrative detection (who is amplifying which framing)
- [ ] Topic-scoped digest (per topic, not per feed)

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

- [ ] Dedup across feeds (same news mentioned by N podcasts → single digest item)
- [ ] Source ranking (per-user trust weights)
- [ ] API endpoints:
  - [ ] `POST /api/digests` - Create / configure a digest
  - [ ] `GET /api/digests/{id}` - Get latest digest output
  - [ ] `POST /api/topics` - Track a topic
  - [ ] `GET /api/topics/{id}/synthesis` - Cross-source synthesis for a topic

---

## P21: Vault & Note-App Export Channels

**Goal:** First-class output channels for Obsidian / Notion / Logseq — served both directly (write-to-vault) and through MCP (`export_to_vault` tool from P19). Templated markdown with frontmatter, clickable timestamps, claim cards, embedded highlights.

> The "very convenient YouTube → note" UX, but built on primitives instead of a one-off plugin.

### Tasks

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

---

## v2.0 Backlog (Future Ideas)

- [ ] **Cross-Platform Social Graph**: Track speakers across downloads, build profiles of their positions over time
- [ ] **Visual Trend Extraction**: For video from 小红书/Instagram, use vision AI to extract aesthetic trends, product placements, visual themes
- [ ] **AI-Generated Podcast Feed**: Auto-create a personal podcast RSS feed from daily distillations
- [ ] Audio fingerprinting for duplicate detection
- [ ] Voice search within transcripts (speak a query, find the answer)
- [ ] Multi-language UI
- [ ] Export to cloud storage (S3, Google Drive, Dropbox)
- [x] Notion integration for structured data export → promoted to **P21: Vault & Note-App Export Channels**
- [x] MCP server for LLM agent integration → promoted to **P19: Sift MCP Server (Capability Surface)**
