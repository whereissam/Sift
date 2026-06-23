# Sift — Python Backend

FastAPI backend powering Sift's web/server mode. Provides the full feature set including download, transcription, LLM summarization, the AI knowledge layer (structured claims / entities / topics / predictions), cross-episode subscription digests, an MCP server, the Telegram bot, and more.

> **Note:** The [desktop app](../frontend/src-tauri/) uses a Rust backend instead. This Python backend is for self-hosted/web deployments.

## Quick Start

```bash
# From project root
uv sync --extra transcribe
uv run sift-api               # http://localhost:8000
```

API docs at http://localhost:8000/docs (Swagger UI).

## Entry Points

| Command | Script | Description |
|---------|--------|-------------|
| `uv run sift-api` | `app/main.py:main` | FastAPI server |
| `uv run sift-bot` | `app/bot/bot.py:run_bot` | Telegram bot (polling) |
| `uv run sift` | `app/cli.py:cli` | CLI tool |
| `uv run sift-mcp` | `app/mcp_server/__main__:main` | MCP server (P19) — exposes Sift to Claude Desktop / Cursor / agents |

## Module Structure

```
app/
├── main.py                  # FastAPI app, lifespan, middleware
├── config.py                # Pydantic Settings (.env loading)
├── cli.py                   # CLI interface
├── logging_config.py        # Structured logging (structlog)
│
├── api/                     # REST API routes (34 modules, 136 routes)
│   ├── __init__.py          # Router aggregation
│   ├── routes.py            # Health, readyz, platforms, quick-add
│   ├── download_routes.py   # POST /download, GET /download/{id}, file serving
│   ├── transcription_routes.py  # Whisper transcription
│   ├── transcript_fetch_routes.py # YouTube/Spotify caption fetching
│   ├── summarize_routes.py  # LLM summarization
│   ├── translation_routes.py    # TranslateGemma translation
│   ├── clip_routes.py       # Viral clip generation
│   ├── sentiment_routes.py  # Psychographic analysis
│   ├── extract_routes.py    # Structured data extraction
│   ├── knowledge_routes.py  # P18: /jobs/{id}/knowledge, extract-knowledge, /claims, backfill
│   ├── entity_routes.py     # P18: /entities, /entities/{id}/mentions
│   ├── topic_routes.py      # P18: /topics, /topics/{id}/claims, /topics/{id}/synthesis
│   ├── prediction_routes.py # P18: /predictions, resolve/revert
│   ├── digest_routes.py     # P20: /digests CRUD + run, cross-episode synthesis
│   ├── export_routes.py     # P21: /export-templates, /jobs/{id}/export (vault notes)
│   ├── job_management_routes.py # Job listing, retry, cleanup
│   ├── batch_routes.py      # Batch downloads
│   ├── schedule_routes.py   # Scheduled downloads
│   ├── subscription_routes.py   # RSS/YouTube subscriptions
│   ├── annotation_routes.py # Collaborative annotations + WebSocket
│   ├── realtime_routes.py   # Live transcription WebSocket
│   ├── webhook_routes.py    # Webhook configuration
│   ├── ai_settings_routes.py    # LLM provider settings
│   ├── storage_routes.py    # Storage management
│   ├── cloud_routes.py      # S3/GDrive/Dropbox upload
│   ├── obsidian_routes.py   # Obsidian export
│   ├── model_routes.py      # Whisper model management (desktop)
│   ├── schemas.py           # Pydantic request/response models
│   ├── auth.py              # API key verification
│   ├── middleware.py         # Timeout, request ID
│   └── ratelimit.py         # slowapi rate limiting
│
├── core/                    # Business logic
│   ├── base.py              # Platform enum, PlatformDownloader ABC, DownloadResult
│   ├── exceptions.py        # SiftError hierarchy
│   ├── downloader.py        # DownloaderFactory (URL → platform downloader)
│   ├── platforms/           # Per-platform downloaders (yt-dlp subprocess)
│   │   ├── xspaces.py      # X Spaces
│   │   ├── youtube.py       # YouTube audio
│   │   ├── youtube_video.py # YouTube video
│   │   ├── x_video.py       # X/Twitter video
│   │   ├── instagram_video.py   # Instagram Reels
│   │   ├── xiaohongshu_video.py # 小红书 video
│   │   ├── apple_podcasts.py    # Apple Podcasts
│   │   ├── spotify.py       # Spotify (spotDL)
│   │   ├── discord_audio.py # Discord CDN
│   │   └── xiaoyuzhou.py    # 小宇宙 podcast
│   ├── converter.py         # FFmpeg audio/video conversion
│   ├── transcriber.py       # Whisper transcription (faster-whisper)
│   ├── transcript_fetcher.py    # YouTube caption / Spotify Read Along
│   ├── realtime_transcriber.py  # Live streaming transcription
│   ├── summarizer.py        # LLM summarization (via litellm)
│   ├── translator.py        # TranslateGemma translation
│   ├── clip_generator.py    # AI viral clip detection
│   ├── clip_exporter.py     # FFmpeg clip extraction
│   ├── sentiment_analyzer.py    # Psychographic mapping
│   ├── extractor.py         # Structured data extraction
│   ├── enhancer.py          # Audio noise reduction (FFmpeg)
│   ├── diarizer.py          # Speaker diarization (pyannote)
│   ├── metadata_tagger.py   # ID3/MP4 tag embedding
│   ├── job_store/           # SQLite persistence (composed mixins)
│   │   ├── _store.py        #   JobStore class (composes the mixins below)
│   │   ├── _schema.py       #   table DDL + migrations
│   │   ├── _jobs.py         #   jobs CRUD + status
│   │   ├── _batches.py      #   batch operations
│   │   ├── _annotations.py  #   collaborative annotations
│   │   ├── _settings.py     #   ai_settings / task presets
│   │   ├── _knowledge.py    #   claims / entities / topics / predictions (P18)
│   │   ├── _backfill.py     #   knowledge backfill state machine + locks (P18 C.3)
│   │   ├── _digest.py       #   digest configs + runs (P20)
│   │   └── _crypto.py       #   field encryption (Fernet)
│   │
│   │ # ── AI Knowledge Layer (P18) ──
│   ├── llm_presets.py       # Task-based LLM provider resolution (extract/summarize/synthesize/chat)
│   ├── knowledge_extractor.py   # LLM claim/entity extraction (JSON mode)
│   ├── knowledge_schema.py  # Claim / Entity / Topic / Prediction Pydantic models
│   ├── knowledge_backfill.py    # Background backfill worker + on-demand path
│   ├── knowledge_budget.py  # Per-UTC-day LLM spend tracker + guardrails
│   ├── embedding_store.py   # Generic embeddings table + cosine search
│   ├── entity_canonicalizer.py  # Cross-episode entity dedup (cosine ≥ 0.85)
│   ├── topic_aggregator.py  # Second-pass topic clustering over claims
│   ├── topic_canonicalizer.py   # Cross-episode topic dedup (cosine ≥ 0.90)
│   ├── topic_normalization.py   # Lexical topic normalization
│   ├── prediction_extractor.py  # Prediction lifecycle enrichment
│   │
│   │ # ── Digest Pipeline (P20) ──
│   ├── digest_schema.py     # DigestSynthesis models + markdown renderer
│   ├── digest_synthesizer.py    # Cross-episode synthesis engine (synthesize preset)
│   ├── digest_runner.py     # Scheduled digest worker + run_digest
│   ├── digest_runner_helpers.py # Claim gathering across a subscription window
│   ├── note_exporter.py     # P21: Obsidian/Logseq/markdown note templater + vault writer
│   │
│   ├── queue_manager.py     # Priority download queue
│   ├── batch_manager.py     # Batch download operations
│   ├── scheduler.py         # Scheduled download worker
│   ├── subscription_store.py    # SQLite subscription storage
│   ├── subscription_fetcher.py  # RSS/YouTube feed fetcher
│   ├── subscription_worker.py   # Background subscription worker
│   ├── webhook_notifier.py  # Webhook delivery with retry
│   ├── websocket_manager.py # Real-time annotation updates
│   ├── storage_manager.py   # Disk space management
│   ├── obsidian_exporter.py # Obsidian vault export
│   ├── url_validator.py     # SSRF allowlist + DNS-pinning transport
│   ├── client.py            # Twitter HTTP client (httpx)
│   ├── auth.py              # Twitter authentication
│   ├── parser.py            # URL parsing utilities
│   ├── checkpoint.py        # Download checkpoint/resume
│   ├── retry.py             # Tenacity retry decorators
│   └── workflow.py          # Multi-step pipeline orchestration (auto-enqueues knowledge extraction)
│
├── mcp_server/              # MCP server (P19) — HTTP client of the Sift API
│   ├── __main__.py          # `sift-mcp` entry point (stdio transport)
│   ├── server.py            # FastMCP tool definitions
│   ├── client.py            # Async Sift API client (X-API-Key passthrough)
│   └── config.py            # SIFT_API_URL / SIFT_API_KEY env config
│
└── bot/                     # Telegram bot
    └── bot.py               # python-telegram-bot handlers
```

## Configuration

All config via environment variables or `.env` file. See `app/config.py` for the full list.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8000` | Server port |
| `DOWNLOAD_DIR` | `./output` | Download directory |
| `DEBUG` | `false` | Enable debug mode / auto-reload |
| `API_KEY` | (none) | API authentication (optional) |
| `LLM_PROVIDER` | `ollama` | LLM backend (ollama/openai/anthropic/groq/deepseek/gemini) |
| `WHISPER_SERVICE_URL` | (none) | Remote Whisper service URL |

## Optional Dependencies

```bash
uv sync                     # Core only (download + API)
uv sync --extra transcribe  # + Whisper transcription
uv sync --extra diarize     # + Speaker diarization (pyannote + torch)
uv sync --extra cloud       # + Cloud storage (S3, GDrive, Dropbox)
uv sync --extra mcp         # + MCP server (sift-mcp)
uv sync --extra dev         # + Testing & linting
```

## Testing

```bash
uv run pytest               # Run all tests
uv run ruff check .         # Lint
```
