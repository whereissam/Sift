"""Audio format converter using FFmpeg."""

import asyncio
import logging
import shutil
from pathlib import Path

from ..exceptions import FFmpegError

logger = logging.getLogger(__name__)


class AudioConverter:
    """FFmpeg-based audio format converter."""

    # Quality presets for MP3 encoding
    QUALITY_PRESETS = {
        "low": "64k",
        "medium": "128k",
        "high": "192k",
        "highest": "320k",
    }

    def __init__(self):
        """Initialize the converter."""
        self._ffmpeg_path = self._find_ffmpeg()

    def _find_ffmpeg(self) -> str:
        """Find FFmpeg binary in system PATH."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise FFmpegError(
                "FFmpeg not found in PATH. Please install it: brew install ffmpeg"
            )
        return ffmpeg

    @staticmethod
    def is_ffmpeg_available() -> bool:
        """Check if FFmpeg is available in system PATH."""
        return shutil.which("ffmpeg") is not None

    async def convert(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        output_format: str = "mp3",
        quality: str = "high",
        keep_original: bool = True,
    ) -> Path:
        """
        Convert audio file to another format.

        Args:
            input_path: Path to input audio file
            output_path: Path for output file (auto-generated if not provided)
            output_format: Target format (mp3, mp4, aac, wav, ogg, flac)
            quality: Quality preset for lossy formats (low, medium, high, highest)
            keep_original: Whether to keep the original file

        Returns:
            Path to the converted file

        Raises:
            FFmpegError: If conversion fails
        """
        input_path = Path(input_path)

        if not input_path.exists():
            raise FFmpegError(f"Input file not found: {input_path}")

        # Determine output path
        if output_path is None:
            output_path = input_path.with_suffix(f".{output_format}")
        else:
            output_path = Path(output_path)

        # Don't convert if same format
        if input_path.suffix.lower() == output_path.suffix.lower():
            logger.info("Input and output formats are the same, skipping conversion")
            return input_path

        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",  # Overwrite output
            "-i", str(input_path),
            # Drop any attached-picture / cover-art video stream. Without this,
            # ffmpeg auto-maps an embedded PNG cover and tries to encode it as
            # H.264 into the audio container (e.g. m4a/ipod), which fails with
            # "codec not currently supported in container".
            "-vn",
        ]

        # Add format-specific options
        if output_format == "mp3":
            bitrate = self.QUALITY_PRESETS.get(quality, "192k")
            cmd.extend([
                "-c:a", "libmp3lame",
                "-b:a", bitrate,
            ])
        elif output_format == "mp4":
            # MP4 container with AAC audio
            cmd.extend([
                "-c:a", "aac",
                "-b:a", self.QUALITY_PRESETS.get(quality, "192k"),
            ])
        elif output_format in ("m4a", "aac"):
            cmd.extend([
                "-c:a", "aac",
                "-b:a", self.QUALITY_PRESETS.get(quality, "192k"),
            ])
        elif output_format == "wav":
            cmd.extend([
                "-c:a", "pcm_s16le",
            ])
        elif output_format == "ogg":
            cmd.extend([
                "-c:a", "libvorbis",
                "-q:a", "6",  # Quality 0-10, 6 is ~192kbps
            ])
        elif output_format == "flac":
            cmd.extend([
                "-c:a", "flac",
            ])
        else:
            # Default: copy codec if possible
            cmd.extend(["-c:a", "copy"])

        cmd.append(str(output_path))

        logger.info(f"Converting {input_path.name} to {output_format}...")

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
                raise FFmpegError(f"Conversion failed: {error_msg[:500]}")

            if not output_path.exists():
                raise FFmpegError(f"Output file was not created: {output_path}")

            # Delete original if requested
            if not keep_original and input_path != output_path:
                input_path.unlink()
                logger.info(f"Deleted original file: {input_path}")

            output_size = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"Conversion complete: {output_path} ({output_size:.2f} MB)")

            return output_path

        except FFmpegError:
            raise
        except Exception as e:
            raise FFmpegError(f"Failed to convert: {e}")

    async def to_mp3(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        quality: str = "high",
    ) -> Path:
        """Convert to MP3."""
        return await self.convert(input_path, output_path, "mp3", quality)

    async def to_mp4(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        quality: str = "high",
    ) -> Path:
        """Convert to MP4."""
        return await self.convert(input_path, output_path, "mp4", quality)

    async def to_wav(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert to WAV (lossless)."""
        return await self.convert(input_path, output_path, "wav")

    async def to_flac(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert to FLAC (lossless)."""
        return await self.convert(input_path, output_path, "flac")


# Convenience function
async def convert_audio(
    input_path: str | Path,
    output_format: str = "mp3",
    quality: str = "high",
) -> Path:
    """
    Convert audio file to another format.

    Args:
        input_path: Path to input file
        output_format: Target format (mp3, mp4, aac, wav, ogg, flac)
        quality: Quality preset for lossy formats

    Returns:
        Path to converted file
    """
    converter = AudioConverter()
    return await converter.convert(input_path, output_format=output_format, quality=quality)
