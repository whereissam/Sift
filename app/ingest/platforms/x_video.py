"""X/Twitter video downloader implementation using yt-dlp."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..settings import IngestSettings, get_ingest_settings
from ..fetch.auth import twitter_ytdlp_cookies
from ..base import (
    Platform,
    PlatformDownloader,
    AudioMetadata,
    DownloadResult,
    resolve_yt_dlp,
    yt_dlp_available,
)
from ..exceptions import SiftError, ContentNotFoundError

logger = logging.getLogger(__name__)


# X cookies expire, and yt-dlp treats a rejected cookie as a hard failure —
# so a stale session makes public posts fail that would have worked with no
# auth at all. Auth must never be worse than no auth.
_AUTH_REJECTED = (
    "could not authenticate you",
    "logged out",
    "401 unauthorized",
    "missing or invalid csrf token",
)


def _is_auth_rejection(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_REJECTED)


async def _run_ytdlp(
    base_cmd: list[str], url: str, settings: Optional[IngestSettings] = None
):
    """Run yt-dlp with X auth, retrying anonymously if the cookies are rejected.

    Returns ``(returncode, stdout, stderr)``. Protected and sensitive posts
    need the cookies; public ones do not, and this keeps both working whether
    or not the configured session is still valid.
    """
    with twitter_ytdlp_cookies(settings) as cookies_file:
        cmd = list(base_cmd)
        if cookies_file:
            cmd.extend(["--cookies", cookies_file])
        cmd.append(url)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

    if process.returncode == 0 or not cookies_file:
        return process.returncode, stdout, stderr

    if not _is_auth_rejection(stderr.decode(errors="replace")):
        return process.returncode, stdout, stderr

    logger.warning("X cookies were rejected; retrying without authentication")
    retry = await asyncio.create_subprocess_exec(
        *base_cmd,
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await retry.communicate()
    return retry.returncode, stdout, stderr


class XVideoDownloader(PlatformDownloader):
    """Downloads videos from X/Twitter posts using yt-dlp."""

    PLATFORM = Platform.X_VIDEO

    # URL patterns for X/Twitter posts with video
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)",
        r"(?:https?://)?(?:mobile\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)",
    ]

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        settings: Optional[IngestSettings] = None,
    ):
        """Initialize the X video downloader."""
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
        return Platform.X_VIDEO

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid X/Twitter post URL."""
        return any(re.search(pattern, url) for pattern in cls.URL_PATTERNS)

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract tweet/post ID from URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ContentNotFoundError(f"Could not extract post ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if yt-dlp is available."""
        return yt_dlp_available()

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "mp4",
        quality: str = "high",
    ) -> DownloadResult:
        """Download video from X/Twitter post."""
        logger.info(f"Starting X video download for: {url}")

        try:
            post_id = self.extract_content_id(url)
            logger.info(f"Extracted post ID: {post_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                output_template = str(output_path)
            else:
                output_template = str(self.download_dir / "%(title)s [%(id)s].%(ext)s")

            # Quality mapping
            format_spec = {
                "low": "worst[ext=mp4]/worst",
                "medium": "best[height<=480][ext=mp4]/best[height<=480]",
                "high": "best[height<=720][ext=mp4]/best[height<=720]",
                "highest": "best[ext=mp4]/best",
            }.get(quality, "best[ext=mp4]/best")

            # X video is always delivered as an mp4 container (default output
            # format). Log it so callers know what to expect.
            logger.info("X video output format: mp4 (default)")

            # Auth (TWITTER_COOKIE_FILE, or TWITTER_AUTH_TOKEN + TWITTER_CT0)
            # is needed for protected / sensitive / age-restricted posts and
            # ignored for public ones. _run_ytdlp retries anonymously if the
            # session has expired.
            logger.info("Running yt-dlp for X video...")
            returncode, stdout, stderr = await _run_ytdlp(
                [
                    self._yt_dlp_path,
                    "--no-progress",
                    "-f", format_spec,
                    "-o", output_template,
                    "--print-json",
                    "--merge-output-format", "mp4",
                    # Parallel fragment downloads
                    "--concurrent-fragments", "16",
                    "--fragment-retries", "5",
                ],
                url,
                settings=self.settings,
            )

            if returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"yt-dlp error: {error_msg}")

                if "404" in error_msg or "not found" in error_msg.lower():
                    raise ContentNotFoundError(f"Post not found: {post_id}")
                if "no video" in error_msg.lower():
                    raise ContentNotFoundError(f"No video in post: {post_id}")
                # Auth gate: protected / age-restricted / sensitive posts.
                if (
                    "nsfw" in error_msg.lower()
                    or "age" in error_msg.lower()
                    or "log in" in error_msg.lower()
                    or "login" in error_msg.lower()
                    or "protected" in error_msg.lower()
                    or "private" in error_msg.lower()
                    or "--cookies" in error_msg.lower()
                ):
                    if not self.settings.has_auth:
                        raise ContentNotFoundError(
                            "This X post requires authentication (protected, "
                            "private, or age-restricted). Set TWITTER_AUTH_TOKEN "
                            "and TWITTER_CT0 (or TWITTER_COOKIE_FILE) in your .env."
                        )
                    raise ContentNotFoundError(
                        "This X post could not be accessed even with the "
                        "configured credentials. They may be expired or lack "
                        "access to this content."
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
                            platform=Platform.X_VIDEO,
                            content_id=data.get('id', post_id),
                            title=data.get('title', data.get('description', 'Unknown')[:100]),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader'),
                            duration_seconds=data.get('duration'),
                            artwork_url=data.get('thumbnail'),
                        )
                        break
                    except json.JSONDecodeError:
                        continue

            # Find output file if not in JSON
            if not file_path or not file_path.exists():
                for ext in ['.mp4', '.webm', '.mkv']:
                    matches = list(self.download_dir.glob(f"*{post_id}*{ext}"))
                    if matches:
                        file_path = matches[0]
                        break

            if not file_path or not file_path.exists():
                raise SiftError("Download completed but output file not found")

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
        """Get metadata for X post without downloading."""
        try:
            post_id = self.extract_content_id(url)

            # Auth matters here too: without it, metadata fails on protected
            # and sensitive posts that the download path handles fine.
            returncode, stdout, stderr = await _run_ytdlp(
                [self._yt_dlp_path, "--no-download", "--print-json"],
                url,
                settings=self.settings,
            )

            if returncode != 0:
                return None

            output = stdout.decode().strip()
            for line in output.split('\n'):
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                        return AudioMetadata(
                            platform=Platform.X_VIDEO,
                            content_id=data.get('id', post_id),
                            title=data.get('title', data.get('description', 'Unknown')[:100]),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader'),
                            duration_seconds=data.get('duration'),
                            artwork_url=data.get('thumbnail'),
                        )
                    except json.JSONDecodeError:
                        continue

            return None

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
