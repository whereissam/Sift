"""YouTube audio downloader implementation using yt-dlp."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..settings import IngestSettings, get_ingest_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult, resolve_yt_dlp, yt_dlp_available
from ..exceptions import SiftError, ContentNotAvailableError, ContentNotFoundError

logger = logging.getLogger(__name__)


def youtube_cookie_args(settings) -> list[str]:
    """yt-dlp cookie flags for YouTube.

    Browser cookies take precedence over an exported cookies.txt — they
    stay fresh, which matters because YouTube bot-blocks datacenter and
    rate-limited IPs unless requests carry a logged-in session.
    """
    if settings.youtube_cookies_from_browser:
        return ["--cookies-from-browser", settings.youtube_cookies_from_browser]
    if settings.youtube_cookies_file:
        return ["--cookies", settings.youtube_cookies_file]
    return []


class YouTubeDownloader(PlatformDownloader):
    """Downloads audio from YouTube videos using yt-dlp."""

    PLATFORM = Platform.YOUTUBE

    # URL patterns for YouTube
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
        r"(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})",
        r"(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        r"(?:https?://)?music\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
    ]

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        settings: Optional[IngestSettings] = None,
    ):
        """Initialize the YouTube downloader."""
        self.settings = settings or get_ingest_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

        self._yt_dlp_path = self._find_yt_dlp()

    def _find_yt_dlp(self) -> str:
        """Resolve yt-dlp, preferring the pinned build over a system one."""
        return resolve_yt_dlp()

    @property
    def platform(self) -> Platform:
        return Platform.YOUTUBE

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid YouTube URL."""
        return any(re.search(pattern, url) for pattern in cls.URL_PATTERNS)

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract video ID from YouTube URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ContentNotFoundError(f"Could not extract video ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if yt-dlp is available."""
        return yt_dlp_available()

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
        """Download audio from a YouTube video."""
        logger.info(f"Starting YouTube audio download for: {url}")

        try:
            video_id = self.extract_content_id(url)
            logger.info(f"Extracted video ID: {video_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                output_template = str(output_path)
            else:
                output_template = str(self.download_dir / "%(title)s [%(id)s].%(ext)s")

            # For mp4, download as m4a first then convert
            download_format = "m4a" if output_format == "mp4" else output_format
            needs_conversion = output_format == "mp4"

            cmd = [
                self._yt_dlp_path,
                # Download the EJS challenge solver so YouTube's n-challenge
                # can be solved (via the local deno runtime); without it some
                # formats are missing / throttled.
                "--remote-components", "ejs:github",
                "--no-progress",
                "-x",  # Extract audio
                "--audio-format", download_format if download_format == "mp3" else "m4a",
                "-o", output_template,
                "--print-json",
                # Workaround for YouTube SABR streaming issues
                "--extractor-args", "youtube:player_client=web",
                # Parallel fragment downloads
                "--concurrent-fragments", "16",
                "--fragment-retries", "5",
            ]

            if download_format == "mp3":
                quality_map = {"low": "64K", "medium": "128K", "high": "192K", "highest": "320K"}
                cmd.extend(["--audio-quality", quality_map.get(quality, "192K")])

            cmd.extend(youtube_cookie_args(self.settings))

            cmd.append(url)

            logger.info("Running yt-dlp for YouTube...")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"yt-dlp error: {error_msg}")

                if "404" in error_msg or "not found" in error_msg.lower():
                    raise ContentNotFoundError(f"Video not found: {video_id}")
                if "private" in error_msg.lower():
                    raise ContentNotFoundError(f"Video is private: {video_id}")
                if "unavailable" in error_msg.lower():
                    raise ContentNotFoundError(f"Video is unavailable: {video_id}")
                if "not made this video available in your country" in error_msg.lower():
                    raise ContentNotAvailableError(
                        f"Video is geo-restricted and not available in your region: {video_id}"
                    )
                if "sign in to confirm" in error_msg.lower():
                    raise ContentNotAvailableError(
                        "YouTube requires cookie authentication. Set "
                        "YOUTUBE_COOKIES_FROM_BROWSER (e.g. 'chrome') or "
                        "YOUTUBE_COOKIES_FILE to a cookies.txt path."
                    )
                if "age" in error_msg.lower() and "restricted" in error_msg.lower():
                    raise ContentNotAvailableError(
                        "Video is age-restricted. Cookie authentication is required."
                    )

                raise SiftError(f"yt-dlp failed: {error_msg[:500]}")

            # Parse JSON output
            output = stdout.decode().strip()
            metadata = None
            file_path = None

            for line in output.split('\n'):
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                        file_path = Path(data.get('_filename', data.get('filename', '')))
                        metadata = AudioMetadata(
                            platform=Platform.YOUTUBE,
                            content_id=data.get('id', video_id),
                            title=data.get('title', 'Unknown'),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            duration_seconds=data.get('duration'),
                            description=data.get('description', '')[:500] if data.get('description') else None,
                            artwork_url=data.get('thumbnail'),
                        )
                        break
                    except json.JSONDecodeError:
                        continue

            # Find output file if not in JSON
            if not file_path or not file_path.exists():
                for ext in ['.m4a', '.mp3', '.aac', '.webm', '.opus']:
                    matches = list(self.download_dir.glob(f"*{video_id}*{ext}"))
                    if matches:
                        file_path = matches[0]
                        break

            if not file_path or not file_path.exists():
                raise SiftError("Download completed but output file not found")

            # Convert to mp4 if needed
            if needs_conversion:
                from ..media.converter import AudioConverter
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
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=f"Unexpected error: {e}",
            )

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for a YouTube video without downloading."""
        try:
            video_id = self.extract_content_id(url)

            cmd = [
                self._yt_dlp_path,
                "--remote-components", "ejs:github",
                "--no-download",
                "--print-json",
                # Without these, metadata fails on exactly the videos that need
                # auth (age-restricted, or a bot-checked IP) while the download
                # path succeeds.
                *youtube_cookie_args(self.settings),
                url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return None

            output = stdout.decode().strip()
            for line in output.split('\n'):
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                        return AudioMetadata(
                            platform=Platform.YOUTUBE,
                            content_id=data.get('id', video_id),
                            title=data.get('title', 'Unknown'),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            duration_seconds=data.get('duration'),
                            description=data.get('description', '')[:500] if data.get('description') else None,
                            artwork_url=data.get('thumbnail'),
                        )
                    except json.JSONDecodeError:
                        continue

            return None

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
