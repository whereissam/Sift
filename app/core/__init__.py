"""Core downloader functionality."""

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
from .base import Platform, AudioMetadata, DownloadResult, PlatformDownloader
from .downloader import DownloaderFactory, download_audio, get_metadata, SpaceDownloader

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
