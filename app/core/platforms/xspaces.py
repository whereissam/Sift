"""X Spaces downloader implementation using yt-dlp."""

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


class XSpacesDownloader(PlatformDownloader):
    """Downloads Twitter/X Spaces using yt-dlp."""

    # URL patterns for X Spaces
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/i/spaces/([a-zA-Z0-9]+)",
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/spaces/([a-zA-Z0-9]+)",
    ]

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the X Spaces downloader."""
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
        return Platform.X_SPACES

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid X Spaces URL."""
        return any(re.search(pattern, url) for pattern in cls.URL_PATTERNS)

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract Space ID from URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ContentNotFoundError(f"Could not extract Space ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if yt-dlp is available."""
        return shutil.which("yt-dlp") is not None

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
        """Download a Twitter Space."""
        logger.info(f"Starting X Spaces download for: {url}")

        try:
            space_id = self.extract_content_id(url)
            logger.info(f"Extracted Space ID: {space_id}")

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
                "--no-progress",
                "-x",
                "--audio-format", download_format if download_format == "mp3" else "m4a",
                "-o", output_template,
                "--print-json",
                # Parallel HLS fragment downloads (major speedup for Spaces)
                "--concurrent-fragments", "16",
                "--fragment-retries", "5",
                "--socket-timeout", "30",
            ]

            if download_format == "mp3":
                quality_map = {"low": "64K", "medium": "128K", "high": "192K", "highest": "320K"}
                cmd.extend(["--audio-quality", quality_map.get(quality, "192K")])

            cmd.append(url)

            logger.info("Running yt-dlp...")

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
                    raise ContentNotFoundError(f"Space not found: {space_id}")

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
                        metadata = AudioMetadata(
                            platform=Platform.X_SPACES,
                            content_id=data.get('id', space_id),
                            title=data.get('title', 'Unknown'),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader'),
                            duration_seconds=data.get('duration'),
                        )
                        break
                    except json.JSONDecodeError:
                        continue

            # Find output file if not in JSON
            if not file_path or not file_path.exists():
                for ext in ['.m4a', '.mp3', '.aac']:
                    matches = list(self.download_dir.glob(f"*{space_id}*{ext}"))
                    if matches:
                        file_path = matches[0]
                        break

            if not file_path or not file_path.exists():
                raise AudioGrabError("Download completed but output file not found")

            # Convert to mp4 if needed
            if needs_conversion:
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
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                metadata=None,
                error=f"Unexpected error: {e}",
            )

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for a Twitter Space without downloading."""
        try:
            space_id = self.extract_content_id(url)

            cmd = [
                self._yt_dlp_path,
                "--no-download",
                "--print-json",
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
                            platform=Platform.X_SPACES,
                            content_id=data.get('id', space_id),
                            title=data.get('title', 'Unknown'),
                            creator_username=data.get('uploader_id'),
                            creator_name=data.get('uploader'),
                            duration_seconds=data.get('duration'),
                        )
                    except json.JSONDecodeError:
                        continue

            return None

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
