# AudioGrab

<p align="center">
  <img src="frontend/public/logo.svg" alt="AudioGrab" width="200">
</p>

**AI-First Knowledge Extraction Platform.** Ingest audio and video from X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, and more — then extract, search, and reason over the knowledge inside.

> Downloading is just the first step. AudioGrab turns media into searchable, queryable intelligence.

## Features

### Ingest & Extract
- **Multi-Platform Ingest** - X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, 小宇宙
- **Video Downloads** - X/Twitter, YouTube, Instagram, 小红书 (480p/720p/1080p)
- **Transcription** - Local Whisper or API models (OpenAI, Groq, etc.), 99+ languages
- **Fetch Transcript** - Instantly grab existing YouTube captions or Spotify Read Along transcripts (no Whisper needed)
- **Live Transcription** - Real-time microphone transcription via WebSocket
- **Smart Metadata** - Auto-embed ID3/MP4 tags with artwork

### Understand & Analyze
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
- **Agentic Ingest Pipeline** - Paste a URL and AudioGrab auto-triggers summarization, entity extraction, and search indexing (coming soon)
- **Telegram Research Assistant** - Send a link, then ask questions about the content — the bot answers instantly
- **Intelligent Webhooks** - Notifications include AI-generated summaries, key findings, and detected insights (coming soon)
- **Subscriptions** - Auto-monitor RSS feeds, YouTube channels, and playlists
- **Batch Downloads** - Download multiple URLs at once with progress tracking
- **Priority Queue** - Prioritize important downloads (1-10 levels)
- **Scheduled Downloads** - Schedule downloads for specific times
- **Job Recovery** - SQLite persistence, auto-resume on restart
- **Collaborative Annotations** - Add comments to transcripts with real-time sync

## Quick Start

### Desktop App (recommended)

```bash
git clone https://github.com/yourusername/audiograb.git
cd audiograb

# Install system dependencies (macOS)
brew install ffmpeg yt-dlp

# Build and run the desktop app
make desktop    # Builds .dmg (macOS) / .msi (Windows) / .deb (Linux)
```

### Web Mode (self-hosted)

```bash
git clone https://github.com/yourusername/audiograb.git
cd audiograb
uv sync --extra transcribe
brew install ffmpeg yt-dlp

# Run (two terminals)
uv run audiograb-api          # Backend: http://localhost:8000
cd frontend && bun run dev    # Frontend: http://localhost:5173
```

## CLI Usage

```bash
uv run audiograb "https://x.com/i/spaces/1vOxwdyYrlqKB"
uv run audiograb "https://youtube.com/watch?v=xxx" -f mp3
uv run audiograb "https://podcasts.apple.com/..." -q highest
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
uv run audiograb-bot  # Polling mode (local dev)
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

# API Authentication (optional)
# API_KEY=your-secret-key  # If set, requires X-API-Key header

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

## Build

### Desktop App

Native desktop app — **pure Rust backend** (~15 MB) with Tauri v2. No Python required.

**Prerequisites:** [Rust](https://rustup.rs/), [Bun](https://bun.sh/), yt-dlp, ffmpeg

```bash
# Install system deps (macOS)
brew install yt-dlp ffmpeg

# Build the desktop app
make desktop
```

**Output:**
| Platform | Installer | Location |
|----------|-----------|----------|
| macOS | `.dmg` | `frontend/src-tauri/target/release/bundle/dmg/` |
| Windows | `.msi` | `frontend/src-tauri/target/release/bundle/msi/` |
| Linux | `.deb` | `frontend/src-tauri/target/release/bundle/deb/` |

**Dev mode** (hot-reload for both frontend and Rust backend):
```bash
make dev
```

### Web Server (self-hosted)

Full-featured Python backend with transcription, LLM summarization, Telegram bot.

**Prerequisites:** Python 3.10+, [uv](https://github.com/astral-sh/uv), [Bun](https://bun.sh/), yt-dlp, ffmpeg

```bash
# Install Python deps
uv sync --extra transcribe

# Run both backend + frontend
make dev-web

# Or run separately:
make dev-backend    # Python API on :8000
make dev-frontend   # Vite on :5173
```

### Docker

```bash
docker-compose up -d    # API + Frontend + Whisper + Ollama
```

See [Deployment Guide](docs/deployment.md) for Docker, cloud, and systemd setup.

### Desktop Architecture

The desktop app embeds an **axum HTTP server** (Rust) that replaces the Python FastAPI backend. It starts on `localhost:8000` inside the Tauri process — the React frontend talks to it the same way as in web mode.

- **Download engine**: Calls yt-dlp as a subprocess with `--concurrent-fragments 16`
- **Job persistence**: SQLite via rusqlite
- **Bundle size**: ~15 MB (vs ~300 MB with Python)

## Architecture & Vision

AudioGrab is evolving from a media downloader into an **AI-First Intelligence Platform**. The core insight: users don't want files — they want the *knowledge* inside those files.

```
URL → Ingest → Transcribe → Understand → Search → Act
         │          │             │           │        │
       Download   Whisper    Summarize    Vector DB  Clips
       Metadata   Diarize    Sentiment    RAG Chat   Export
                  Enhance    Entities     Ask Audio   Webhook
```

The **Agentic Pipeline** (on the roadmap) will make this entire chain automatic: paste a URL, and AudioGrab handles the rest — downloading, transcribing, indexing, summarizing, and making the content queryable.

## Documentation

- **API Docs**: http://localhost:8000/docs (Swagger UI — web mode)
- [Architecture](docs/architecture.md) - System design, download flow, module structure
- [Deployment](docs/deployment.md) - Docker, cloud, systemd setup
- [Diarization Setup](docs/diarization-setup.md) - Speaker identification
- [API Endpoints](docs/api-endpoints.md) - Internal API details
- [Queue & Scheduling](docs/queue-scheduling.md) - Batch downloads, priority queue, scheduling
- [Webhooks & Annotations](docs/webhooks-annotations.md) - Notifications and collaboration
- [Feature Roadmap](docs/todo.md) - Full v1.x and v2.0 AI-Native roadmap

## License

MIT
