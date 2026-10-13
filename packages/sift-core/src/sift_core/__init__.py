"""The ingestion core: get media off any platform and turn it into a transcript.

This is the layer the Sift app is built on, shipped as its own package
(`sift-core`) so it can be used without the server, database, or bot. Nothing
here may import the `app` package; `tests/test_layering.py` enforces it on
every run.

    platforms/   per-site adapters (X Spaces, Apple Podcasts, Spotify, YouTube,
                 Discord, Instagram, 小红书, 小宇宙, 喜马拉雅)
    fetch/       platform dispatch, downloading, existing-caption fetch
    settings.py  the only configuration the core reads (`IngestSettings`);
                 the app registers its own, library callers may pass one
    media/       conversion, merging, enhancement, metadata tagging
    transcribe/  Whisper engines, diarization, subtitle reflow
    cli.py       the `sift` command
"""

from .exceptions import (
    SiftError,
    XDownloaderError,  # Backward compatibility
    AudioGrabError,  # Backward compatibility
    AuthenticationError,
    ContentNotFoundError,
    SpaceNotFoundError,  # Backward compatibility
    ContentNotAvailableError,
    SpaceNotAvailableError,  # Backward compatibility
    DownloadError,
    FFmpegError,
    ToolNotFoundError,
    UnsupportedPlatformError,
)
from .settings import IngestSettings
from .base import Platform, AudioMetadata, DownloadResult, PlatformDownloader
from .fetch.downloader import DownloaderFactory, download_audio, get_metadata, SpaceDownloader

__all__ = [
    # Exceptions
    "SiftError",
    "XDownloaderError",
    "AudioGrabError",
    "AuthenticationError",
    "ContentNotFoundError",
    "SpaceNotFoundError",
    "ContentNotAvailableError",
    "SpaceNotAvailableError",
    "DownloadError",
    "FFmpegError",
    "ToolNotFoundError",
    "UnsupportedPlatformError",
    # Configuration
    "IngestSettings",
    # Base classes
    "Platform",
    "AudioMetadata",
    "DownloadResult",
    "PlatformDownloader",
    # Factory and functions
    "DownloaderFactory",
    "download_audio",
    "get_metadata",
    "SpaceDownloader",
]
