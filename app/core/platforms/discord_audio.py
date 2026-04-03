"""Discord audio downloader implementation."""

import asyncio
import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import httpx

from ...config import get_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import SiftError, ContentNotFoundError

logger = logging.getLogger(__name__)


class DiscordAudioDownloader(PlatformDownloader):
    """Downloads audio files from Discord CDN.

    Supports:
    - Discord attachment URLs (cdn.discordapp.com/attachments/...)
    - Discord media URLs (media.discordapp.net/attachments/...)
    - Discord voice messages
    - Discord soundboard clips
    """

    PLATFORM = Platform.DISCORD

    # URL patterns for Discord audio
    URL_PATTERNS = [
        # CDN attachment URLs
        r"(?:https?://)?cdn\.discordapp\.com/attachments/(\d+)/(\d+)/([^?]+)",
        # Media URLs (often used for previews)
        r"(?:https?://)?media\.discordapp\.net/attachments/(\d+)/(\d+)/([^?]+)",
        # Ephemeral attachment URLs
        r"(?:https?://)?cdn\.discordapp\.com/ephemeral-attachments/(\d+)/(\d+)/([^?]+)",
    ]

    # Supported audio extensions
    AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus", ".webm"}

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the Discord audio downloader."""
        self.settings = get_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

    @property
    def platform(self) -> Platform:
        return Platform.DISCORD

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid Discord audio URL."""
        if not any(re.search(pattern, url) for pattern in cls.URL_PATTERNS):
            return False

        # Extract filename and check if it's an audio file
        parsed = urlparse(url)
        path = unquote(parsed.path)
        ext = Path(path).suffix.lower()

        return ext in cls.AUDIO_EXTENSIONS

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract content ID from Discord URL.

        Returns a combination of channel_id/message_id/filename for uniqueness.
        """
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                channel_id = match.group(1)
                attachment_id = match.group(2)
                filename = match.group(3)
                # Remove query params from filename
                filename = filename.split("?")[0]
                return f"{channel_id}_{attachment_id}_{filename}"

        # Fallback: hash the URL
        return hashlib.md5(url.encode()).hexdigest()[:16]

    @classmethod
    def is_available(cls) -> bool:
        """Check if downloader is available (always true for HTTP downloads)."""
        return True

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        sanitized = re.sub(r'\s+', '_', sanitized)
        return sanitized[:100]

    def _extract_filename_from_url(self, url: str) -> str:
        """Extract the original filename from the Discord URL."""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = Path(path).name
        # Remove query params
        filename = filename.split("?")[0]
        return self._sanitize_filename(filename)

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> DownloadResult:
        """Download audio from Discord CDN."""
        logger.info(f"Starting Discord audio download for: {url}")

        try:
            content_id = self.extract_content_id(url)
            logger.info(f"Content ID: {content_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            # Extract original filename
            original_filename = self._extract_filename_from_url(url)
            original_ext = Path(original_filename).suffix.lower()

            # Determine output filename
            if output_path:
                file_path = output_path
            else:
                # Use original filename with potential format conversion
                base_name = Path(original_filename).stem
                target_ext = f".{output_format}" if output_format else original_ext
                file_path = self.download_dir / f"{base_name}{target_ext}"

            # Download the file
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0),
                follow_redirects=True,
            ) as client:
                # Discord CDN sometimes requires specific headers
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "*/*",
                }

                logger.info("Downloading from Discord CDN...")
                response = await client.get(url, headers=headers)

                if response.status_code == 404:
                    raise ContentNotFoundError(f"Discord file not found or expired: {url}")

                if response.status_code == 403:
                    raise SiftError(
                        "Access denied. The link may have expired or require authentication."
                    )

                if response.status_code != 200:
                    raise SiftError(
                        f"Failed to download from Discord: HTTP {response.status_code}"
                    )

                # Save the downloaded content
                temp_path = self.download_dir / f"discord_temp_{content_id}{original_ext}"
                temp_path.write_bytes(response.content)
                logger.info(f"Downloaded to temp file: {temp_path}")

            # Convert format if needed
            needs_conversion = output_format and f".{output_format}" != original_ext
            if needs_conversion:
                from ..converter import AudioConverter

                logger.info(f"Converting from {original_ext} to {output_format}...")
                converter = AudioConverter()
                converted_path = await converter.convert(
                    input_path=temp_path,
                    output_format=output_format,
                    quality=quality,
                    keep_original=False,
                )
                file_path = converted_path
            else:
                # Just move the temp file to final location
                if temp_path != file_path:
                    shutil.move(str(temp_path), str(file_path))

            file_size = file_path.stat().st_size

            # Create metadata
            metadata = AudioMetadata(
                platform=Platform.DISCORD,
                content_id=content_id,
                title=Path(original_filename).stem,
                creator_name="Discord",
                description=f"Downloaded from Discord CDN",
            )

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
        """Get metadata for Discord audio without downloading.

        For Discord, we can only get basic info from the URL since there's
        no API to query file metadata.
        """
        try:
            content_id = self.extract_content_id(url)
            filename = self._extract_filename_from_url(url)

            # Try to get file size via HEAD request
            file_size = None
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0),
                    follow_redirects=True,
                ) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    }
                    response = await client.head(url, headers=headers)
                    if response.status_code == 200:
                        content_length = response.headers.get("content-length")
                        if content_length:
                            file_size = int(content_length)
            except Exception:
                pass

            return AudioMetadata(
                platform=Platform.DISCORD,
                content_id=content_id,
                title=Path(filename).stem,
                creator_name="Discord",
                description=f"Audio file from Discord",
            )

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
