"""小宇宙播客 (Xiaoyuzhou FM) downloader implementation."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from ...config import get_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import SiftError, ContentNotFoundError

logger = logging.getLogger(__name__)


class XiaoyuzhouDownloader(PlatformDownloader):
    """Downloads podcast episodes from 小宇宙 (Xiaoyuzhou FM)."""

    PLATFORM = Platform.XIAOYUZHOU

    # URL patterns for Xiaoyuzhou
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?xiaoyuzhoufm\.com/episode/([a-zA-Z0-9]+)",
        r"(?:https?://)?(?:www\.)?xiaoyuzhoufm\.com/podcast/([a-zA-Z0-9]+)",
    ]

    API_BASE = "https://api.xiaoyuzhoufm.com/v1"

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the Xiaoyuzhou downloader."""
        self.settings = get_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

    @property
    def platform(self) -> Platform:
        return Platform.XIAOYUZHOU

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid Xiaoyuzhou URL."""
        return "xiaoyuzhoufm.com" in url

    @classmethod
    def extract_content_id(cls, url: str) -> tuple[str, str]:
        """Extract episode or podcast ID from URL.

        Returns: (content_type, content_id) where content_type is 'episode' or 'podcast'
        """
        # Episode URL
        episode_match = re.search(r"xiaoyuzhoufm\.com/episode/([a-zA-Z0-9]+)", url)
        if episode_match:
            return ("episode", episode_match.group(1))

        # Podcast URL
        podcast_match = re.search(r"xiaoyuzhoufm\.com/podcast/([a-zA-Z0-9]+)", url)
        if podcast_match:
            return ("podcast", podcast_match.group(1))

        raise ContentNotFoundError(f"Could not extract ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Xiaoyuzhou downloader is always available (uses HTTP)."""
        return True

    async def _get_episode_info(self, episode_id: str) -> dict:
        """Get episode info by scraping the page."""
        import json as json_module

        async with httpx.AsyncClient() as client:
            # Fetch the episode page
            resp = await client.get(
                f"https://www.xiaoyuzhoufm.com/episode/{episode_id}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                timeout=30.0,
                follow_redirects=True,
            )

            if resp.status_code != 200:
                raise ContentNotFoundError(f"Episode not found: {episode_id}")

            html = resp.text

            # Extract JSON data from script tag
            # Look for __NEXT_DATA__ which contains the episode info
            import re
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if match:
                try:
                    data = json_module.loads(match.group(1))
                    props = data.get("props", {}).get("pageProps", {})
                    episode = props.get("episode", {})
                    if episode:
                        return episode
                except json_module.JSONDecodeError:
                    pass

            # Fallback: try to extract audio URL directly from HTML
            audio_match = re.search(r'"enclosure":\s*\{\s*"url":\s*"([^"]+)"', html)
            if audio_match:
                return {"enclosure": {"url": audio_match.group(1)}, "title": "Unknown Episode"}

            # Try to find media key
            media_match = re.search(r'"mediaKey":\s*"([^"]+)"', html)
            if media_match:
                return {"mediaKey": media_match.group(1), "title": "Unknown Episode"}

            raise ContentNotFoundError(f"Could not extract episode data: {episode_id}")

    async def _get_podcast_latest_episode(self, podcast_id: str) -> dict:
        """Get the latest episode from a podcast."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/podcast/{podcast_id}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                # Get episodes list
                episodes = data.get("episodes", [])
                if episodes:
                    return episodes[0]

            raise ContentNotFoundError(f"Podcast not found: {podcast_id}")

    async def _download_file(self, url: str, output_path: Path) -> None:
        """Download file from URL."""
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                url,
                timeout=300.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                }
            ) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        sanitized = re.sub(r'\s+', '_', sanitized)
        return sanitized[:100]

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> DownloadResult:
        """Download a podcast episode from Xiaoyuzhou."""
        logger.info(f"Starting Xiaoyuzhou download for: {url}")

        try:
            content_type, content_id = self.extract_content_id(url)
            logger.info(f"Content type: {content_type}, ID: {content_id}")

            # Get episode info
            if content_type == "episode":
                episode_info = await self._get_episode_info(content_id)
            else:
                # Get latest episode from podcast
                episode_info = await self._get_podcast_latest_episode(content_id)

            # Extract audio URL
            audio_url = episode_info.get("enclosure", {}).get("url")
            if not audio_url:
                audio_url = episode_info.get("mediaKey")
            if not audio_url:
                raise SiftError("No audio URL found in episode")

            # If mediaKey, construct full URL
            if audio_url and not audio_url.startswith("http"):
                audio_url = f"https://media.xyzcdn.net/{audio_url}"

            # Extract metadata
            title = episode_info.get("title", "Unknown Episode")
            podcast_info = episode_info.get("podcast", {})
            show_name = podcast_info.get("title", "")
            author = podcast_info.get("author", "")

            metadata = AudioMetadata(
                platform=Platform.XIAOYUZHOU,
                content_id=episode_info.get("eid", content_id),
                title=title,
                creator_name=author,
                description=episode_info.get("description", "")[:500],
                show_name=show_name,
                duration_seconds=episode_info.get("duration"),
                artwork_url=episode_info.get("image", {}).get("picUrl"),
            )

            # Determine output path
            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                file_path = Path(output_path)
            else:
                # Determine extension from audio URL
                ext = ".m4a"
                if ".mp3" in audio_url.lower():
                    ext = ".mp3"

                filename = f"{self._sanitize_filename(show_name)} - {self._sanitize_filename(title)}{ext}"
                file_path = self.download_dir / filename

            logger.info(f"Downloading audio from Xiaoyuzhou...")

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

        except (ContentNotFoundError, SiftError) as e:
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
        """Get metadata for episode without downloading."""
        try:
            content_type, content_id = self.extract_content_id(url)

            if content_type == "episode":
                episode_info = await self._get_episode_info(content_id)
            else:
                episode_info = await self._get_podcast_latest_episode(content_id)

            podcast_info = episode_info.get("podcast", {})

            return AudioMetadata(
                platform=Platform.XIAOYUZHOU,
                content_id=episode_info.get("eid", content_id),
                title=episode_info.get("title", "Unknown Episode"),
                creator_name=podcast_info.get("author"),
                description=episode_info.get("description", "")[:500],
                show_name=podcast_info.get("title"),
                duration_seconds=episode_info.get("duration"),
                artwork_url=episode_info.get("image", {}).get("picUrl"),
            )

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
