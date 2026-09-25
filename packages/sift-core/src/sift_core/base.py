"""Abstract base classes for platform downloaders."""

import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional


def resolve_yt_dlp() -> str:
    """Absolute path to the yt-dlp binary the adapters should run.

    Order matters. The project pins a yt-dlp version in pyproject.toml, but
    every adapter shells out to a *binary* — so a system-wide install (brew,
    apt) silently shadows the pinned one whenever the app is started outside
    `uv run`. yt-dlp extractors break constantly, so running a months-old
    binary while the lockfile claims a current one is a confusing failure that
    looks like a broken platform.

    1. ``YT_DLP_PATH`` — explicit override, for packaged builds
    2. the current interpreter's own environment — this is the pinned version
    3. ``PATH`` — whatever is installed system-wide
    """
    from .exceptions import ToolNotFoundError

    override = os.environ.get("YT_DLP_PATH")
    if override:
        if Path(override).exists():
            return override
        raise ToolNotFoundError(f"YT_DLP_PATH is set but does not exist: {override}")

    for name in ("yt-dlp", "yt-dlp.exe"):
        candidate = Path(sys.executable).with_name(name)
        if candidate.exists():
            return str(candidate)

    found = shutil.which("yt-dlp")
    if found:
        return found

    raise ToolNotFoundError(
        "yt-dlp not found. Install it with `uv sync` (preferred, matches the "
        "pinned version), `brew install yt-dlp`, or set YT_DLP_PATH."
    )


def yt_dlp_available() -> bool:
    """Whether a usable yt-dlp exists, by the same rules as `resolve_yt_dlp`.

    Checking PATH directly would report "unavailable" on an install where only
    the pinned build exists, which is the normal `uv sync` layout.
    """
    try:
        resolve_yt_dlp()
    except Exception:
        return False
    return True


class Platform(str, Enum):
    """Supported platforms."""

    # Audio platforms
    X_SPACES = "x_spaces"
    APPLE_PODCASTS = "apple_podcasts"
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"
    XIAOYUZHOU = "xiaoyuzhou"
    XIMALAYA = "ximalaya"
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
    """Abstract base class for platform-specific downloaders.

    Subclasses declare ``PLATFORM`` and are listed once, in URL-detection
    order, in ``sift_core.platforms.DOWNLOADERS``.
    """

    PLATFORM: ClassVar[Platform]

    @property
    def platform(self) -> Platform:
        """Return the platform this downloader handles."""
        return self.PLATFORM

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
