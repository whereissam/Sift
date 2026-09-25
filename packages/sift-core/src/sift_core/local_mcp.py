"""Local MCP server over the ingestion core: ``sift-core-mcp``.

The app's ``sift-mcp`` is an HTTP client of a running Sift server (jobs,
knowledge, search). This one needs no server and no database: every tool calls
`sift_core` in-process, so an agent can download, read metadata, pull existing
captions, and transcribe with nothing but ``pip install 'sift-core[mcp]'``.

Every tool returns a JSON object with ``ok``; on failure ``ok`` is false and
``error`` says why, instead of raising — an agent can read and act on that.
Transcripts can run to hours, so text is capped by ``max_chars`` and segments
are only included on request.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from .exceptions import SiftError
from .fetch.downloader import DownloaderFactory, download_audio, get_metadata
from .fetch.transcript_fetcher import TranscriptFetcher
from .settings import IngestSettings, get_ingest_settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 100_000

SERVER_INSTRUCTIONS = (
    "Local media ingestion: no server, no database. Call `capabilities` first "
    "to see which platforms and transcription engines are installed. To get a "
    "transcript, try `fetch_transcript` first — YouTube and Spotify often have "
    "captions already, which is instant and free — and fall back to "
    "`transcribe`, which downloads the audio and runs speech-to-text locally "
    "(slow for long episodes). `download` saves the audio and returns its path. "
    "Every tool returns `ok`; when it is false, read `error`."
)


def _jsonable(value: Any) -> Any:
    """Dataclasses, enums, paths, and datetimes → plain JSON values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _failure(error: str, **extra: Any) -> dict:
    return {"ok": False, "error": error, **extra}


def _transcript_payload(
    text: Optional[str],
    segments: Optional[list],
    *,
    include_segments: bool,
    max_chars: int,
    **fields: Any,
) -> dict:
    text = text or ""
    payload: dict[str, Any] = {
        "ok": True,
        **fields,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "total_chars": len(text),
        "segment_count": len(segments or []),
    }
    if include_segments:
        payload["segments"] = _jsonable(segments or [])
    return payload


def build_server(settings: Optional[IngestSettings] = None):
    """A configured ``FastMCP`` whose tools call the core directly.

    ``settings`` controls the download dir and platform cookies for every tool;
    leave it out to read env / ``.env`` like the rest of the core.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - depends on the extra
        raise RuntimeError(
            "The local MCP server needs the `mcp` extra: pip install 'sift-core[mcp]'"
        ) from e

    def _settings() -> IngestSettings:
        return settings or get_ingest_settings()

    server = FastMCP("sift-core", instructions=SERVER_INSTRUCTIONS)

    @server.tool()
    async def capabilities() -> dict:
        """Which platforms can be downloaded and which transcription engines
        are installed on this machine."""
        from .platforms import DOWNLOADERS
        from .transcribe.transcription_engine import get_available_engines

        return {
            "ok": True,
            "platforms": [
                {"platform": cls.PLATFORM.value, "available": cls.is_available()}
                for cls in DOWNLOADERS
            ],
            "transcription_engines": [
                {"engine": info.engine.value, "name": info.name, "available": info.available}
                for info in get_available_engines()
            ],
            "caption_fetch_platforms": ["youtube", "spotify"],
            "download_dir": str(_settings().get_download_path()),
        }

    @server.tool(name="get_metadata")
    async def get_metadata_tool(url: str) -> dict:
        """Title, creator, duration and more for a URL, without downloading."""
        platform = DownloaderFactory.detect_platform(url)
        if platform is None:
            return _failure(f"Unsupported URL: {url}")
        try:
            metadata = await get_metadata(url, settings=_settings())
        except SiftError as e:
            return _failure(str(e), platform=platform.value)
        if metadata is None:
            return _failure("No metadata found for this URL", platform=platform.value)
        return {"ok": True, "platform": platform.value, "metadata": _jsonable(metadata)}

    @server.tool()
    async def download(
        url: str,
        format: Literal["m4a", "mp3", "mp4"] = "m4a",
        quality: Literal["low", "medium", "high", "highest"] = "high",
    ) -> dict:
        """Download audio (or video, for video platforms) to the local download
        directory and return the file path. Long episodes take a while."""
        if DownloaderFactory.detect_platform(url) is None:
            return _failure(f"Unsupported URL: {url}")
        try:
            result = await download_audio(
                url, output_format=format, quality=quality, settings=_settings()
            )
        except SiftError as e:
            return _failure(str(e))
        if not result.success:
            return _failure(result.error or "Download failed")
        return {
            "ok": True,
            "file_path": str(result.file_path),
            "file_size_bytes": result.file_size_bytes,
            "metadata": _jsonable(result.metadata),
        }

    @server.tool()
    async def fetch_transcript(
        url: str,
        language: Optional[str] = None,
        include_segments: bool = False,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """Existing captions for a YouTube video or Spotify episode — instant,
        no audio download. Fails on other platforms; use `transcribe` there."""
        fetcher = TranscriptFetcher(settings=_settings())
        if not fetcher.can_fetch_transcript(url):
            return _failure(
                "Captions can only be fetched from YouTube or Spotify; use `transcribe`"
            )
        fetched = await fetcher.fetch_transcript(url, language=language)
        if not fetched.success:
            return _failure(fetched.error or "No transcript available")
        return _transcript_payload(
            fetched.text,
            fetched.segments,
            include_segments=include_segments,
            max_chars=max_chars,
            source=fetched.source,
            language=fetched.language,
            duration_seconds=fetched.duration_seconds,
        )

    @server.tool()
    async def transcribe(
        source: str,
        language: Optional[str] = None,
        engine: Optional[Literal["whisper", "sensevoice", "apple", "cloud"]] = None,
        include_segments: bool = False,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """Speech-to-text on a URL (downloaded first) or a local audio file.
        Picks the best installed engine unless `engine` is given. Slow: roughly
        real-time or faster depending on the engine and hardware."""
        from .transcribe.transcription_engine import (
            TranscriptionEngine,
            get_best_engine,
            get_engine,
        )

        if source.startswith(("http://", "https://")):
            if DownloaderFactory.detect_platform(source) is None:
                return _failure(f"Unsupported URL: {source}")
            try:
                result = await download_audio(source, settings=_settings())
            except SiftError as e:
                return _failure(str(e))
            if not result.success:
                return _failure(result.error or "Download failed")
            audio_path = Path(result.file_path)
        else:
            audio_path = Path(source).expanduser()
            if not audio_path.is_file():
                return _failure(f"File not found: {audio_path}")

        chosen = TranscriptionEngine(engine) if engine else get_best_engine(language)
        backend = get_engine(chosen)
        if not backend.is_available():
            return _failure(
                f"Transcription engine '{chosen.value}' is not installed. "
                "Install local Whisper with: pip install 'sift-core[transcribe]'",
                audio_path=str(audio_path),
            )

        transcribed = await backend.transcribe(audio_path, language=language)
        if not transcribed.success:
            return _failure(
                transcribed.error or "Transcription failed", audio_path=str(audio_path)
            )
        return _transcript_payload(
            transcribed.text,
            transcribed.segments,
            include_segments=include_segments,
            max_chars=max_chars,
            engine=chosen.value,
            audio_path=str(audio_path),
            language=transcribed.language,
            duration_seconds=transcribed.duration,
        )

    return server


def main() -> None:
    logging.basicConfig(
        level=os.getenv("SIFT_MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = build_server()
    logger.info("Starting sift-core-mcp (download_dir=%s)", get_ingest_settings().download_dir)
    # stdio transport — Claude Desktop, Claude Code, Cursor, raw MCP clients.
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
