"""Audio processing and merging using FFmpeg."""

import asyncio
import logging
import shutil
from pathlib import Path

from ..exceptions import FFmpegError

logger = logging.getLogger(__name__)


class AudioMerger:
    """FFmpeg-based audio processing for HLS streams."""

    # Quality presets for MP3 encoding
    QUALITY_PRESETS = {
        "low": "64k",
        "medium": "128k",
        "high": "192k",
        "highest": "320k",
    }

    def __init__(self):
        """Initialize the audio merger."""
        self._ffmpeg_path = self._find_ffmpeg()

    def _find_ffmpeg(self) -> str:
        """Find FFmpeg binary in system PATH."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise FFmpegError(
                "FFmpeg not found in PATH. Please install FFmpeg."
            )
        return ffmpeg

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg is available in system PATH."""
        return shutil.which("ffmpeg") is not None

    async def merge_hls_stream(
        self,
        m3u8_url: str,
        output_path: str | Path,
        format: str = "m4a",
        copy_codec: bool = True,
    ) -> Path:
        """
        Download and merge HLS stream into a single audio file.

        Args:
            m3u8_url: URL to the m3u8 playlist
            output_path: Path for the output file (extension will be adjusted)
            format: Output format (m4a, mp3, aac)
            copy_codec: If True, copy codec without re-encoding (faster)

        Returns:
            Path to the output file

        Raises:
            FFmpegError: If FFmpeg fails
        """
        output_path = Path(output_path)

        # Ensure correct extension
        if format == "m4a":
            output_path = output_path.with_suffix(".m4a")
        elif format == "mp3":
            output_path = output_path.with_suffix(".mp3")
        elif format == "aac":
            output_path = output_path.with_suffix(".aac")

        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",  # Overwrite output
            "-i", m3u8_url,
            "-vn",  # No video
        ]

        if copy_codec and format != "mp3":
            # Copy codec for faster processing (works for m4a/aac)
            cmd.extend(["-c", "copy"])
        elif format == "mp3":
            # MP3 requires re-encoding
            cmd.extend([
                "-c:a", "libmp3lame",
                "-b:a", self.QUALITY_PRESETS.get("high", "192k"),
            ])
        else:
            # Default: copy
            cmd.extend(["-c", "copy"])

        cmd.append(str(output_path))

        logger.info(f"Running FFmpeg: {' '.join(cmd[:6])}...")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"FFmpeg error: {error_msg}")
                raise FFmpegError(f"FFmpeg failed: {error_msg[:500]}")

            if not output_path.exists():
                raise FFmpegError(f"Output file was not created: {output_path}")

            logger.info(f"Successfully created: {output_path}")
            return output_path

        except asyncio.CancelledError:
            logger.warning("FFmpeg process was cancelled")
            raise
        except FFmpegError:
            raise
        except Exception as e:
            raise FFmpegError(f"Failed to run FFmpeg: {e}")

    async def convert_to_mp3(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        quality: str = "high",
    ) -> Path:
        """
        Convert an audio file to MP3.

        Args:
            input_path: Path to input audio file
            output_path: Path for output MP3 (default: same name with .mp3)
            quality: Quality preset (low, medium, high, highest)

        Returns:
            Path to the MP3 file

        Raises:
            FFmpegError: If conversion fails
        """
        input_path = Path(input_path)

        if output_path is None:
            output_path = input_path.with_suffix(".mp3")
        else:
            output_path = Path(output_path)

        bitrate = self.QUALITY_PRESETS.get(quality, "192k")

        cmd = [
            self._ffmpeg_path,
            "-y",
            "-i", str(input_path),
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
            str(output_path),
        ]

        logger.info(f"Converting to MP3 at {bitrate}...")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise FFmpegError(f"MP3 conversion failed: {error_msg[:500]}")

            return output_path

        except FFmpegError:
            raise
        except Exception as e:
            raise FFmpegError(f"Failed to convert to MP3: {e}")

    async def get_duration(self, file_path: str | Path) -> float:
        """
        Get the duration of an audio file in seconds.

        Args:
            file_path: Path to the audio file

        Returns:
            Duration in seconds
        """
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise FFmpegError("ffprobe not found in PATH")

        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise FFmpegError("Failed to get duration")

            return float(stdout.decode().strip())

        except ValueError:
            raise FFmpegError("Could not parse duration")
        except Exception as e:
            raise FFmpegError(f"Failed to get duration: {e}")
