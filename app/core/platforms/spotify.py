"""Spotify downloader implementation using spotDL."""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from ...config import get_settings
from ..base import Platform, PlatformDownloader, AudioMetadata, DownloadResult
from ..exceptions import SiftError, ContentNotFoundError, ToolNotFoundError

logger = logging.getLogger(__name__)


class SpotifyDownloader(PlatformDownloader):
    """Downloads from Spotify using spotDL (finds YouTube matches)."""

    PLATFORM = Platform.SPOTIFY

    # URL patterns for Spotify
    URL_PATTERNS = [
        r"open\.spotify\.com/episode/([a-zA-Z0-9]+)",
        r"open\.spotify\.com/track/([a-zA-Z0-9]+)",
        r"open\.spotify\.com/album/([a-zA-Z0-9]+)",
        r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)",
    ]

    def __init__(self, download_dir: Optional[Path] = None):
        """Initialize the Spotify downloader."""
        self.settings = get_settings()

        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            self.download_dir = self.settings.get_download_path()

        self._spotdl_path = shutil.which("spotdl")
        self._yt_dlp_path = (
            shutil.which("yt-dlp")
            or next(
                (p for p in ["/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"]
                 if Path(p).exists()),
                None,
            )
        )

        if not self._spotdl_path and not self._yt_dlp_path:
            raise ToolNotFoundError(
                "Neither spotdl nor yt-dlp found. Install one: brew install yt-dlp"
            )

    @property
    def platform(self) -> Platform:
        return Platform.SPOTIFY

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if URL is a valid Spotify URL."""
        return "open.spotify.com" in url

    @classmethod
    def extract_content_id(cls, url: str) -> str:
        """Extract content ID from Spotify URL."""
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ContentNotFoundError(f"Could not extract Spotify ID from URL: {url}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if spotdl is available."""
        return shutil.which("spotdl") is not None

    def _get_content_type(self, url: str) -> str:
        """Determine the type of Spotify content."""
        if "/track/" in url:
            return "track"
        elif "/episode/" in url:
            return "episode"
        elif "/album/" in url:
            return "album"
        elif "/playlist/" in url:
            return "playlist"
        return "unknown"

    async def download(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "mp3",
        quality: str = "high",
    ) -> DownloadResult:
        """Download from Spotify using spotDL or yt-dlp fallback."""
        logger.info(f"Starting Spotify download for: {url}")

        # Use yt-dlp fallback if spotdl is not installed
        if not self._spotdl_path and self._yt_dlp_path:
            return await self._download_with_ytdlp(url, output_path, output_format, quality)

        try:
            content_id = self.extract_content_id(url)
            content_type = self._get_content_type(url)
            logger.info(f"Spotify {content_type} ID: {content_id}")

            self.download_dir.mkdir(parents=True, exist_ok=True)

            # Map quality to bitrate
            bitrate_map = {
                "low": "128k",
                "medium": "192k",
                "high": "256k",
                "highest": "320k",
            }
            bitrate = bitrate_map.get(quality, "256k")

            # Build spotdl command
            # For mp4, download as mp3 first then convert
            download_format = "mp3" if output_format == "mp4" else output_format
            needs_conversion = output_format == "mp4"

            cmd = [
                self._spotdl_path,
                url,
                "-o", str(self.download_dir),
                "--output-format", download_format if download_format in ["mp3", "m4a", "flac", "ogg", "opus"] else "mp3",
            ]

            logger.info("Running spotdl... (this may take a while)")
            logger.debug(f"Command: {' '.join(cmd[:6])}...")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.download_dir),
            )

            stdout, stderr = await process.communicate()

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            # spotdl prints to stderr even on success (warnings); check both
            combined_output = f"{stderr_text}\n{stdout_text}".strip()

            if process.returncode != 0:
                logger.error(f"spotdl error: {combined_output}")

                if "rate" in combined_output.lower() and "limit" in combined_output.lower():
                    raise SiftError(
                        "Spotify rate limited — too many requests. "
                        "Wait 10–30 minutes before trying again. "
                        "If this persists, try a different network or use a VPN."
                    )

                if "no results" in combined_output.lower() or "not found" in combined_output.lower():
                    raise ContentNotFoundError(f"Could not find audio for: {url}")

                raise SiftError(f"spotdl failed: {combined_output[:500]}")

            # Find the downloaded file
            # spotdl outputs files in format: "Artist - Title.ext"
            file_path = None
            ext = f".{download_format}" if download_format in ["mp3", "m4a", "flac", "ogg", "opus"] else ".mp3"

            # Look for recently created files
            for f in self.download_dir.glob(f"*{ext}"):
                # Check if file was created recently (within last 5 minutes)
                if f.stat().st_mtime > (asyncio.get_event_loop().time() - 300):
                    file_path = f
                    break

            # If not found, try to find any matching file
            if not file_path:
                matches = list(self.download_dir.glob(f"*{ext}"))
                if matches:
                    # Get the most recently modified
                    file_path = max(matches, key=lambda p: p.stat().st_mtime)

            if not file_path or not file_path.exists():
                raise SiftError("Download completed but output file not found")

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

            # Extract metadata from filename
            filename = file_path.stem
            parts = filename.split(" - ", 1)
            artist = parts[0] if len(parts) > 1 else None
            title = parts[1] if len(parts) > 1 else filename

            metadata = AudioMetadata(
                platform=Platform.SPOTIFY,
                content_id=content_id,
                title=title,
                creator_name=artist,
            )

            file_size = file_path.stat().st_size

            logger.info(f"Download complete: {file_path}")
            logger.info(f"File size: {file_size / (1024*1024):.2f} MB")

            return DownloadResult(
                success=True,
                file_path=file_path,
                metadata=metadata,
                file_size_bytes=file_size,
            )

        except (ContentNotFoundError, SiftError, ToolNotFoundError) as e:
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

    async def _download_with_ytdlp(
        self,
        url: str,
        output_path: Optional[Path] = None,
        output_format: str = "mp3",
        quality: str = "high",
    ) -> DownloadResult:
        """Fallback: download Spotify content using yt-dlp."""
        logger.info("Using yt-dlp fallback for Spotify download")

        try:
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
                "--concurrent-fragments", "16",
                "--fragment-retries", "5",
            ]

            if download_format == "mp3":
                quality_map = {"low": "64K", "medium": "128K", "high": "192K", "highest": "320K"}
                cmd.extend(["--audio-quality", quality_map.get(quality, "192K")])

            cmd.append(url)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise SiftError(f"yt-dlp failed for Spotify: {error_msg[:500]}")

            # Parse JSON output
            output = stdout.decode().strip()
            file_path = None
            metadata = None

            for line in output.split('\n'):
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                        file_path = Path(data.get('_filename', data.get('filename', '')))
                        metadata = AudioMetadata(
                            platform=Platform.SPOTIFY,
                            content_id=data.get('id', ''),
                            title=data.get('title', 'Unknown'),
                            creator_name=data.get('uploader') or data.get('artist'),
                            duration_seconds=data.get('duration'),
                        )
                        break
                    except json.JSONDecodeError:
                        continue

            if not file_path or not file_path.exists():
                raise SiftError("Download completed but output file not found")

            # Convert to mp4 if needed
            if needs_conversion:
                from ..converter import AudioConverter
                converter = AudioConverter()
                file_path = await converter.convert(
                    input_path=file_path,
                    output_format=output_format,
                    quality=quality,
                    keep_original=False,
                )

            file_size = file_path.stat().st_size
            logger.info(f"Download complete: {file_path} ({file_size / (1024*1024):.2f} MB)")

            return DownloadResult(
                success=True,
                file_path=file_path,
                metadata=metadata,
                file_size_bytes=file_size,
            )

        except (SiftError,) as e:
            return DownloadResult(success=False, file_path=None, metadata=None, error=str(e))
        except Exception as e:
            logger.exception(f"yt-dlp fallback error: {e}")
            return DownloadResult(success=False, file_path=None, metadata=None, error=str(e))

    async def get_metadata(self, url: str) -> Optional[AudioMetadata]:
        """Get metadata for Spotify content without downloading."""
        try:
            content_id = self.extract_content_id(url)
            content_type = self._get_content_type(url)

            if not self._spotdl_path:
                return AudioMetadata(
                    platform=Platform.SPOTIFY,
                    content_id=content_id,
                    title=f"Spotify {content_type}",
                )

            # Use spotdl to get metadata
            cmd = [
                self._spotdl_path,
                "save",
                url,
                "--save-file", "/dev/stdout",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return None

            # Try to parse JSON output
            try:
                output = stdout.decode().strip()
                if output.startswith("["):
                    data = json.loads(output)
                    if data:
                        item = data[0]
                        return AudioMetadata(
                            platform=Platform.SPOTIFY,
                            content_id=content_id,
                            title=item.get("name", "Unknown"),
                            creator_name=", ".join(item.get("artists", [])),
                            duration_seconds=item.get("duration"),
                            artwork_url=item.get("cover_url"),
                        )
            except json.JSONDecodeError:
                pass

            # Return basic metadata
            return AudioMetadata(
                platform=Platform.SPOTIFY,
                content_id=content_id,
                title=f"Spotify {content_type}",
            )

        except Exception as e:
            logger.warning(f"Failed to get metadata: {e}")
            return None
