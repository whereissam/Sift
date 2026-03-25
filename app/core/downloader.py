"""Unified downloader with auto-detection and factory pattern."""

import logging
from pathlib import Path
from typing import Optional, Type

from .base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from .exceptions import UnsupportedPlatformError

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies
_platform_downloaders: Optional[list[Type[PlatformDownloader]]] = None


def _get_platform_downloaders() -> list[Type[PlatformDownloader]]:
    """Get list of platform downloader classes (lazy loaded)."""
    global _platform_downloaders
    if _platform_downloaders is None:
        from .platforms import (
            XSpacesDownloader,
            ApplePodcastsDownloader,
            SpotifyDownloader,
            YouTubeDownloader,
            XiaoyuzhouDownloader,
            DiscordAudioDownloader,
            XVideoDownloader,
            YouTubeVideoDownloader,
            InstagramVideoDownloader,
            XiaohongshuVideoDownloader,
        )
        _platform_downloaders = [
            # Audio
            XSpacesDownloader,
            ApplePodcastsDownloader,
            SpotifyDownloader,
            YouTubeDownloader,
            XiaoyuzhouDownloader,
            DiscordAudioDownloader,
            # Video
            XVideoDownloader,
            YouTubeVideoDownloader,
            InstagramVideoDownloader,
            XiaohongshuVideoDownloader,
        ]
    return _platform_downloaders


class DownloaderFactory:
    """Factory for creating platform-specific downloaders."""

    @classmethod
    def detect_platform(cls, url: str) -> Optional[Platform]:
        """Auto-detect platform from URL.

        Uses class-level PLATFORM attribute to avoid instantiation
        (which may fail if external tools like spotdl aren't installed).
        """
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.can_handle_url(url):
                # Use class attribute if available, otherwise instantiate
                if hasattr(downloader_cls, 'PLATFORM'):
                    return downloader_cls.PLATFORM
                try:
                    return downloader_cls().platform
                except Exception:
                    # Tool not installed — skip but still return platform from class name
                    return None
        return None

    @classmethod
    def get_downloader(cls, url: str) -> PlatformDownloader:
        """Get appropriate downloader for URL."""
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.can_handle_url(url):
                return downloader_cls()
        raise UnsupportedPlatformError(f"No downloader found for URL: {url}")

    @classmethod
    def get_downloader_for_platform(cls, platform: Platform) -> PlatformDownloader:
        """Get downloader for specific platform."""
        from .platforms import (
            XSpacesDownloader,
            ApplePodcastsDownloader,
            SpotifyDownloader,
            YouTubeDownloader,
            XiaoyuzhouDownloader,
            DiscordAudioDownloader,
            XVideoDownloader,
            YouTubeVideoDownloader,
            InstagramVideoDownloader,
            XiaohongshuVideoDownloader,
        )

        mapping = {
            # Audio
            Platform.X_SPACES: XSpacesDownloader,
            Platform.APPLE_PODCASTS: ApplePodcastsDownloader,
            Platform.SPOTIFY: SpotifyDownloader,
            Platform.YOUTUBE: YouTubeDownloader,
            Platform.XIAOYUZHOU: XiaoyuzhouDownloader,
            Platform.DISCORD: DiscordAudioDownloader,
            # Video
            Platform.X_VIDEO: XVideoDownloader,
            Platform.YOUTUBE_VIDEO: YouTubeVideoDownloader,
            Platform.INSTAGRAM: InstagramVideoDownloader,
            Platform.XIAOHONGSHU: XiaohongshuVideoDownloader,
        }

        downloader_cls = mapping.get(platform)
        if not downloader_cls:
            raise UnsupportedPlatformError(f"Unknown platform: {platform}")

        return downloader_cls()

    @classmethod
    def is_url_supported(cls, url: str) -> bool:
        """Check if URL is supported by any platform."""
        return cls.detect_platform(url) is not None

    @classmethod
    def get_available_platforms(cls) -> list[Platform]:
        """Get list of platforms with available dependencies."""
        available = []
        for downloader_cls in _get_platform_downloaders():
            if downloader_cls.is_available():
                if hasattr(downloader_cls, 'PLATFORM'):
                    available.append(downloader_cls.PLATFORM)
                else:
                    try:
                        available.append(downloader_cls().platform)
                    except Exception:
                        pass
        return available


# Convenience function for simple usage
async def download_audio(
    url: str,
    output_path: Optional[Path] = None,
    output_format: str = "m4a",
    quality: str = "high",
) -> DownloadResult:
    """
    Download audio from any supported platform.

    Args:
        url: URL to download from
        output_path: Optional output path
        output_format: Output format (m4a, mp3, mp4)
        quality: Quality preset

    Returns:
        DownloadResult
    """
    downloader = DownloaderFactory.get_downloader(url)
    return await downloader.download(
        url,
        output_path=output_path,
        output_format=output_format,
        quality=quality,
    )


async def get_metadata(url: str) -> Optional[AudioMetadata]:
    """
    Get metadata for content without downloading.

    Args:
        url: URL to get metadata for

    Returns:
        AudioMetadata or None
    """
    downloader = DownloaderFactory.get_downloader(url)
    return await downloader.get_metadata(url)


# Backward compatibility - keep SpaceDownloader as alias
def SpaceDownloader(*args, **kwargs):
    """Backward compatibility alias for XSpacesDownloader."""
    from .platforms import XSpacesDownloader
    return XSpacesDownloader(*args, **kwargs)


# Re-export for backward compatibility
from .base import DownloadResult, AudioMetadata

__all__ = [
    "DownloaderFactory",
    "download_audio",
    "get_metadata",
    "SpaceDownloader",
    "DownloadResult",
    "AudioMetadata",
]
