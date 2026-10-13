# Sift

<p align="center">
  <img src="frontend/public/logo.svg" alt="Sift" width="200">
</p>

**AI-First Knowledge Extraction Platform.** Ingest audio and video from X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, 小宇宙, 喜马拉雅, and more — then extract, search, and reason over the knowledge inside.

> Downloading is just the first step. Sift turns media into searchable, queryable intelligence.

## Features

### Ingest & Extract
- **Multi-Platform Ingest** - X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, 小宇宙, 喜马拉雅
- **Video Downloads** - X/Twitter, YouTube, Instagram, 小红书 (480p/720p/1080p)
- **Transcription** - Local Whisper or API models (OpenAI, Groq, etc.), 99+ languages
- **Fetch Transcript** - Instantly grab existing YouTube captions or Spotify Read Along transcripts (no Whisper needed)
- **Subtitle-Grade SRT/VTT** - Subtitle output is reflowed into readable cues rather than dumped one-per-ASR-segment: width-capped lines, max two lines, breaks at punctuation and never mid-word, CJK-aware (16 chars/line, not 8), fragmentary auto-captions merged. See [Subtitle Output](#subtitle-output).
- **Live Transcription** - Real-time microphone transcription via WebSocket
- **Smart Metadata** - Auto-embed ID3/MP4 tags with artwork

### Understand & Analyze
- **Knowledge Extraction** - Structured, citable claims (fact / opinion / prediction / question / recommendation) with timestamps, speaker attribution, and confidence scores. Canonical entities (people, companies, tickers, projects) and topic clusters are resolved across episodes so the same concept collapses to one node in the graph. Prediction claims get lifecycle metadata (target horizon, conditions, falsifier) and a resolve / revert API for tracking accuracy over time. Queryable across your library via `/api/claims`, `/api/entities`, `/api/topics`, and `/api/predictions`. Newly transcribed episodes are **auto-queued for extraction** the moment a transcript completes (toggle with `knowledge_auto_extract`), so the knowledge base stays current with no manual step. Extraction also runs **on demand** (a `GET /api/jobs/{id}/knowledge` on an un-extracted job runs inline for short transcripts, or returns `202` and queues longer ones) and via a **background backfill worker** that processes the back catalogue under a claim-lock with per-day cost guardrails (daily budget + automatic model downgrade); enqueue with `POST /api/jobs/{id}/knowledge/enqueue` and watch progress at `GET /api/knowledge/backfill-status`. The full schema contract lives in [`docs/knowledge-schema.md`](docs/knowledge-schema.md).
- **Ask Audio (RAG)** - Chat with your downloads — ask questions, get answers grounded in the transcript with cited timestamps, per episode or library-wide, via `POST /api/ask` or the MCP `ask_episode` / `ask_at_timestamp` tools. See [Ask Audio](#ask-audio).
- **Semantic Search** - Search your entire library by concept, not just keywords. Transcripts are auto-indexed into vector embeddings (local model, free) on completion; query via `POST /api/search` with job/platform/speaker/date filters, or the MCP `search_library` / `search_segments` tools. See [Semantic Search](#semantic-search).
- **Psychographic Mapping** - Emotional heatmap timeline with AI-powered reasoning: detect heated moments, explain *why* they're heated, and spot contradictions across a conversation
- **LLM Summarization** - Bullet points, chapter markers, key topics, action items via any AI provider
- **Speaker Diarization** - Identify different speakers (optional)
- **Contradiction Detection** - AI cross-references extracted claims — within an episode or by one speaker across episodes — and surfaces pairs that can't both be true, with quotes, timestamps, and confidence. `POST /api/jobs/{id}/analyze-contradictions`, `GET /api/contradictions?speaker=`, or the MCP `find_contradictions` tool.
- **Structured Data Extraction** - Turn a transcript into typed fields with built-in presets (meeting notes, interview, tutorial, news/analysis, product review) or your own schema — save named schemas via `POST /api/extraction-schemas` and reuse them with `schema_id`. Export any extraction as JSON, Markdown, or CSV at `GET /api/jobs/{id}/extract/export?format=`.

### Transform & Create
- **Translation** - TranslateGemma (local) or AI providers, 55+ languages
- **Social Media Clips** - AI identifies viral-worthy moments, generates captions & hashtags
- **Audio Enhancement** - Noise reduction & voice isolation (FFmpeg-based), neural voice reconstruction on the roadmap
- **Content Distiller** - Pick several episodes and get one synthesized briefing — what they agreed on, where they contradict each other, and which narratives repeat. `POST /api/distill`, or the **Library → Distill** tab.

### Automate & Integrate
- **Vault & Note-App Export** - Turn any episode into a templated markdown note for **Obsidian / Logseq / plain markdown** — YAML frontmatter, clickable timestamp links, claim cards, pull-quote highlights, a collapsible transcript, and `[[wikilinks]]` for canonical entities. Served over the API and the MCP `export_to_vault` tool. See [Vault Export](#vault--note-app-export).
- **Subscription Digests (Cross-Episode Synthesis)** - Define a digest over a set of subscriptions and Sift generates a scheduled cross-source brief: what several episodes agreed on, where they disagreed, repeated narratives, and predictions worth tracking. The differentiator over single-episode summaries is reading *across* sources. Also on-demand per-topic synthesis. See [Subscription Digests](#subscription-digests).
- **MCP Server (Capability Surface)** - Expose Sift to Claude Desktop, Cursor, and custom agents as MCP tools (`ingest_url`, `get_transcript`, `get_claims`, `get_entities`, `get_topics`, `get_predictions`, …). One server, N agent skills. See [MCP Server](#mcp-server) below.
- **Agentic Ingest Pipeline** - Paste a URL with a profile (`quick` / `deep` / `full`) and Sift runs the whole chain — transcribe, search-index, knowledge extraction, summary, sentiment, clips, webhook — with per-stage status at `GET /api/jobs/{id}/pipeline`. See [Agentic Ingest](#agentic-ingest).
- **Telegram Research Assistant** - Send a link, then ask questions about the content — the bot answers instantly
- **Intelligent Webhooks** - Delivery payloads carry more than a status line: pick `minimal`, `summary` (AI summary + key topics), or `full_intelligence` (entities, sentiment, claim counts). Assembled from already-extracted data, never a fresh LLM call.
- **Subscriptions** - Auto-monitor RSS feeds, YouTube channels, and playlists
- **Batch Downloads** - Download multiple URLs at once with progress tracking
- **Priority Queue** - Prioritize important downloads (1-10 levels)
- **Scheduled Downloads** - Schedule downloads for specific times
- **Job Recovery** - SQLite persistence, auto-resume on restart
- **Collaborative Annotations** - Add comments to transcripts with real-time sync

## Quick Start

### System Dependencies

```bash
# macOS (required for both modes)
brew install ffmpeg yt-dlp
```

### Desktop App (recommended)

Native app with Rust backend — no Python needed.

```bash
git clone https://github.com/yourusername/Sift.git
cd Sift

# Development (hot-reload)
make dev

# Build installer (.dmg / .msi / .deb)
make desktop
```

### Web Mode (self-hosted, full features)

Python backend with transcription, LLM summarization, Telegram bot.

```bash
git clone https://github.com/yourusername/Sift.git
cd Sift
uv sync --extra transcribe

# Run both backend + frontend
make dev-web
```

> **Important:** Desktop and web modes both use port 8000. Only run one at a time.
> If you get port conflicts, run: `lsof -ti:8000 | xargs kill -9`

## CLI Usage

```bash
uv run sift download "https://x.com/i/spaces/1vOxwdyYrlqKB"
uv run sift download "https://youtube.com/watch?v=xxx" -f mp3
uv run sift download "https://podcasts.apple.com/..." -f mp3 -q highest
```

### As a Python library

The ingestion core is its own package, [`sift-core`](packages/sift-core/README.md), and runs without the server, database, or bot.
Pass settings explicitly, or leave them out to read the same env vars / `.env`:

```python
import asyncio
from sift_core import IngestSettings, download_audio, get_metadata

settings = IngestSettings(download_dir="./downloads", youtube_cookies_from_browser="chrome")
result = asyncio.run(download_audio("https://podcasts.apple.com/...", settings=settings))
print(result.file_path, result.metadata.title if result.metadata else None)
```

For agents, `sift-core-mcp` exposes download, metadata, caption fetch and
transcription as local MCP tools, with no server needed. See
[sift-core's README](packages/sift-core/README.md#local-mcp-server).

### Audio → YouTube-ready video

Turn a downloaded audio file into an MP4 with a still image (H.264 + AAC,
faststart) that uploads cleanly to YouTube. AAC audio is stream-copied (no
re-encode); other codecs are transcoded to AAC.

```bash
xdownloader to-video podcast.m4a
xdownloader to-video --resolution 1080p -o show.mp4 podcast.m4a
```

## API

Full API documentation available at http://localhost:8000/docs (Swagger UI)

## Web UI

`make dev-web` serves the React app on `:5173` against the API on `:8000`.

| Page | What it does |
|------|--------------|
| **Audio** / **Video** | Paste a URL, pick a format, download |
| **Transcribe** | Transcribe a URL or an uploaded file; the result view carries summary, translation, sentiment, structured extraction, contradictions, per-episode Ask, and pipeline progress |
| **Clips** | AI-suggested viral moments with captions |
| **Live** | Real-time microphone transcription |
| **Library** | **Search** your whole library by meaning · **Ask** it questions with cited sources · **Distill** several episodes into one brief |
| **Feeds** | RSS / YouTube channel subscriptions |
| **Settings** | AI providers, translation, webhooks, storage |

Episodes ingested through the [agentic pipeline](#agentic-ingest) show per-stage
progress in the transcription view; ordinary transcriptions show nothing extra.

## Supported Platforms

### Audio
| Platform | URL Pattern |
|----------|-------------|
| X Spaces | `x.com/i/spaces/...` |
| Apple Podcasts | `podcasts.apple.com/...` |
| Spotify | `open.spotify.com/...` |
| YouTube | `youtube.com/watch?v=...` |
| Discord | `cdn.discordapp.com/attachments/...` |
| 小宇宙 | `xiaoyuzhoufm.com/episode/...` |
| 喜马拉雅 | `ximalaya.com/sound/...` (single episodes; album pages not supported) |

### Video
| Platform | URL Pattern |
|----------|-------------|
| X/Twitter | `x.com/user/status/...` |
| YouTube | `youtube.com/watch?v=...` |
| Instagram | `instagram.com/reel/...`, `instagram.com/p/...` (requires login cookies — see [docs/instagram-setup.md](docs/instagram-setup.md)) |
| 小红书 | `xiaohongshu.com/explore/...`, `xhslink.com/...` |

## Telegram Bot

More than a download bot — a **research assistant**. Send a link and ask questions about the content. Supports all 10 platforms with inline format selection, transcription, and AI-powered Q&A.

```bash
uv run sift-bot  # Polling mode (local dev)
```

Or run in webhook mode alongside the FastAPI server — set in `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_BOT_MODE=webhook
TELEGRAM_WEBHOOK_URL=https://yourdomain.com/api/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=optional-secret
```

**Bot commands:** `/start`, `/help`, `/status`, `/platforms`, `/transcribe`

## Configuration

Create `.env`:

```env
# Server
HOST=127.0.0.1            # Use 0.0.0.0 to expose to network
PORT=8000
DOWNLOAD_DIR=./output

# API Authentication (optional for localhost; REQUIRED if exposed to a network)
# API_KEY=your-secret-key  # If set, requires X-API-Key header

# Secret encryption (set for production — encrypts stored AI provider keys at rest)
# ENCRYPTION_KEY=your-strong-random-secret

# Telegram Bot
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_BOT_MODE=polling         # "polling" or "webhook"
# TELEGRAM_WEBHOOK_URL=https://yourdomain.com/api/telegram/webhook
# TELEGRAM_WEBHOOK_SECRET=optional-secret

# YouTube cookies (for bypassing bot detection / age restrictions)
# YOUTUBE_COOKIES_FILE=./cookies.txt
# ...or read fresh cookies straight from a local browser (takes precedence):
# YOUTUBE_COOKIES_FROM_BROWSER=chrome

# Optional
HUGGINGFACE_TOKEN=hf_xxx  # For speaker diarization

# yt-dlp binary. Adapters prefer the version pinned in pyproject.toml (the one
# `uv sync` installs) over a system-wide install, so a stale `brew install
# yt-dlp` can't silently shadow it. Set this to force a specific binary.
# YT_DLP_PATH=/usr/local/bin/yt-dlp

# Queue & Scheduling
QUEUE_ENABLED=true
MAX_CONCURRENT_QUEUE_JOBS=5
SCHEDULER_ENABLED=true
SCHEDULER_CHECK_INTERVAL=60

# Webhooks
DEFAULT_WEBHOOK_URL=https://your-webhook.com/hook
WEBHOOK_RETRY_ATTEMPTS=3
WEBHOOK_RETRY_DELAY=60

# Spotify Transcript (optional - for fetching Spotify Read Along transcripts)
# SPOTIFY_SP_DC=your-sp-dc-cookie-value
```

### YouTube Cookies

If YouTube shows "Sign in to confirm you're not a bot" or blocks age-restricted / geo-restricted content, you need to provide browser cookies:

1. Open YouTube in your browser and make sure you're logged in
2. Export cookies using **one** of these methods:
   - **yt-dlp** (easiest): `yt-dlp --cookies-from-browser chrome --cookies cookies.txt "https://youtube.com"`
   - **Browser extension**: Install "Get cookies.txt LOCALLY" and export from youtube.com
3. Place the `cookies.txt` file in your project directory
4. Add to `.env`:
   ```env
   YOUTUBE_COOKIES_FILE=./cookies.txt
   ```

> Note: YouTube cookies expire periodically. If downloads start failing again, re-export fresh cookies.

### Fetch Transcript

YouTube transcripts work out of the box - no configuration needed. When you paste a YouTube URL in the Transcribe page, it will automatically detect available captions and let you fetch them instantly.

For **Spotify** transcripts, you need to provide your `sp_dc` cookie:

1. Open [https://open.spotify.com](https://open.spotify.com) in your browser and log in
2. Open DevTools (`F12` or `Cmd+Shift+I`)
3. Go to **Application** tab (Chrome) or **Storage** tab (Firefox)
4. Expand **Cookies** → click `https://open.spotify.com`
5. Find the cookie named `sp_dc` and copy its value
6. Add to `.env`:
   ```env
   SPOTIFY_SP_DC=your-copied-value-here
   ```

> Note: The `sp_dc` cookie expires periodically. If Spotify transcript fetching stops working, repeat the steps above to get a fresh cookie.

### Subtitle Output

Raw ASR segments are not subtitles. Whisper emits 10-30 second segments that overflow any player; fetched YouTube auto-captions arrive as 2-3 word cues that flicker. Every `srt` / `vtt` response is therefore reflowed through one shared writer that caps line width, keeps cues to two lines, breaks at punctuation instead of mid-word, and merges fragmentary cues.

Measurement is script-aware and chosen from the text itself, not from the declared language — so a Chinese episode quoting English product names gets the right rule per line (16 characters for a CJK line, 42 display-width units for a Latin one).

Four presets, selected globally or per request:

| preset | line width | max lines | notes |
|---|---|---|---|
| `balanced` *(default)* | 42 Latin / 16 CJK | 2 | comfortable reading pace |
| `broadcast` | 42 / 16 | 2 | Netflix-derived timing |
| `youtube` | 42 / 16 | 2 | aggressive merging for auto-captions |
| `single_line` | 32 / 12 | 1 | burned-in / clip captions |

```env
SUBTITLE_REFLOW=true          # false restores the raw one-cue-per-segment output
SUBTITLE_STYLE_PRESET=balanced
```

```bash
curl -X POST localhost:8000/api/transcript/fetch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtu.be/...", "output_format": "srt", "subtitle_style": "youtube"}'
```

Some sources cannot satisfy every subtitle rule — 60 characters spoken in 2 seconds reads at 30 cps no matter where you cut it, and splitting cannot change that. Rather than fail the transcription or silently emit a broken cue, the reflow emits the best legal cue and logs what it could not meet (`"12 cues, unmet targets: 3 reading_speed"`).

### API Authentication

By default, the API is open (no auth required) - suitable for local/self-hosted use.

To enable authentication, set `API_KEY` in `.env`:

```bash
# .env
API_KEY=my-secret-key

# Then include header in requests
curl -H "X-API-Key: my-secret-key" http://localhost:8000/api/health
```

### Issued API keys, usage & quotas

Beyond the single master key, you can mint per-client **principal keys** (only their SHA-256 is stored; the plaintext is shown once):

```bash
# Mint a key with an optional daily request quota (master key required)
curl -X POST http://localhost:8000/api/principals -H "X-API-Key: my-secret-key" \
  -H "Content-Type: application/json" -d '{"name": "acme-integration", "daily_request_quota": 5000}'
# → {"api_key": "sk_sift_...", ...}  ← save it now, it is never shown again

curl http://localhost:8000/api/principals -H "X-API-Key: my-secret-key"       # list (no key material)
curl -X DELETE http://localhost:8000/api/principals/pr_xxxx -H "X-API-Key: my-secret-key"  # revoke
```

Every request made with a principal key is counted in a per-day **usage ledger** (`GET /api/usage` — a principal sees its own usage, the master key sees everything), and once a principal's `daily_request_quota` is exhausted further requests get `429`. Only the master key can manage principals — a principal key can never mint or revoke keys.

### Signed webhooks

Set `WEBHOOK_SIGNING_SECRET` and every webhook delivery carries `X-Sift-Timestamp` and `X-Sift-Signature: sha256=<hex>`, where the signature is `HMAC-SHA256(secret, "<timestamp>.<raw body>")`. Verify on your receiver:

```python
import hashlib, hmac

def verify(secret: str, body: bytes, ts: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"sha256={expected}")
```

Reject stale timestamps (e.g. older than 5 minutes) to block replays.

## Build & Run

### Available Commands

| Command | What it does |
|---------|-------------|
| `make dev` | Desktop dev mode — Tauri + Rust backend + hot-reload |
| `make dev-web` | Web dev mode — Python backend + Vite frontend |
| `make dev-backend` | Python backend only (`:8000`) |
| `make dev-frontend` | Vite frontend only (`:5173`) |
| `make desktop` | Build desktop installer (`.dmg` / `.msi` / `.deb`) |
| `make test` | Run Python test suite |
| `make lint` | Lint Python + TypeScript + Rust |
| `make clean` | Remove build artifacts |

### Desktop App

**Prerequisites:** [Rust](https://rustup.rs/), [Bun](https://bun.sh/), yt-dlp, ffmpeg

```bash
make desktop    # Build installer (~1 min)
```

| Platform | Installer | Location |
|----------|-----------|----------|
| macOS | `.dmg` (6.9 MB) | `frontend/src-tauri/target/release/bundle/dmg/` |
| Windows | `.msi` | `frontend/src-tauri/target/release/bundle/msi/` |
| Linux | `.deb` | `frontend/src-tauri/target/release/bundle/deb/` |

The desktop app embeds an **axum HTTP server** (Rust) that runs on `localhost:8000` inside the Tauri process. The React frontend connects the same way as web mode — no configuration needed.

- **Download engine**: yt-dlp subprocess with `--concurrent-fragments 16`
- **Job persistence**: SQLite via rusqlite
- **Binary**: 17 MB, **DMG**: 6.9 MB

### Web Server

**Prerequisites:** Python 3.10+, [uv](https://github.com/astral-sh/uv), [Bun](https://bun.sh/), yt-dlp, ffmpeg

```bash
uv sync --extra transcribe    # Install Python deps
make dev-web                  # Starts backend + frontend
```

### Docker

```bash
docker-compose up -d    # API + Frontend + Whisper + Ollama
```

See [Deployment Guide](docs/deployment.md) for Docker, cloud, and systemd setup.

## Vault & Note-App Export

Export an episode as a templated markdown note, built on Sift's primitives (transcript + the P18 knowledge layer) rather than a one-off plugin.

- **Targets:** `obsidian` (`[[wikilinks]]` + collapsible `> [!note]` callout transcript), `logseq` (outline bullets), `markdown` (portable plain text).
- **Templates:** `episode` (frontmatter, claim cards, clickable timestamps, full transcript) and `highlights` (top claims by confidence, no transcript).
- **Frontmatter:** title, source, date, speakers, topics, entities, tags — YAML-safe (anti-injection).

```bash
# Write an Obsidian note into a configured vault
curl -X POST http://localhost:8000/api/jobs/{id}/export -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "target": "obsidian", "template": "episode", "vault_path": "~/Vaults/Research", "subfolder": "Sift"
}'

# Preview the rendered markdown without writing
curl -X POST http://localhost:8000/api/jobs/{id}/export -H "X-API-Key: $KEY" -d '{"write": false, "template": "highlights"}'

# List templates + targets
curl http://localhost:8000/api/export-templates -H "X-API-Key: $KEY"
```

Vault paths are restricted to your home directory or the configured download dir, with `..`/absolute-path containment on the subfolder. Agents can call the same thing via the MCP `export_to_vault(episode_id, target, template?, preview?)` tool. **Notion** export (database rows per claim) is deferred — it needs an external integration token + SDK.

## Subscription Digests

A **digest** turns Sift from an on-demand tool into an always-on knowledge pipeline. Define a digest over one or more [subscriptions](#subscriptions), and a background runner periodically gathers the new episodes in a time window, extracts their structured knowledge (P18), and runs **cross-episode synthesis** with the `synthesize` LLM preset — producing a brief of:

- **Themes** that surfaced across multiple sources
- **Consensus** — what the sources broadly agreed on
- **Disagreements** — where they took opposing positions
- **Predictions to track** — falsifiable forward-looking claims, attributed
- **Narratives** — repeated framings and who is amplifying them

The output is stored as structured JSON + rendered markdown, and (if configured) pushed to a webhook. The differentiator vs. a single-episode summary is *cross-source synthesis*: "what 5 podcasts said about the same topic this week."

```bash
# Create a digest over two subscriptions, synthesized daily over a 7-day window
curl -X POST http://localhost:8000/api/digests -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "name": "Crypto Weekly",
  "subscription_ids": ["sub_abc", "sub_def"],
  "window_days": 7,
  "schedule_hours": 24,
  "webhook_url": "https://hooks.example.com/digest"
}'

# Generate one now (synchronous) and read it back
curl -X POST http://localhost:8000/api/digests/{id}/run -H "X-API-Key: $KEY"
curl http://localhost:8000/api/digests/{id} -H "X-API-Key: $KEY"   # config + latest run

# On-demand cross-source synthesis for a single topic (across the whole library)
curl http://localhost:8000/api/topics/{topic_id}/synthesis -H "X-API-Key: $KEY"
```

Endpoints: `POST/GET/PATCH/DELETE /api/digests`, `GET /api/digests/{id}` (config + latest run), `POST /api/digests/{id}/run`, `GET /api/digests/{id}/runs`, `GET /api/topics/{id}/synthesis`. The runner respects the same per-day LLM budget guardrail as knowledge extraction (`KNOWLEDGE_DAILY_BUDGET_USD`); toggle the worker with `DIGEST_ENABLED`. Email / Notion / Obsidian delivery channels land with P21.

**On-demand distillation:** the same cross-source synthesis, but over episodes *you pick* instead of a subscription window. `POST /api/distill {"job_ids": [...], "mode": "synthesis" | "debate"}` returns one brief (debate mode leads with the disagreements and each side's strongest sourced position); fetch it later as structured JSON (`GET /api/distill/{id}`), rendered markdown (`GET /api/distill/{id}/markdown`), or browse history at `GET /api/distillations`.

## Semantic Search

Every completed transcription is automatically chunked and embedded with a local sentence-transformers model (no LLM cost) into the same embedding store the knowledge layer uses. Query by meaning, not keywords:

```bash
# Library-wide concept search
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "difference between L2s and sidechains", "k": 5}'

# Scope to one episode, or filter by platform / speaker / date
curl "http://localhost:8000/api/search?q=fed+rate+hike&job_id=<id>"
curl -X POST http://localhost:8000/api/search \
  -d '{"query": "airdrop rumors", "platform": "youtube", "since": "2026-07-01"}'
```

Hits return the matching transcript chunk with timestamps, speaker, cosine score, and episode context (title / source URL / platform) — jump straight to the moment. Older episodes transcribed before this feature: `POST /api/search/reindex` sweeps them in batches, `POST /api/jobs/{id}/search-index` (re)indexes one job, and `GET /api/search/status` reports coverage. Auto-indexing is gated on `SEARCH_AUTO_INDEX` (default on).

## Agentic Ingest

One call, maximum value. `POST /api/ingest` takes a URL and a pipeline profile and drives it through every stage, with per-stage progress you can poll:

| Profile | Stages |
|---------|--------|
| `quick` | download + transcribe → search index → webhook |
| `deep` (default) | quick + knowledge extraction (claims/entities/topics) + LLM summary |
| `full` | deep + sentiment/heat analysis + viral clip suggestions |

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtu.be/...", "profile": "deep"}'

curl http://localhost:8000/api/jobs/<job_id>/pipeline   # stage-by-stage status
curl http://localhost:8000/api/pipelines                # list profiles
```

A transcription failure aborts the run; enrichment-stage failures (say, no LLM provider configured) are recorded on that stage and the rest continues. Stage results land where the rest of the app expects them — the transcript, search index, knowledge base, sentiment and clips endpoints all see pipeline-produced output.

**Intelligent webhooks:** the completion webhook can carry more than a status line. Pick a payload template — `minimal` (legacy), `summary` (adds the AI summary + key topics), or `full_intelligence` (adds entities, sentiment overview, and claim/prediction counts) — globally via the `WEBHOOK_TEMPLATE` setting or per job with `webhook_template` on `POST /api/ingest`. Payloads are assembled from already-extracted data, never a fresh LLM call. `GET /api/webhooks/templates` lists them.

## Ask Audio

Grounded Q&A on top of the semantic index. Answers come from the configured `chat` LLM preset (AI Settings), are restricted to retrieved transcript excerpts, and cite numbered sources with timestamps and speakers — if the transcript doesn't cover it, the answer says so instead of guessing.

```bash
# Ask one episode (with optional time-range scoping)
curl -X POST http://localhost:8000/api/jobs/<id>/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What did they say about the Fed rate hike?"}'

# Ask across your whole library
curl -X POST http://localhost:8000/api/ask \
  -d '{"question": "Who has been bullish on ETH this month?"}'

# Past Q&A
curl http://localhost:8000/api/jobs/<id>/chat-history
curl http://localhost:8000/api/ask/history
```

Every exchange is persisted (per-episode and library-wide histories are separate), and LLM spend counts against the same daily budget as knowledge extraction. Agents get the same capability through the MCP `ask_episode` / `ask_at_timestamp` tools.

## MCP Server

Sift ships an [MCP](https://modelcontextprotocol.io) server (`sift-mcp`) that exposes its primitives as tools to Claude Desktop, Cursor, and any MCP client. It's a thin HTTP client of the Sift REST API — point it at a local or remote Sift instance with `SIFT_API_URL` / `SIFT_API_KEY` (the key is sent as `X-API-Key`). The MCP process holds no database of its own.

**Tools (this release):** `ingest_url`, `get_transcript`, `get_segment`, `get_summary`, `get_chapters`, `get_clips`, `get_highlights`, `get_claims`, `get_entities`, `get_topics`, `get_predictions`, `export_to_vault`, `search_library`, `search_segments`, `ask_episode`, `ask_at_timestamp`. The knowledge tools (`get_claims`/`entities`/`topics`/`predictions`) read the P18 layer and return `status: "pending"` while extraction is still running — just retry. `export_to_vault` writes an Obsidian/Logseq note (P21). `search_library` semantically searches every indexed episode; `search_segments` scopes to one episode (P10). `ask_episode` answers questions grounded in one episode's transcript with cited timestamps; `ask_at_timestamp` scopes the answer to a time range (P11).

**Install & run** (needs a running Sift API — see [Web Mode](#web-mode-self-hosted-full-features)):

```bash
# from a checkout
uv sync --extra mcp
SIFT_API_URL=http://localhost:8000 SIFT_API_KEY=your-key uv run sift-mcp
```

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sift": {
      "command": "uv",
      "args": ["run", "sift-mcp"],
      "cwd": "/path/to/xdownloader",
      "env": {
        "SIFT_API_URL": "http://localhost:8000",
        "SIFT_API_KEY": "your-key"
      }
    }
  }
}
```

**Cursor** — add to `~/.cursor/mcp.json` (or the project's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "sift": {
      "command": "uv",
      "args": ["run", "sift-mcp"],
      "cwd": "/path/to/xdownloader",
      "env": { "SIFT_API_URL": "http://localhost:8000", "SIFT_API_KEY": "your-key" }
    }
  }
}
```

If Sift runs without `API_KEY` set (auth disabled), omit `SIFT_API_KEY`. The full knowledge schema the tools surface is documented in [`docs/knowledge-schema.md`](docs/knowledge-schema.md).

## Architecture & Vision

Sift is evolving from a media downloader into an **AI-First Intelligence Platform**. The core insight: users don't want files — they want the *knowledge* inside those files.

```
URL → Ingest → Transcribe → Understand → Search → Act
         │          │             │           │        │
       Download   Whisper    Summarize    Vector DB  Clips
       Metadata   Diarize    Sentiment    RAG Chat   Export
                  Enhance    Entities     Ask Audio   Webhook
```

The **[Agentic Pipeline](#agentic-ingest)** makes this entire chain automatic: paste a URL with a profile, and Sift handles the rest — downloading, transcribing, indexing, summarizing, and making the content queryable, with per-stage status you can poll.

### How the code is organized

Five layers, in dependency order. Each may import the ones above it, never the ones below:

```
sift_core        THE CORE — packages/sift-core (own package)
app/store/       SQLite persistence
app/knowledge/   claims, entities, topics, search, synthesis
app/delivery/    notes, clips, webhooks, cloud
app/pipeline/    workflows, queue, scheduler, subscriptions
app/api/         FastAPI routers · app/mcp_server/ · app/bot/
```

`sift_core` is the layer everything else is built on — getting media off a platform and turning it into a transcript. It ships as its own package so it runs with nothing above it installed, and it may not import the `app` package at all. `tests/test_layering.py` asserts this per file on every test run, rather than leaving it to discipline. See [Architecture](docs/architecture.md#layers).

## Documentation

- **API Docs**: http://localhost:8000/docs (Swagger UI — web mode)
- [Architecture](docs/architecture.md) - System design, download flow, module structure
- [Deployment](docs/deployment.md) - Docker, cloud, systemd setup
- [Diarization Setup](docs/diarization-setup.md) - Speaker identification
- [API Endpoints](docs/api-endpoints.md) - Internal API details
- [Queue & Scheduling](docs/queue-scheduling.md) - Batch downloads, priority queue, scheduling
- [Webhooks & Annotations](docs/webhooks-annotations.md) - Notifications and collaboration
- [Feature Roadmap](docs/todo.md) - Open work only
- [Shipped](docs/shipped.md) - Completed phases and the notes written when they landed

## Security

Sift is safe-by-default for **local, single-user** use. Before exposing it on a
network, set `API_KEY` (request auth) and `ENCRYPTION_KEY` (encrypts stored
provider keys at rest), and terminate TLS at a reverse proxy. The Docker Compose
setup requires `API_KEY` because the container binds `0.0.0.0`.

Found a vulnerability? Please report it privately — see [SECURITY.md](SECURITY.md).
Don't open a public issue.

## License

MIT
