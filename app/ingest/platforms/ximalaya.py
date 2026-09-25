"""喜马拉雅 (Ximalaya) audio downloader implementation using yt-dlp."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..settings import IngestSettings, get_ingest_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult, resolve_yt_dlp, yt_dlp_available
from ..exceptions import SiftError, ContentNotFoundError

logger = logging.getLogger(__name__)


class XimalayaDownloader(PlatformDownloader):
    """Downloads podcast episodes from 喜马拉雅 (Ximalaya) using yt-dlp.

    Supports single episodes (``ximalaya.com/sound/<id>``). Album / series
    pages (e.g. ``ximalaya.com/<category>/<album_id>/``) are not supported —
    yt-dlp's Ximalaya album extractor is currently broken, and downloading an
    entire album is a different (playlist) flow. Users should open a single
    episode and paste its ``/sound/`` link.
    """

    PLATFORM = Platform.XIMALAYA

    # URL patterns for Ximalaya single episodes ("sounds").
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?ximalaya\.com/sound/(\d+)",
        r"(?:https?://)?(?:www\.)?ximalaya\.com/[^/]+/sound/(\d+)",
    ]

    def __init__(
        self,
        download_dir: Optional[Path] = None,
        settings: Optional[IngestSettings] = None,
    ):
        """Initialize the Ximalaya downloader."""
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
        return Platform.XIMALAYA

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Handle any ximalaya.com URL so we can return a clear message."""
        return "ximalaya.com" in url

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract the sound (episode) ID from a Ximalaya URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ContentNotFoundError(
            "Ximalaya album/series links aren't supported yet. Open a single "
            "episode and paste its link (it should look like "
            "ximalaya.com/sound/123456789)."
        )

    @classmethod
    def is_available(cls) -> bool:
        """Check if yt-dlp is available."""
        return yt_dlp_available()

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "m4a",
        quality: str = "high",
    ) -> DownloadResult:
        """Download a single audio episode from Ximalaya."""
        logger.info(f"Starting Ximalaya download for: {url}")

        try:
            sound_id = self.extract_content_id(url)
            logger.info(f"Extracted sound ID: {sound_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            if output_path:
                output_template = str(output_path)
            else:
                output_template = str(self.download_dir / "%(title)s [%(id)s].%(ext)s")

            # For mp4, download as m4a first then convert.
            download_format = "m4a" if output_format == "mp4" else output_format
            needs_conversion = output_format == "mp4"

            cmd = [
                self._yt_dlp_path,
                "--no-progress",
                "--no-playlist",  # never expand into a whole album
                "-x",  # extract audio
                "--audio-format", download_format if download_format == "mp3" else "m4a",
                "-o", output_template,
                "--print-json",
                "--fragment-retries", "5",
            ]

            if download_format == "mp3":
                quality_map = {"low": "64K", "medium": "128K", "high": "192K", "highest": "320K"}
                cmd.extend(["--audio-quality", quality_map.get(quality, "192K")])

            cmd.append(url)

            logger.info("Running yt-dlp for Ximalaya...")

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
                    raise ContentNotFoundError(f"Episode not found: {sound_id}")
                if "vip" in error_msg.lower() or "paid" in error_msg.lower():
                    raise ContentNotFoundError(
                        f"This Ximalaya episode is paid / VIP-only: {sound_id}"
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
                            platform=Platform.XIMALAYA,
                            content_id=str(data.get('id', sound_id)),
                            title=data.get('title', 'Unknown'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            creator_username=data.get('uploader_id'),
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
                    matches = list(self.download_dir.glob(f"*{sound_id}*{ext}"))
                    if matches:
                        file_path = matches[0]
                        break

            if not file_path or not file_path.exists():
                raise SiftError("Download completed but output file not found")

            # Convert to mp4 if requested
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
                success=False, file_path=None, metadata=None, error=str(e)
            )
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return DownloadResult(
                success=False, file_path=None, metadata=None, error=f"Unexpected error: {e}"
            )

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for a Ximalaya episode without downloading."""
        try:
            sound_id = self.extract_content_id(url)

            cmd = [
                self._yt_dlp_path,
                "--no-playlist",
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
                            platform=Platform.XIMALAYA,
                            content_id=str(data.get('id', sound_id)),
                            title=data.get('title', 'Unknown'),
                            creator_name=data.get('uploader') or data.get('channel'),
                            creator_username=data.get('uploader_id'),
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
