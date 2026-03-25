"""Apple Podcasts downloader implementation."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional
from datetime import datetime

import httpx
import feedparser

from ...config import get_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import AudioGrabError, ContentNotFoundError

logger = logging.getLogger(__name__)


class ApplePodcastsDownloader(PlatformDownloader):
    """Downloads podcast episodes from Apple Podcasts via RSS feeds."""

    PLATFORM = Platform.APPLE_PODCASTS

    # URL patterns for Apple Podcasts
    URL_PATTERNS = [
        # Podcast page: podcasts.apple.com/us/podcast/show-name/id123456789
        r"podcasts\.apple\.com/(?:\w+/)?podcast/[^/]+/id(\d+)",
        # Episode page: podcasts.apple.com/us/podcast/show-name/id123456789?i=1000123456789
        r"podcasts\.apple\.com/(?:\w+/)?podcast/[^/]+/id(\d+)\?i=(\d+)",
    ]

    ITUNES_LOOKUP_API = "https://itunes.apple.com/lookup"

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the Apple Podcasts downloader."""
        self.settings = get_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

    @property
    def platform(self) -> Platform:
        return Platform.APPLE_PODCASTS

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid Apple Podcasts URL."""
        return "podcasts.apple.com" in url and "/podcast/" in url

    @classmethod
    def extract_content_id(cls, url: str) -> tuple[str, Optional[str]]:
        """Extract podcast ID and optional episode ID from URL."""
        # Try episode URL pattern first
        episode_pattern = r"podcasts\.apple\.com/(?:\w+/)?podcast/[^/]+/id(\d+)\?i=(\d+)"
        match = re.search(episode_pattern, url)
        if match:
            return match.group(1), match.group(2)

        # Try podcast-only pattern
        podcast_pattern = r"podcasts\.apple\.com/(?:\w+/)?podcast/[^/]+/id(\d+)"
        match = re.search(podcast_pattern, url)
        if match:
            return match.group(1), None

        raise ContentNotFoundError(f"Could not extract podcast ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Apple Podcasts downloader is always available (uses HTTP)."""
        return True

    async def _get_podcast_info(self, podcast_id: str) -> dict:
        """Get podcast info from iTunes API."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self.ITUNES_LOOKUP_API,
                params={"id": podcast_id, "entity": "podcast"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("resultCount", 0) == 0:
                raise ContentNotFoundError(f"Podcast not found: {podcast_id}")

            return data["results"][0]

    async def _get_rss_feed(self, feed_url: str) -> feedparser.FeedParserDict:
        """Fetch and parse RSS feed."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(feed_url, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            return feedparser.parse(resp.text)

    async def _download_file(self, url: str, output_path: Path) -> None:
        """Download file from URL."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, timeout=300.0, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        sanitized = re.sub(r'\s+', '_', sanitized)
        return sanitized[:100]

    async def _resolve_episode_title(self, podcast_id: str, episode_id: str) -> Optional[str]:
        """Resolve an iTunes episode track ID to its title via the Lookup API."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.ITUNES_LOOKUP_API,
                    params={"id": podcast_id, "entity": "podcastEpisode", "limit": "200"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                for result in data.get("results", []):
                    if str(result.get("trackId")) == episode_id:
                        return result.get("trackName")
        except Exception as e:
            logger.warning(f"Failed to resolve episode title for {episode_id}: {e}")
        return None

    async def _find_episode(
        self, feed: feedparser.FeedParserDict, podcast_id: str, episode_id: str,
    ) -> Optional[dict]:
        """Find episode in feed by Apple episode ID."""
        # Try matching GUID directly
        for entry in feed.entries:
            guid = entry.get("id", "") or entry.get("guid", "")
            if episode_id in guid:
                return entry

        # Resolve iTunes track ID to episode title, then match by title
        title = await self._resolve_episode_title(podcast_id, episode_id)
        if title:
            logger.info(f"Resolved episode {episode_id} -> '{title}'")
            for entry in feed.entries:
                if entry.get("title") == title:
                    return entry

        return None

    def _parse_duration(self, raw: Optional[str]) -> Optional[float]:
        """Parse iTunes duration which can be seconds string or HH:MM:SS."""
        if not raw:
            return None
        try:
            # Pure numeric (seconds)
            return float(raw)
        except (ValueError, TypeError):
            pass
        # HH:MM:SS or MM:SS
        parts = str(raw).split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, TypeError):
            pass
        return None

    def _get_audio_url(self, entry: dict) -> Optional[str]:
        """Extract audio URL from feed entry."""
        # Check enclosures
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/"):
                return enclosure.get("href") or enclosure.get("url")

        # Check links
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/"):
                return link.get("href")

        return None

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> DownloadResult:
        """Download a podcast episode from Apple Podcasts."""
        logger.info(f"Starting Apple Podcasts download for: {url}")

        try:
            podcast_id, episode_id = self.extract_content_id(url)
            logger.info(f"Podcast ID: {podcast_id}, Episode ID: {episode_id}")

            # Get podcast info from iTunes API
            podcast_info = await self._get_podcast_info(podcast_id)
            feed_url = podcast_info.get("feedUrl")

            if not feed_url:
                raise AudioGrabError("Podcast does not have a public RSS feed")

            logger.info(f"Fetching RSS feed: {feed_url}")

            # Parse RSS feed
            feed = await self._get_rss_feed(feed_url)

            if not feed.entries:
                raise ContentNotFoundError("No episodes found in podcast feed")

            # Find the episode
            if episode_id:
                entry = await self._find_episode(feed, podcast_id, episode_id)
                if not entry:
                    # Fall back to latest episode
                    logger.warning(f"Episode {episode_id} not found, using latest")
                    entry = feed.entries[0]
            else:
                # Get latest episode
                entry = feed.entries[0]

            # Get audio URL
            audio_url = self._get_audio_url(entry)
            if not audio_url:
                raise AudioGrabError("No audio URL found in episode")

            # Create metadata
            show_name = feed.feed.get("title", podcast_info.get("collectionName", "Unknown"))
            episode_title = entry.get("title", "Unknown Episode")

            metadata = AudioMetadata(
                platform=Platform.APPLE_PODCASTS,
                content_id=episode_id or entry.get("id", podcast_id),
                title=episode_title,
                creator_name=podcast_info.get("artistName"),
                description=entry.get("summary", entry.get("description")),
                show_name=show_name,
                artwork_url=podcast_info.get("artworkUrl600"),
                duration_seconds=self._parse_duration(entry.get("itunes_duration")),
            )

            # Determine output path
            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                file_path = Path(output_path)
            else:
                # Determine extension from audio URL
                ext = ".mp3"  # Default
                if ".m4a" in audio_url.lower():
                    ext = ".m4a"
                elif ".aac" in audio_url.lower():
                    ext = ".aac"

                filename = f"{self._sanitize_filename(show_name)} - {self._sanitize_filename(episode_title)}{ext}"
                file_path = self.download_dir / filename

            logger.info(f"Downloading audio: {audio_url[:80]}...")

            # Download the audio file
            await self._download_file(audio_url, file_path)

            # Convert format if needed
            original_ext = file_path.suffix.lower()
            if output_format and f".{output_format}" != original_ext:
                from ..converter import AudioConverter
                logger.info(f"Converting to {output_format}...")
                converter = AudioConverter()
                converted_path = await converter.convert(
                    input_path=file_path,
                    output_format=output_format,
                    quality=quality,
                    keep_original=False,
                )
                file_path = converted_path

            file_size = file_path.stat().st_size

            logger.info(f"Download complete: {file_path}")
            logger.info(f"File size: {file_size / (1024*1024):.2f} MB")

            return DownloadResult(
                success=True,
                file_path=file_path,
                metadata=metadata,
                file_size_bytes=file_size,
            )

        except (ContentNotFoundError, AudioGrabError) as e:
            logger.error(f"Download failed: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=str(e),
            )
        except httpx.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=f"HTTP error: {e}",
            )
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=f"Unexpected error: {e}",
            )

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for a podcast episode without downloading."""
        try:
            podcast_id, episode_id = self.extract_content_id(url)

            # Get podcast info
            podcast_info = await self._get_podcast_info(podcast_id)
            feed_url = podcast_info.get("feedUrl")

            if not feed_url:
                return None

            # Parse feed
            feed = await self._get_rss_feed(feed_url)

            if not feed.entries:
                return None

            # Find episode
            if episode_id:
                entry = await self._find_episode(feed, podcast_id, episode_id)
                if not entry:
                    entry = feed.entries[0]
            else:
                entry = feed.entries[0]

            show_name = feed.feed.get("title", podcast_info.get("collectionName", "Unknown"))

            return AudioMetadata(
                platform=Platform.APPLE_PODCASTS,
                content_id=episode_id or entry.get("id", podcast_id),
                title=entry.get("title", "Unknown Episode"),
                creator_name=podcast_info.get("artistName"),
                description=entry.get("summary"),
                show_name=show_name,
                artwork_url=podcast_info.get("artworkUrl600"),
                duration_seconds=self._parse_duration(entry.get("itunes_duration")),
            )

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
