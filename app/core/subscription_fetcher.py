"""Fetchers for different subscription types."""

import asyncio
import json
import logging
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import feedparser
import httpx

from .url_validator import validate_url_ssrf

logger = logging.getLogger(__name__)


@dataclass
class FetchedItem:
    """Represents a fetched item from a subscription source."""
    content_id: str
    content_url: str
    title: Optional[str] = None
    published_at: Optional[str] = None  # ISO format


class BaseFetcher(ABC):
    """Base class for subscription fetchers."""

    @abstractmethod
    async def fetch_items(
        self,
        source_url: str,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[FetchedItem]:
        """Fetch items from the subscription source."""
        pass

    @abstractmethod
    async def validate_source(self, source_url: str) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Validate a source URL and extract metadata.

        Returns:
            Tuple of (is_valid, source_id, source_name)
        """
        pass


class RSSFetcher(BaseFetcher):
    """Fetches items from RSS/Atom feeds (podcasts)."""

    ITUNES_LOOKUP_API = "https://itunes.apple.com/lookup"

    async def fetch_items(
        self,
        source_url: str,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[FetchedItem]:
        """Fetch episodes from an RSS feed."""
        logger.info(f"Fetching RSS feed: {source_url}")

        # SSRF protection: block private/reserved IPs
        is_valid, error = validate_url_ssrf(source_url)
        if not is_valid:
            logger.warning(f"Blocked RSS fetch to {source_url}: {error}")
            return []

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    source_url,
                    timeout=60.0,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

            items = []
            for entry in feed.entries[:limit]:
                # Extract content ID (GUID or link)
                content_id = entry.get("id") or entry.get("guid") or entry.get("link", "")

                # Get audio URL from enclosures
                content_url = self._get_audio_url(entry)
                if not content_url:
                    logger.debug(f"No audio URL found for entry: {entry.get('title', 'Unknown')}")
                    continue

                # Parse published date
                published_at = None
                if entry.get("published_parsed"):
                    try:
                        dt = datetime(*entry.published_parsed[:6])
                        published_at = dt.isoformat()
                    except Exception:
                        pass

                items.append(FetchedItem(
                    content_id=content_id,
                    content_url=content_url,
                    title=entry.get("title"),
                    published_at=published_at,
                ))

            logger.info(f"Found {len(items)} items in RSS feed")
            return items

        except Exception as e:
            logger.error(f"Failed to fetch RSS feed: {e}")
            return []

    async def validate_source(self, source_url: str) -> tuple[bool, Optional[str], Optional[str]]:
        """Validate RSS feed URL."""
        # Check if it's an Apple Podcasts URL - convert to RSS
        if "podcasts.apple.com" in source_url:
            rss_url, podcast_name = await self._apple_podcasts_to_rss(source_url)
            if rss_url:
                return True, rss_url, podcast_name
            return False, None, None

        # Try to fetch and parse the RSS feed directly
        # SSRF protection: block private/reserved IPs
        is_valid, error = validate_url_ssrf(source_url)
        if not is_valid:
            logger.warning(f"Blocked RSS validation for {source_url}: {error}")
            return False, None, None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    source_url,
                    timeout=30.0,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

            if feed.bozo and not feed.entries:
                logger.warning(f"Invalid RSS feed: {source_url}")
                return False, None, None

            feed_title = feed.feed.get("title", "Unknown Feed")
            return True, source_url, feed_title

        except Exception as e:
            logger.error(f"Failed to validate RSS feed: {e}")
            return False, None, None

    async def _apple_podcasts_to_rss(
        self, url: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Convert Apple Podcasts URL to RSS feed URL."""
        # Extract podcast ID
        pattern = r"podcasts\.apple\.com/(?:\w+/)?podcast/[^/]+/id(\d+)"
        match = re.search(pattern, url)
        if not match:
            return None, None

        podcast_id = match.group(1)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.ITUNES_LOOKUP_API,
                    params={"id": podcast_id, "entity": "podcast"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("resultCount", 0) == 0:
                return None, None

            result = data["results"][0]
            feed_url = result.get("feedUrl")
            podcast_name = result.get("collectionName", "Unknown Podcast")

            return feed_url, podcast_name

        except Exception as e:
            logger.error(f"Failed to get RSS from Apple Podcasts: {e}")
            return None, None

    def _get_audio_url(self, entry: dict) -> Optional[str]:
        """Extract audio URL from feed entry."""
        # Check enclosures first
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/"):
                return enclosure.get("href") or enclosure.get("url")

        # Check links
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/"):
                return link.get("href")

        return None


class YouTubeChannelFetcher(BaseFetcher):
    """Fetches videos from a YouTube channel."""

    def __init__(self):
        self._yt_dlp_path = shutil.which("yt-dlp")

    async def fetch_items(
        self,
        source_url: str,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[FetchedItem]:
        """Fetch videos from a YouTube channel."""
        if not self._yt_dlp_path:
            logger.error("yt-dlp not found")
            return []

        # Construct channel videos URL
        channel_url = source_url
        if source_id:
            channel_url = f"https://www.youtube.com/channel/{source_id}/videos"
        elif "/videos" not in channel_url:
            # Ensure we're getting the videos tab
            if channel_url.endswith("/"):
                channel_url += "videos"
            else:
                channel_url += "/videos"

        logger.info(f"Fetching YouTube channel: {channel_url}")

        try:
            cmd = [
                self._yt_dlp_path,
                "--flat-playlist",
                "--print-json",
                "--playlist-end", str(limit),
                channel_url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()[:500]}")
                return []

            items = []
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    video_id = data.get("id")
                    if not video_id:
                        continue

                    # Parse upload date
                    published_at = None
                    upload_date = data.get("upload_date")
                    if upload_date and len(upload_date) == 8:
                        try:
                            dt = datetime.strptime(upload_date, "%Y%m%d")
                            published_at = dt.isoformat()
                        except ValueError:
                            pass

                    items.append(FetchedItem(
                        content_id=video_id,
                        content_url=f"https://www.youtube.com/watch?v={video_id}",
                        title=data.get("title"),
                        published_at=published_at,
                    ))
                except json.JSONDecodeError:
                    continue

            logger.info(f"Found {len(items)} videos in channel")
            return items

        except Exception as e:
            logger.error(f"Failed to fetch YouTube channel: {e}")
            return []

    async def validate_source(self, source_url: str) -> tuple[bool, Optional[str], Optional[str]]:
        """Validate YouTube channel URL."""
        if not self._yt_dlp_path:
            return False, None, None

        # Accept various YouTube channel URL formats
        patterns = [
            r"youtube\.com/channel/([a-zA-Z0-9_-]+)",
            r"youtube\.com/@([a-zA-Z0-9_-]+)",
            r"youtube\.com/c/([a-zA-Z0-9_-]+)",
            r"youtube\.com/user/([a-zA-Z0-9_-]+)",
        ]

        for pattern in patterns:
            if re.search(pattern, source_url):
                break
        else:
            return False, None, None

        try:
            cmd = [
                self._yt_dlp_path,
                "--flat-playlist",
                "--playlist-end", "1",
                "--print", "%(channel)s",
                source_url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return False, None, None

            channel_name = stdout.decode().strip().split("\n")[0]
            return True, source_url, channel_name or "YouTube Channel"

        except Exception as e:
            logger.error(f"Failed to validate YouTube channel: {e}")
            return False, None, None


class YouTubePlaylistFetcher(BaseFetcher):
    """Fetches videos from a YouTube playlist."""

    def __init__(self):
        self._yt_dlp_path = shutil.which("yt-dlp")

    async def fetch_items(
        self,
        source_url: str,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[FetchedItem]:
        """Fetch videos from a YouTube playlist."""
        if not self._yt_dlp_path:
            logger.error("yt-dlp not found")
            return []

        playlist_url = source_url
        if source_id:
            playlist_url = f"https://www.youtube.com/playlist?list={source_id}"

        logger.info(f"Fetching YouTube playlist: {playlist_url}")

        try:
            cmd = [
                self._yt_dlp_path,
                "--flat-playlist",
                "--print-json",
                "--playlist-end", str(limit),
                playlist_url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"yt-dlp error: {stderr.decode()[:500]}")
                return []

            items = []
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    video_id = data.get("id")
                    if not video_id:
                        continue

                    items.append(FetchedItem(
                        content_id=video_id,
                        content_url=f"https://www.youtube.com/watch?v={video_id}",
                        title=data.get("title"),
                        published_at=None,  # Playlists don't always have dates
                    ))
                except json.JSONDecodeError:
                    continue

            logger.info(f"Found {len(items)} videos in playlist")
            return items

        except Exception as e:
            logger.error(f"Failed to fetch YouTube playlist: {e}")
            return []

    async def validate_source(self, source_url: str) -> tuple[bool, Optional[str], Optional[str]]:
        """Validate YouTube playlist URL."""
        if not self._yt_dlp_path:
            return False, None, None

        # Check URL pattern
        if "youtube.com/playlist" not in source_url and "list=" not in source_url:
            return False, None, None

        # Extract playlist ID
        match = re.search(r"list=([a-zA-Z0-9_-]+)", source_url)
        if not match:
            return False, None, None

        playlist_id = match.group(1)

        try:
            cmd = [
                self._yt_dlp_path,
                "--flat-playlist",
                "--playlist-end", "1",
                "--print", "%(playlist_title)s",
                source_url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return False, None, None

            playlist_title = stdout.decode().strip().split("\n")[0]
            return True, playlist_id, playlist_title or "YouTube Playlist"

        except Exception as e:
            logger.error(f"Failed to validate YouTube playlist: {e}")
            return False, None, None


def get_fetcher(subscription_type: str) -> BaseFetcher:
    """Get the appropriate fetcher for a subscription type."""
    fetchers = {
        "rss": RSSFetcher,
        "youtube_channel": YouTubeChannelFetcher,
        "youtube_playlist": YouTubePlaylistFetcher,
    }

    fetcher_class = fetchers.get(subscription_type)
    if not fetcher_class:
        raise ValueError(f"Unknown subscription type: {subscription_type}")

    return fetcher_class()
