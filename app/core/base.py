"""Abstract base classes for platform downloaders."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class Platform(str, Enum):
    """Supported platforms."""

    # Audio platforms
    X_SPACES = "x_spaces"
    APPLE_PODCASTS = "apple_podcasts"
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"
    XIAOYUZHOU = "xiaoyuzhou"
    DISCORD = "discord"
    # Video platforms
    X_VIDEO = "x_video"
    YOUTUBE_VIDEO = "youtube_video"
    INSTAGRAM = "instagram"
    XIAOHONGSHU = "xiaohongshu"


@dataclass
class AudioMetadata:
    """Unified metadata model for all platforms."""

    platform: Platform
    content_id: str
    title: str
    creator_name: Optional[str] = None
    creator_username: Optional[str] = None
    duration_seconds: Optional[float] = None
    description: Optional[str] = None
    artwork_url: Optional[str] = None
    published_at: Optional[datetime] = None
    # Podcast-specific fields
    show_name: Optional[str] = None
    episode_number: Optional[int] = None
    # X Spaces specific
    total_listeners: Optional[int] = None
    total_replay_watched: Optional[int] = None


@dataclass
class DownloadResult:
    """Result of a download operation."""

    success: bool
    file_path: Optional[Path] = None
    metadata: Optional[AudioMetadata] = None
    error: Optional[str] = None
    file_size_bytes: Optional[int] = None

    @property
    def file_size_mb(self) -> Optional[float]:
        """Return file size in MB."""
        if self.file_size_bytes:
            return self.file_size_bytes / (1024 * 1024)
        return None


class PlatformDownloader(ABC):
    """Abstract base class for platform-specific downloaders."""

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform this downloader handles."""
        pass

    @classmethod
    @abstractmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if this downloader can handle the given URL."""
        pass

    @classmethod
    @abstractmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract the content ID from URL."""
        pass

    @abstractmethod
    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> DownloadResult:
        """Download audio from the platform."""
        pass

    @abstractmethod
    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata without downloading."""
        pass

    @classmethod
    def is_available(cls) -> bool:
        """Check if this downloader's dependencies are available."""
        return True
