"""Audio format converter using FFmpeg."""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from ..exceptions import FFmpegError

logger = logging.getLogger(__name__)


# What ffprobe must report for a file to already *be* each target format, as
# (container names, audio codecs). `None` codecs = any codec in that container.
# mp4 matches on container alone so a video's picture track is never dropped
# by an audio-only (-vn) re-encode.
_ALREADY_IN_FORMAT: dict[str, tuple[set[str], Optional[set[str]]]] = {
    "mp3": ({"mp3"}, {"mp3"}),
    "m4a": ({"mp4", "m4a", "mov"}, {"aac", "alac"}),
    "mp4": ({"mp4", "mov"}, None),
    "aac": ({"aac"}, {"aac"}),
    "wav": ({"wav"}, None),
    "ogg": ({"ogg"}, {"vorbis", "opus"}),
    "flac": ({"flac"}, {"flac"}),
}


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

        # Decide by what the bytes are, not what the file is called: a
        # download saved under the requested name (`-o episode.m4a`) can hold
        # MP3 data, and a name guessed from a URL can lie either way.
        if await self._already_in_format(input_path, output_format):
            if output_path == input_path:
                logger.info("Already %s, skipping conversion", output_format)
                return input_path
            # Right format, wrong name or place: move/copy, don't re-encode.
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if keep_original:
                shutil.copy2(input_path, output_path)
            else:
                shutil.move(str(input_path), str(output_path))
            logger.info("Already %s, saved as %s without re-encoding", output_format, output_path)
            return output_path

        # Converting a file onto its own path: ffmpeg can't read and write the
        # same file, so encode to a sibling and swap it in afterwards.
        in_place = output_path == input_path
        final_path = output_path
        if in_place:
            output_path = output_path.with_name(
                f"{output_path.stem}.converting{output_path.suffix}"
            )

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

            if in_place:
                os.replace(output_path, final_path)
                output_path = final_path
            # Delete original if requested
            elif not keep_original:
                input_path.unlink()
                logger.info(f"Deleted original file: {input_path}")

            output_size = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"Conversion complete: {output_path} ({output_size:.2f} MB)")

            return output_path

        except FFmpegError:
            if in_place:
                output_path.unlink(missing_ok=True)
            raise
        except Exception as e:
            if in_place:
                output_path.unlink(missing_ok=True)
            raise FFmpegError(f"Failed to convert: {e}")

    async def _already_in_format(self, path: Path, output_format: str) -> bool:
        """Whether `path`'s bytes already are `output_format`, per ffprobe.

        Without ffprobe (or for a format with no rule) this falls back to the
        old extension comparison rather than forcing a re-encode.
        """
        rule = _ALREADY_IN_FORMAT.get(output_format)
        ffprobe = shutil.which("ffprobe")
        if rule is None or ffprobe is None:
            return path.suffix.lower() == f".{output_format}"

        process = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "format=format_name:stream=codec_name",
            "-of", "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return False  # unreadable: let ffmpeg try, and report its error
        data = json.loads(stdout or b"{}")
        containers = set((data.get("format", {}).get("format_name") or "").split(","))
        streams = data.get("streams") or []
        codec = (streams[0].get("codec_name") or "").lower() if streams else ""

        allowed_containers, allowed_codecs = rule
        if not containers & allowed_containers:
            return False
        return allowed_codecs is None or codec in allowed_codecs

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
