# sift-core

The ingestion core of [Sift](../../README.md): download audio and video from
X Spaces, Apple Podcasts, Spotify, YouTube, Discord, Instagram, 小红书, 小宇宙
and 喜马拉雅, convert it, and transcribe it. It has no server, database, or bot —
those live in the `sift` app, which is built on this package.

System tools: `ffmpeg` for conversion, and `spotdl` on `PATH` for Spotify music
(episodes don't need it). `yt-dlp` is installed as a dependency.

## Library

```python
import asyncio
from sift_core import IngestSettings, download_audio

settings = IngestSettings(download_dir="./downloads")
result = asyncio.run(download_audio("https://podcasts.apple.com/...", settings=settings))
print(result.file_path)
```

Leave `settings` out to read the same environment variables / `.env` as the app
(`DOWNLOAD_DIR`, `TWITTER_AUTH_TOKEN`, `YOUTUBE_COOKIES_FROM_BROWSER`, ...).

## CLI

```bash
sift download "https://podcasts.apple.com/..." -f mp3
sift convert episode.m4a -f mp3
sift to-video episode.m4a
```

## Extras

- `sift-core[transcribe]` — local Whisper transcription
- `sift-core[diarize]` — speaker diarization (pyannote)
