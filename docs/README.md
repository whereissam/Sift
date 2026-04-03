# Sift Backend

A Python backend service for downloading audio and video from X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, and more.

## Overview

This project provides:
- **CLI Tool**: Download audio/video and convert formats
- **Core Library**: Python module for programmatic access
- **FastAPI Backend**: REST API for web integrations
- **Real-Time Transcription**: WebSocket-based live audio transcription from microphone
- **Telegram Bot**: Download, format selection, and transcription via Telegram (all 10 platforms, polling + webhook modes)

## How It Works

The downloader uses **yt-dlp** under the hood, which handles:
1. Extracting Space ID from URL
2. Fetching metadata via Twitter's GraphQL API
3. Getting the m3u8 stream URL
4. Downloading and merging HLS segments with FFmpeg

```
URL → yt-dlp → GraphQL API → m3u8 playlist → FFmpeg → audio file
```

## Quick Start

```bash
# Install dependencies
uv sync

# Download a Space (no auth needed for public Spaces)
uv run xdownloader https://x.com/i/spaces/1vOxwdyYrlqKB

# Download as MP3
uv run xdownloader download -f mp3 https://x.com/i/spaces/...

# Convert existing file
uv run xdownloader convert -f mp3 space.m4a
uv run xdownloader convert -f mp4 space.m4a
```

## Requirements

- Python 3.10+
- FFmpeg (for audio processing)
- yt-dlp (for downloading)

Install on macOS:
```bash
brew install ffmpeg yt-dlp
```

## Features

### Real-Time Transcription

Transcribe audio from your browser microphone in real-time:

```
Browser Microphone → WebSocket → faster-whisper → Live Transcript
```

- **WebSocket streaming** at `/api/transcribe/live`
- **Context-aware transcription** using recent text as prompt
- **Smart segment merging** to handle chunk boundaries
- **Optional LLM polish** for cleaner output (requires AI provider)

Access via the `/live` route in the web UI.

### Fetch Transcript

Instantly grab existing transcripts from YouTube captions or Spotify Read Along — no Whisper processing needed. The fetched transcript is stored in the same format as Whisper results, so all downstream features (summarize, translate, sentiment analysis, Obsidian export) work unchanged.

#### YouTube

Works out of the box. When you paste a YouTube URL in the Transcribe page, it automatically detects available captions and lets you fetch them. Prefers manual (human-made) captions over auto-generated ones. Supports language selection when multiple caption tracks are available.

**API endpoints:**
- `GET /api/transcript/check?url=...` — check if transcript is available, list languages
- `POST /api/transcript/fetch` — fetch the transcript and return a completed job

#### Spotify

Requires a `sp_dc` cookie for authentication. To get it:

1. Open [https://open.spotify.com](https://open.spotify.com) in your browser and log in
2. Open DevTools (`F12` or `Cmd+Shift+I`)
3. Go to **Application** tab (Chrome) or **Storage** tab (Firefox)
4. Expand **Cookies** → click `https://open.spotify.com`
5. Find the cookie named **`sp_dc`** and copy its value
6. Add to your `.env`:
   ```env
   SPOTIFY_SP_DC=your-copied-value-here
   ```

> **Note:** The `sp_dc` cookie expires periodically (usually every few weeks/months). If fetching stops working, repeat the steps above to get a fresh value.

#### Known issues

- **Spotify regional blocking:** Spotify's CDN (`open.spotify.com/get_access_token`) blocks requests from certain regions (notably Japan and some cloud provider IPs). If you see a 403 error when fetching Spotify transcripts, try using a VPN to a US or EU region. This is a Spotify-side restriction, not a bug in Sift.
- **YouTube IP blocking:** YouTube may block transcript requests from IPs that make too many requests, or from cloud provider IPs. If you encounter `RequestBlocked` errors, try again later or use a different IP/proxy.

## Documentation

- [Architecture Details](./architecture.md) (includes real-time transcription flow)
- [Deployment Guide](./deployment.md)
- [API Reference](./api-endpoints.md) (REST & WebSocket endpoints)
- [Authentication Guide](./authentication.md) (for private Spaces)
- [Queue & Scheduling](./queue-scheduling.md) (batch downloads, priority queue)
- [Webhooks & Annotations](./webhooks-annotations.md) (notifications, collaboration)

## License

MIT
