# Sift

<p align="center">
  <img src="frontend/public/logo.svg" alt="Sift" width="200">
</p>

**AI-First Knowledge Extraction Platform.** Ingest audio and video from X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, and more — then extract, search, and reason over the knowledge inside.

> Downloading is just the first step. Sift turns media into searchable, queryable intelligence.

## Features

### Ingest & Extract
- **Multi-Platform Ingest** - X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, 小宇宙
- **Video Downloads** - X/Twitter, YouTube, Instagram, 小红书 (480p/720p/1080p)
- **Transcription** - Local Whisper or API models (OpenAI, Groq, etc.), 99+ languages
- **Fetch Transcript** - Instantly grab existing YouTube captions or Spotify Read Along transcripts (no Whisper needed)
- **Live Transcription** - Real-time microphone transcription via WebSocket
- **Smart Metadata** - Auto-embed ID3/MP4 tags with artwork

### Understand & Analyze
- **Knowledge Extraction** - Structured, citable claims (fact / opinion / prediction / question / recommendation) with timestamps, speaker attribution, and confidence scores. Canonical entities (people, companies, tickers, projects) and topic clusters are resolved across episodes so the same concept collapses to one node in the graph. Prediction claims get lifecycle metadata (target horizon, conditions, falsifier) and a resolve / revert API for tracking accuracy over time. Queryable across your library via `/api/claims`, `/api/entities`, `/api/topics`, and `/api/predictions`. Newly transcribed episodes are **auto-queued for extraction** the moment a transcript completes (toggle with `knowledge_auto_extract`), so the knowledge base stays current with no manual step. Extraction also runs **on demand** (a `GET /api/jobs/{id}/knowledge` on an un-extracted job runs inline for short transcripts, or returns `202` and queues longer ones) and via a **background backfill worker** that processes the back catalogue under a claim-lock with per-day cost guardrails (daily budget + automatic model downgrade); enqueue with `POST /api/jobs/{id}/knowledge/enqueue` and watch progress at `GET /api/knowledge/backfill-status`. The full schema contract lives in [`docs/knowledge-schema.md`](docs/knowledge-schema.md).
- **Ask Audio (RAG)** - Chat with your downloads — ask questions, get answers with timestamps (coming soon)
- **Semantic Search** - Search your entire library by concept, not just keywords, via vector embeddings (coming soon)
- **Psychographic Mapping** - Emotional heatmap timeline with AI-powered reasoning: detect heated moments, explain *why* they're heated, and spot contradictions across a conversation
- **LLM Summarization** - Bullet points, chapter markers, key topics, action items via any AI provider
- **Speaker Diarization** - Identify different speakers (optional)
- **Contradiction Detection** - AI cross-references statements across the transcript to surface inconsistencies (coming soon)

### Transform & Create
- **Translation** - TranslateGemma (local) or AI providers, 55+ languages
- **Social Media Clips** - AI identifies viral-worthy moments, generates captions & hashtags
- **Audio Enhancement** - Noise reduction & voice isolation (FFmpeg-based), neural voice reconstruction on the roadmap
- **Content Distiller** - Feed multiple URLs and get a single synthesized briefing (coming soon)

### Automate & Integrate
- **Vault & Note-App Export** - Turn any episode into a templated markdown note for **Obsidian / Logseq / plain markdown** — YAML frontmatter, clickable timestamp links, claim cards, pull-quote highlights, a collapsible transcript, and `[[wikilinks]]` for canonical entities. Served over the API and the MCP `export_to_vault` tool. See [Vault Export](#vault--note-app-export).
- **Subscription Digests (Cross-Episode Synthesis)** - Define a digest over a set of subscriptions and Sift generates a scheduled cross-source brief: what several episodes agreed on, where they disagreed, repeated narratives, and predictions worth tracking. The differentiator over single-episode summaries is reading *across* sources. Also on-demand per-topic synthesis. See [Subscription Digests](#subscription-digests).
- **MCP Server (Capability Surface)** - Expose Sift to Claude Desktop, Cursor, and custom agents as MCP tools (`ingest_url`, `get_transcript`, `get_claims`, `get_entities`, `get_topics`, `get_predictions`, …). One server, N agent skills. See [MCP Server](#mcp-server) below.
- **Agentic Ingest Pipeline** - Paste a URL and Sift auto-triggers summarization, entity extraction, and search indexing (coming soon)
- **Telegram Research Assistant** - Send a link, then ask questions about the content — the bot answers instantly
- **Intelligent Webhooks** - Notifications include AI-generated summaries, key findings, and detected insights (coming soon)
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
uv run sift "https://x.com/i/spaces/1vOxwdyYrlqKB"
uv run sift "https://youtube.com/watch?v=xxx" -f mp3
uv run sift "https://podcasts.apple.com/..." -q highest
```

## API

Full API documentation available at http://localhost:8000/docs (Swagger UI)

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

### Video
| Platform | URL Pattern |
|----------|-------------|
| X/Twitter | `x.com/user/status/...` |
| YouTube | `youtube.com/watch?v=...` |
| Instagram | `instagram.com/reel/...`, `instagram.com/p/...` |
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

# Optional
HUGGINGFACE_TOKEN=hf_xxx  # For speaker diarization

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

### API Authentication

By default, the API is open (no auth required) - suitable for local/self-hosted use.

To enable authentication, set `API_KEY` in `.env`:

```bash
# .env
API_KEY=my-secret-key

# Then include header in requests
curl -H "X-API-Key: my-secret-key" http://localhost:8000/api/health
```

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

## MCP Server

Sift ships an [MCP](https://modelcontextprotocol.io) server (`sift-mcp`) that exposes its primitives as tools to Claude Desktop, Cursor, and any MCP client. It's a thin HTTP client of the Sift REST API — point it at a local or remote Sift instance with `SIFT_API_URL` / `SIFT_API_KEY` (the key is sent as `X-API-Key`). The MCP process holds no database of its own.

**Tools (this release):** `ingest_url`, `get_transcript`, `get_segment`, `get_summary`, `get_chapters`, `get_clips`, `get_highlights`, `get_claims`, `get_entities`, `get_topics`, `get_predictions`, `export_to_vault`. The knowledge tools (`get_claims`/`entities`/`topics`/`predictions`) read the P18 layer and return `status: "pending"` while extraction is still running — just retry. `export_to_vault` writes an Obsidian/Logseq note (P21). Q&A and library-wide semantic search are not yet exposed (they await P10/P11).

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

The **Agentic Pipeline** (on the roadmap) will make this entire chain automatic: paste a URL, and Sift handles the rest — downloading, transcribing, indexing, summarizing, and making the content queryable.

## Documentation

- **API Docs**: http://localhost:8000/docs (Swagger UI — web mode)
- [Architecture](docs/architecture.md) - System design, download flow, module structure
- [Deployment](docs/deployment.md) - Docker, cloud, systemd setup
- [Diarization Setup](docs/diarization-setup.md) - Speaker identification
- [API Endpoints](docs/api-endpoints.md) - Internal API details
- [Queue & Scheduling](docs/queue-scheduling.md) - Batch downloads, priority queue, scheduling
- [Webhooks & Annotations](docs/webhooks-annotations.md) - Notifications and collaboration
- [Feature Roadmap](docs/todo.md) - Full v1.x and v2.0 AI-Native roadmap

## Security

Sift is safe-by-default for **local, single-user** use. Before exposing it on a
network, set `API_KEY` (request auth) and `ENCRYPTION_KEY` (encrypts stored
provider keys at rest), and terminate TLS at a reverse proxy. The Docker Compose
setup requires `API_KEY` because the container binds `0.0.0.0`.

Found a vulnerability? Please report it privately — see [SECURITY.md](SECURITY.md).
Don't open a public issue.

## License

MIT
