# AudioGrab - Frontend

<p align="center">
  <img src="public/logo.svg" alt="AudioGrab" width="200">
</p>

Modern React frontend for downloading, transcribing, and analyzing audio from X Spaces, YouTube, Apple Podcasts, Spotify, and more.

This directory contains **two things**:

| Directory | What | Runtime |
|-----------|------|---------|
| `src/` | React frontend (shared UI) | Browser / Tauri webview |
| `src-tauri/` | Native desktop app + Rust backend | macOS / Windows / Linux |

The React code in `src/` is **shared** — it runs identically in both web and desktop mode.

---

## 1. Web Mode

The frontend runs as a standard Vite dev server and talks to a **Python FastAPI backend** via proxy.

### Prerequisites

- Bun (or Node.js 20+)

### Setup

```bash
bun install
bun run dev       # http://localhost:5173
```

Make sure the Python backend is running at http://localhost:8000:
```bash
# From project root
uv run audiograb-api
```

### Build for production

```bash
bun run build     # Output in dist/
bun run preview   # Preview the build
```

### How it connects

Vite proxies `/api` requests to `http://localhost:8000` (configured in `vite.config.ts`). The frontend uses relative URLs like `POST /api/download`.

---

## 2. Desktop App (Tauri + Rust)

A native macOS/Windows/Linux app. The Rust backend is **embedded** — no Python, no separate server.

### Prerequisites

- [Rust](https://rustup.rs/)
- [Bun](https://bun.sh/)
- yt-dlp and ffmpeg in PATH

### Development

```bash
# From project root
make dev
```

This launches Tauri with hot-reload for both the React frontend and the Rust backend.

### Build installer

```bash
# From project root
make desktop
```

Output:
| Platform | Format | Location |
|----------|--------|----------|
| macOS | `.dmg` | `src-tauri/target/release/bundle/dmg/` |
| Windows | `.msi` | `src-tauri/target/release/bundle/msi/` |
| Linux | `.deb` | `src-tauri/target/release/bundle/deb/` |

### How it connects

The Tauri app starts an **axum HTTP server** on `localhost:8000` inside the same process. The React frontend detects Tauri via `window.__TAURI__` and hits the server directly (no Vite proxy). The `useTauriBackend` hook handles this automatically.

### Desktop-specific files

```
src/
├── hooks/useTauriBackend.ts     # Detects Tauri, manages backend readiness
└── components/DesktopSplash.tsx  # Loading screen while backend starts
```

### Rust backend structure

```
src-tauri/
├── Cargo.toml              # Rust dependencies (axum, rusqlite, tokio, etc.)
├── tauri.conf.json          # Window config, bundle settings, CSP
├── capabilities/default.json # Permissions (shell, process, dialog)
└── src/
    ├── main.rs              # Entry point
    ├── lib.rs               # Tauri setup, starts axum server on :8000
    └── backend/
        ├── mod.rs           # Server startup + CORS
        ├── types.rs         # Platform, DownloadJob, DownloadRequest, etc.
        ├── platform.rs      # URL → platform detection (10 platforms)
        ├── downloader.rs    # yt-dlp subprocess with --concurrent-fragments 16
        ├── routes.rs        # API routes (health, download, jobs, queue, file serving)
        └── db.rs            # SQLite job persistence (rusqlite)
```

### Desktop vs Web feature comparison

| Feature | Desktop (Rust) | Web (Python) |
|---------|---------------|-------------|
| Download (all 10 platforms) | Yes | Yes |
| Parallel HLS fragments (16x) | Yes | Yes |
| Job management + SQLite | Yes | Yes |
| Transcription (Whisper) | Planned | Yes |
| LLM Summarization | Planned | Yes |
| Telegram Bot | No | Yes |
| Subscriptions/RSS | Planned | Yes |
| Bundle size | ~15 MB | N/A (server) |

---

## Shared: Project Structure

```
src/
├── components/
│   ├── ui/              # shadcn/ui components (Button, Input, Tabs)
│   ├── downloader/      # Download & transcription components
│   │   ├── DownloadForm.tsx
│   │   ├── TranscribeForm.tsx
│   │   ├── SuccessViews.tsx
│   │   └── types.ts
│   ├── clips/           # Viral clip generation
│   ├── live/            # Real-time transcription
│   ├── settings/        # AI & translation settings
│   ├── subscriptions/   # Subscription management
│   └── DesktopSplash.tsx # Desktop loading screen
├── hooks/
│   ├── useAudioCapture.ts          # MediaRecorder API
│   ├── useRealtimeTranscription.ts # WebSocket for live transcription
│   ├── useSwipeGesture.ts          # Touch gestures
│   └── useTauriBackend.ts          # Desktop backend detection
├── lib/
│   └── utils.ts
├── routes/              # File-based routing (TanStack Router)
│   ├── __root.tsx       # Root layout with navigation
│   ├── audio.tsx        # /audio — Audio download
│   ├── video.tsx        # /video — Video download
│   ├── transcribe.tsx   # /transcribe — Transcription
│   ├── live.tsx         # /live — Real-time transcription
│   ├── clips.tsx        # /clips — Viral clips
│   ├── settings.tsx     # /settings — Configuration
│   └── subscriptions.tsx # /subscriptions
├── main.tsx
└── index.css
```

## Supported Platforms

| Platform | Audio | Video | Transcribe |
|----------|-------|-------|------------|
| X Spaces | M4A, MP3 | - | Yes |
| X/Twitter | - | MP4 | Yes |
| YouTube | M4A, MP3 | MP4 | Yes |
| Apple Podcasts | M4A, MP3 | - | Yes |
| Spotify | MP3, M4A | - | Yes |
| 小宇宙 | M4A, MP3 | - | Yes |
| Instagram | - | MP4 | Yes |
| 小红书 | - | MP4 | Yes |

## API Endpoints

Both web and desktop backends serve the same API shape:

### Core (available in both modes)

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `POST /api/download` | Start download job |
| `GET /api/download/{job_id}` | Get job status |
| `GET /api/download/{job_id}/file` | Download completed file |
| `DELETE /api/download/{job_id}` | Cancel/delete job |
| `GET /api/jobs` | List all jobs |
| `GET /api/queue` | Queue status |
| `GET /api/add?url=...` | Quick add (browser extension) |

### Web mode only (Python backend)

| Endpoint | Description |
|----------|-------------|
| `POST /api/transcribe` | Start transcription |
| `POST /api/transcribe/upload` | Upload file & transcribe |
| `WS /api/transcribe/live` | Live transcription WebSocket |
| `POST /api/summarize/{job_id}` | LLM summarization |
| `POST /api/translate` | Translation |
| `POST /api/subscriptions` | RSS/YouTube subscriptions |
| `POST /api/jobs/{id}/clips` | Viral clip generation |

## License

MIT
