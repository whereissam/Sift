"""Unified downloader with auto-detection and factory pattern."""

import logging
from pathlib import Path
from typing import Optional

from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import UnsupportedPlatformError
from ..settings import IngestSettings

logger = logging.getLogger(__name__)


def _get_platform_downloaders() -> tuple[type[PlatformDownloader], ...]:
    """The adapter list, in URL-detection order.

    Imported lazily: the platform modules import from `fetch`, so pulling them
    in at module load would be circular.
    """
    from ..platforms import DOWNLOADERS

    return DOWNLOADERS


class DownloaderFactory:
    """Factory for creating platform-specific downloaders."""

    @classmethod
    def detect_platform(cls, url: str) -> Optional[Platform]:
        """Auto-detect platform from URL.

        Reads the class-level ``PLATFORM`` so nothing is instantiated (which
        may fail if external tools like spotdl aren't installed).
        """
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.can_handle_url(url):
                return downloader_cls.PLATFORM
        return None

    @classmethod
    def get_downloader(
        cls, url: str, settings: Optional[IngestSettings] = None
    ) -> PlatformDownloader:
        """Get appropriate downloader for URL."""
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.can_handle_url(url):
                return downloader_cls(settings=settings)
        raise UnsupportedPlatformError(f"No downloader found for URL: {url}")

    @classmethod
    def get_downloader_for_platform(
        cls, platform: Platform, settings: Optional[IngestSettings] = None
    ) -> PlatformDownloader:
        """Get downloader for specific platform."""
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.PLATFORM == platform:
                return downloader_cls(settings=settings)
        raise UnsupportedPlatformError(f"Unknown platform: {platform}")

    @classmethod
    def is_url_supported(cls, url: str) -> bool:
        """Check if URL is supported by any platform."""
        return cls.detect_platform(url) is not None

    @classmethod
    def get_available_platforms(cls) -> list[Platform]:
        """Get list of platforms with available dependencies."""
        return [
            downloader_cls.PLATFORM
            for downloader_cls in _get_platform_downloaders()
            if downloader_cls.is_available()
        ]


# Convenience function for simple usage
async def download_audio(
    url: str,
    output_path: Optional[Path] = None,
    output_format: str = "m4a",
    quality: str = "high",
    settings: Optional[IngestSettings] = None,
) -> DownloadResult:
    """
    Download audio from any supported platform.

    Args:
        url: URL to download from
        output_path: Optional output path
        output_format: Output format (m4a, mp3, mp4)
        quality: Quality preset
        settings: Download dir and platform cookies; defaults to env / `.env`

    Returns:
        DownloadResult
    """
    downloader = DownloaderFactory.get_downloader(url, settings=settings)
    return await downloader.download(
        url,
        output_path=output_path,
        output_format=output_format,
        quality=quality,
    )


async def get_metadata(
    url: str, settings: Optional[IngestSettings] = None
) -> Optional[AudioMetadata]:
    """
    Get metadata for content without downloading.

    Args:
        url: URL to get metadata for
        settings: Platform cookies; defaults to env / `.env`

    Returns:
        AudioMetadata or None
    """
    downloader = DownloaderFactory.get_downloader(url, settings=settings)
    return await downloader.get_metadata(url)


# Backward compatibility - keep SpaceDownloader as alias
def SpaceDownloader(*args, **kwargs):
    """Backward compatibility alias for XSpacesDownloader."""
    from ..platforms import XSpacesDownloader
    return XSpacesDownloader(*args, **kwargs)


__all__ = [
    "DownloaderFactory",
    "download_audio",
    "get_metadata",
    "SpaceDownloader",
    "DownloadResult",
    "AudioMetadata",
]
