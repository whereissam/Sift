"""Xiaohongshu (小红书/RED) video downloader implementation using yt-dlp."""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from ...config import get_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import AudioGrabError, ContentNotFoundError, ToolNotFoundError

logger = logging.getLogger(__name__)


class XiaohongshuVideoDownloader(PlatformDownloader):
    """Downloads videos from Xiaohongshu (小红书/RED) using yt-dlp."""

    # URL patterns for Xiaohongshu posts
    URL_PATTERNS = [
        # Full web URL
        r"(?:https?://)?(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/([a-zA-Z0-9]+)",
        # Short URL
        r"(?:https?://)?xhslink\.com/([a-zA-Z0-9]+)",
        # Alternative patterns
        r"(?:https?://)?(?:www\.)?xiaohongshu\.com/user/profile/[^/]+/([a-zA-Z0-9]+)",
        # Mobile share link
        r"(?:https?://)?xhs\.cn/([a-zA-Z0-9]+)",
    ]

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the Xiaohongshu video downloader."""
        self.settings = get_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

        self._yt_dlp_path = self._find_yt_dlp()

    def _find_yt_dlp(self) -> str:
        """Find yt-dlp binary in system PATH."""
        yt_dlp = shutil.which("yt-dlp")
        if not yt_dlp:
            raise ToolNotFoundError(
                "yt-dlp not found in PATH. Please install it: brew install yt-dlp"
            )
        return yt_dlp

    @property
    def platform(self) -> Platform:
        return Platform.XIAOHONGSHU

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid Xiaohongshu URL."""
        # Check standard patterns
        if any(re.search(pattern, url) for pattern in cls.URL_PATTERNS):
            return True
        # Also check for xiaohongshu.com or xhslink.com in URL
        return "xiaohongshu.com" in url or "xhslink.com" in url or "xhs.cn" in url

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract content ID from URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # Try to extract ID from generic URL
        # Pattern: any alphanumeric ID at the end of path
        generic_match = re.search(r"/([a-zA-Z0-9]{20,})", url)
        if generic_match:
            return generic_match.group(1)

        # Return URL hash as fallback ID
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]

    @classmethod
    def is_available(cls) -> bool:
        """Check if yt-dlp is available."""
        return shutil.which("yt-dlp") is not None

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "mp4",
        quality: str = "high",
    ) -> DownloadResult:
        """Download video from Xiaohongshu post."""
        logger.info(f"Starting Xiaohongshu video download for: {url}")

        try:
            content_id = self.extract_content_id(url)
            logger.info(f"Extracted content ID: {content_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                output_template = str(output_path)
            else:
                output_template = str(self.download_dir / "%(title).100s [%(id)s].%(ext)s")

            # Quality mapping - use flexible format selection
            format_spec = {
                "low": "worst",
                "medium": "best[height<=480]/best",
                "high": "best[height<=720]/best",
                "highest": "best",
            }.get(quality, "best")

            cmd = [
                self._yt_dlp_path,
                "--no-progress",
                "-f", format_spec,
                "-o", output_template,
                "--print-json",
                "--merge-output-format", "mp4",
                "--recode-video", "mp4",  # Recode to mp4 if needed
                # Xiaohongshu-specific options
                "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Referer:https://www.xiaohongshu.com/",
                # Parallel fragment downloads
                "--concurrent-fragments", "16",
                "--fragment-retries", "5",
            ]

            cmd.append(url)

            logger.info("Running yt-dlp for Xiaohongshu video...")

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
                    raise ContentNotFoundError(f"Content not found: {content_id}")
                if "private" in error_msg.lower() or "login" in error_msg.lower():
                    raise ContentNotFoundError(f"Content is private or requires login: {content_id}")
                if "no video" in error_msg.lower() or "Unsupported URL" in error_msg:
                    raise ContentNotFoundError(f"No video found at this URL (may be image-only post): {url}")

                raise AudioGrabError(f"yt-dlp failed: {error_msg[:500]}")

            # Parse JSON output
            output = stdout.decode().strip()
            metadata = None
            file_path = None

            for line in output.split('\n'):
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                        file_path = Path(data.get('_filename', data.get('filename', '')))

                        # Extract title
                        title = data.get('title', '') or data.get('description', '')[:100] or '小红书视频'
                        if len(title) > 100:
                            title = title[:97] + '...'

                        metadata = AudioMetadata(
                            platform=Platform.XIAOHONGSHU,
                            content_id=data.get('id', content_id),
                            title=title,
                            creator_username=data.get('uploader_id') or data.get('channel_id'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            duration_seconds=data.get('duration'),
                            artwork_url=data.get('thumbnail'),
                            description=data.get('description', '')[:500] if data.get('description') else None,
                        )
                        break
                    except json.JSONDecodeError:
                        continue

            # Find output file if not in JSON
            if not file_path or not file_path.exists():
                for ext in ['.mp4', '.webm', '.mkv']:
                    matches = list(self.download_dir.glob(f"*{content_id}*{ext}"))
                    if matches:
                        file_path = matches[0]
                        break

                # Also try to find any recent mp4 file
                if not file_path or not file_path.exists():
                    mp4_files = sorted(
                        self.download_dir.glob("*.mp4"),
                        key=lambda f: f.stat().st_mtime,
                        reverse=True
                    )
                    if mp4_files:
                        file_path = mp4_files[0]

            if not file_path or not file_path.exists():
                raise AudioGrabError("Download completed but output file not found")

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
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=f"Unexpected error: {e}",
            )

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for Xiaohongshu post without downloading."""
        try:
            content_id = self.extract_content_id(url)

            cmd = [
                self._yt_dlp_path,
                "--no-download",
                "--print-json",
                "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Referer:https://www.xiaohongshu.com/",
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
                        title = data.get('title', '') or data.get('description', '')[:100] or '小红书视频'
                        if len(title) > 100:
                            title = title[:97] + '...'

                        return AudioMetadata(
                            platform=Platform.XIAOHONGSHU,
                            content_id=data.get('id', content_id),
                            title=title,
                            creator_username=data.get('uploader_id') or data.get('channel_id'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            duration_seconds=data.get('duration'),
                            artwork_url=data.get('thumbnail'),
                            description=data.get('description', '')[:500] if data.get('description') else None,
                        )
                    except json.JSONDecodeError:
                        continue

            return None

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
