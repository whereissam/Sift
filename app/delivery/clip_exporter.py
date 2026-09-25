"""Audio clip exporter using FFmpeg for social media platforms."""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .clip_generator import SocialPlatform
from sift_core.exceptions import FFmpegError

logger = logging.getLogger(__name__)


@dataclass
class ClipExportResult:
    """Result of a clip export operation."""

    success: bool
    clip_id: str
    platform: SocialPlatform
    file_path: Optional[str] = None
    file_size_mb: Optional[float] = None
    duration: Optional[float] = None
    format: str = "mp3"
    error: Optional[str] = None


class ClipExporter:
    """FFmpeg-based audio clip exporter for social media."""

    # Quality presets for audio encoding
    QUALITY_PRESETS = {
        "low": "64k",
        "medium": "128k",
        "high": "192k",
        "highest": "320k",
    }

    # Platform-specific max durations in seconds
    PLATFORM_MAX_DURATION = {
        SocialPlatform.TIKTOK: 180,
        SocialPlatform.INSTAGRAM_REELS: 90,
        SocialPlatform.YOUTUBE_SHORTS: 60,
        SocialPlatform.TWITTER_X: 140,
    }

    def __init__(self):
        """Initialize the exporter."""
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

    async def export_clip(
        self,
        audio_path: str | Path,
        clip_id: str,
        start_time: float,
        end_time: float,
        platform: SocialPlatform,
        output_dir: Optional[str | Path] = None,
        output_format: str = "mp3",
        quality: str = "high",
    ) -> ClipExportResult:
        """Export a clip segment from an audio file.

        Args:
            audio_path: Path to the source audio file
            clip_id: Unique identifier for the clip
            start_time: Start time in seconds
            end_time: End time in seconds
            platform: Target social media platform
            output_dir: Output directory (defaults to same as source)
            output_format: Output format (mp3, mp4, aac, wav)
            quality: Quality preset (low, medium, high, highest)

        Returns:
            ClipExportResult with export details
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            return ClipExportResult(
                success=False,
                clip_id=clip_id,
                platform=platform,
                error=f"Source audio not found: {audio_path}",
            )

        # Calculate duration
        duration = end_time - start_time

        # Validate duration for platform
        max_duration = self.PLATFORM_MAX_DURATION.get(platform, 180)
        if duration > max_duration:
            return ClipExportResult(
                success=False,
                clip_id=clip_id,
                platform=platform,
                error=f"Clip duration ({duration:.1f}s) exceeds {platform.value} max ({max_duration}s)",
            )

        # Determine output path
        if output_dir is None:
            output_dir = audio_path.parent
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        # Generate output filename
        safe_clip_id = clip_id[:8]  # Use first 8 chars of UUID
        output_filename = f"clip_{safe_clip_id}_{platform.value}.{output_format}"
        output_path = output_dir / output_filename

        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",  # Overwrite output
            "-i",
            str(audio_path),
            "-ss",
            str(start_time),  # Start time
            "-t",
            str(duration),  # Duration
        ]

        # Add format-specific encoding options
        if output_format == "mp3":
            bitrate = self.QUALITY_PRESETS.get(quality, "192k")
            cmd.extend(
                [
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    bitrate,
                ]
            )
        elif output_format == "mp4":
            cmd.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    self.QUALITY_PRESETS.get(quality, "192k"),
                ]
            )
        elif output_format == "aac":
            cmd.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    self.QUALITY_PRESETS.get(quality, "192k"),
                ]
            )
        elif output_format == "wav":
            cmd.extend(
                [
                    "-c:a",
                    "pcm_s16le",
                ]
            )
        else:
            # Default: copy codec
            cmd.extend(["-c:a", "copy"])

        cmd.append(str(output_path))

        logger.info(
            f"Exporting clip {clip_id} ({start_time:.1f}s - {end_time:.1f}s) "
            f"for {platform.value}..."
        )

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
                return ClipExportResult(
                    success=False,
                    clip_id=clip_id,
                    platform=platform,
                    error=f"Export failed: {error_msg[:500]}",
                )

            if not output_path.exists():
                return ClipExportResult(
                    success=False,
                    clip_id=clip_id,
                    platform=platform,
                    error=f"Output file was not created: {output_path}",
                )

            file_size = output_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"Clip exported: {output_path.name} ({file_size:.2f} MB, {duration:.1f}s)"
            )

            return ClipExportResult(
                success=True,
                clip_id=clip_id,
                platform=platform,
                file_path=str(output_path),
                file_size_mb=file_size,
                duration=duration,
                format=output_format,
            )

        except FFmpegError:
            raise
        except Exception as e:
            logger.error(f"Failed to export clip: {e}")
            return ClipExportResult(
                success=False,
                clip_id=clip_id,
                platform=platform,
                error=f"Failed to export clip: {e}",
            )

    async def export_all_platforms(
        self,
        audio_path: str | Path,
        clip_id: str,
        start_time: float,
        end_time: float,
        platforms: list[SocialPlatform],
        output_dir: Optional[str | Path] = None,
        output_format: str = "mp3",
        quality: str = "high",
    ) -> dict[SocialPlatform, ClipExportResult]:
        """Export a clip to multiple platforms.

        Args:
            audio_path: Path to the source audio file
            clip_id: Unique identifier for the clip
            start_time: Start time in seconds
            end_time: End time in seconds
            platforms: List of target platforms
            output_dir: Output directory
            output_format: Output format
            quality: Quality preset

        Returns:
            Dictionary mapping platforms to their export results
        """
        results = {}
        duration = end_time - start_time

        for platform in platforms:
            # Check if clip fits platform duration
            max_duration = self.PLATFORM_MAX_DURATION.get(platform, 180)
            if duration > max_duration:
                results[platform] = ClipExportResult(
                    success=False,
                    clip_id=clip_id,
                    platform=platform,
                    error=f"Duration ({duration:.1f}s) exceeds {platform.value} limit ({max_duration}s)",
                )
                continue

            result = await self.export_clip(
                audio_path=audio_path,
                clip_id=clip_id,
                start_time=start_time,
                end_time=end_time,
                platform=platform,
                output_dir=output_dir,
                output_format=output_format,
                quality=quality,
            )
            results[platform] = result

        return results

    async def get_audio_duration(self, audio_path: str | Path) -> Optional[float]:
        """Get the duration of an audio file using FFprobe.

        Args:
            audio_path: Path to the audio file

        Returns:
            Duration in seconds, or None if unable to determine
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            return None

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            logger.warning("FFprobe not found, cannot determine audio duration")
            return None

        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await process.communicate()

            if process.returncode == 0 and stdout:
                return float(stdout.decode().strip())
        except Exception as e:
            logger.error(f"Failed to get audio duration: {e}")

        return None


# Convenience function
async def export_clip(
    audio_path: str | Path,
    clip_id: str,
    start_time: float,
    end_time: float,
    platform: SocialPlatform,
    output_dir: Optional[str | Path] = None,
    quality: str = "high",
) -> ClipExportResult:
    """Export a clip segment from an audio file.

    Args:
        audio_path: Path to the source audio file
        clip_id: Unique identifier for the clip
        start_time: Start time in seconds
        end_time: End time in seconds
        platform: Target social media platform
        output_dir: Output directory
        quality: Quality preset

    Returns:
        ClipExportResult with export details
    """
    exporter = ClipExporter()
    return await exporter.export_clip(
        audio_path=audio_path,
        clip_id=clip_id,
        start_time=start_time,
        end_time=end_time,
        platform=platform,
        output_dir=output_dir,
        quality=quality,
    )
