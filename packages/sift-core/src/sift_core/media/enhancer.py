"""Audio enhancement using FFmpeg filters for voice isolation and noise reduction."""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EnhancementPreset(str, Enum):
    """Audio enhancement presets."""

    NONE = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


@dataclass
class EnhancementResult:
    """Result of audio enhancement."""

    success: bool
    original_path: Path
    enhanced_path: Optional[Path] = None
    provider: str = "ffmpeg"
    preset: EnhancementPreset = EnhancementPreset.NONE
    error: Optional[str] = None


class FFmpegEnhancer:
    """Audio enhancement using FFmpeg filters."""

    # FFmpeg filter chains for each preset
    PRESET_FILTERS = {
        EnhancementPreset.NONE: "",
        # Light: Basic cleanup - remove rumble, light noise reduction, normalize
        EnhancementPreset.LIGHT: "highpass=f=80,afftdn=nf=-25,loudnorm",
        # Medium: Voice-focused - tighter frequency range, stronger noise reduction
        EnhancementPreset.MEDIUM: "highpass=f=100,lowpass=f=8000,afftdn=nf=-20,anlmdn,loudnorm",
        # Heavy: Aggressive filtering for very noisy audio
        EnhancementPreset.HEAVY: "highpass=f=150,lowpass=f=7000,afftdn=nf=-15:tn=1,anlmdn,dynaudnorm,loudnorm",
    }

    async def enhance(
        self,
        input_path: Path,
        output_path: Path,
        preset: EnhancementPreset,
    ) -> bool:
        """
        Apply audio enhancement filters to an audio file.

        Args:
            input_path: Path to input audio file
            output_path: Path for enhanced output file
            preset: Enhancement preset to apply

        Returns:
            True if enhancement succeeded, False otherwise
        """
        if preset == EnhancementPreset.NONE:
            # No enhancement, just copy the file
            shutil.copy(input_path, output_path)
            return True

        filter_chain = self.PRESET_FILTERS.get(preset, "")
        if not filter_chain:
            logger.warning(f"Unknown preset: {preset}, skipping enhancement")
            shutil.copy(input_path, output_path)
            return True

        logger.info(f"Applying {preset.value} enhancement to {input_path.name}")

        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-af", filter_chain,
            "-c:a", "aac",  # Re-encode as AAC
            "-b:a", "192k",  # Good quality bitrate
            str(output_path),
        ]

        try:
            loop = asyncio.get_event_loop()

            def _run_ffmpeg():
                import subprocess
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0, result.stderr

            success, stderr = await loop.run_in_executor(None, _run_ffmpeg)

            if success:
                logger.info(f"Enhancement complete: {output_path.name}")
                return True
            else:
                logger.error(f"FFmpeg enhancement failed: {stderr}")
                return False

        except Exception as e:
            logger.error(f"Enhancement error: {e}")
            return False

    @staticmethod
    def is_available() -> bool:
        """Check if FFmpeg is available."""
        return shutil.which("ffmpeg") is not None


class AudioEnhancer:
    """Main audio enhancement service."""

    def __init__(self):
        self._ffmpeg = FFmpegEnhancer()

    async def enhance(
        self,
        audio_path: Path,
        preset: EnhancementPreset = EnhancementPreset.MEDIUM,
        keep_original: bool = True,
    ) -> EnhancementResult:
        """
        Enhance audio quality using FFmpeg filters.

        Args:
            audio_path: Path to the audio file
            preset: Enhancement preset to apply
            keep_original: If True, creates a new enhanced file; if False, replaces original

        Returns:
            EnhancementResult with success status and paths
        """
        if not audio_path.exists():
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                error=f"Audio file not found: {audio_path}",
            )

        if preset == EnhancementPreset.NONE:
            return EnhancementResult(
                success=True,
                original_path=audio_path,
                enhanced_path=audio_path,
                preset=preset,
            )

        if not self._ffmpeg.is_available():
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                error="FFmpeg not available for audio enhancement",
            )

        # Generate output path
        if keep_original:
            # Create enhanced file with suffix
            enhanced_path = audio_path.parent / f"{audio_path.stem}_enhanced{audio_path.suffix}"
        else:
            # Use temp file, then replace original
            enhanced_path = audio_path.parent / f"{audio_path.stem}_temp_enhanced{audio_path.suffix}"

        try:
            success = await self._ffmpeg.enhance(audio_path, enhanced_path, preset)

            if success:
                if not keep_original:
                    # Replace original with enhanced
                    audio_path.unlink()
                    enhanced_path.rename(audio_path)
                    enhanced_path = audio_path

                return EnhancementResult(
                    success=True,
                    original_path=audio_path,
                    enhanced_path=enhanced_path,
                    preset=preset,
                )
            else:
                # Clean up failed output
                if enhanced_path.exists():
                    enhanced_path.unlink()

                return EnhancementResult(
                    success=False,
                    original_path=audio_path,
                    preset=preset,
                    error="FFmpeg enhancement failed",
                )

        except Exception as e:
            logger.exception(f"Enhancement error: {e}")
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                preset=preset,
                error=str(e),
            )

    async def preview(
        self,
        audio_path: Path,
        preset: EnhancementPreset,
        duration_seconds: int = 30,
    ) -> EnhancementResult:
        """
        Create a short preview of enhanced audio.

        Args:
            audio_path: Path to the audio file
            preset: Enhancement preset to apply
            duration_seconds: Length of preview (default: 30 seconds)

        Returns:
            EnhancementResult with path to preview file
        """
        if not audio_path.exists():
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                error=f"Audio file not found: {audio_path}",
            )

        if not self._ffmpeg.is_available():
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                error="FFmpeg not available",
            )

        # Create preview file path
        preview_path = audio_path.parent / f"{audio_path.stem}_preview{audio_path.suffix}"

        filter_chain = FFmpegEnhancer.PRESET_FILTERS.get(preset, "")
        if not filter_chain:
            filter_chain = "anull"  # Pass-through if no enhancement

        # Build FFmpeg command with duration limit
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(audio_path),
            "-t", str(duration_seconds),
            "-af", filter_chain,
            "-c:a", "aac",
            "-b:a", "128k",
            str(preview_path),
        ]

        try:
            loop = asyncio.get_event_loop()

            def _run_ffmpeg():
                import subprocess
                result = subprocess.run(cmd, capture_output=True, text=True)
                return result.returncode == 0, result.stderr

            success, stderr = await loop.run_in_executor(None, _run_ffmpeg)

            if success:
                return EnhancementResult(
                    success=True,
                    original_path=audio_path,
                    enhanced_path=preview_path,
                    preset=preset,
                )
            else:
                return EnhancementResult(
                    success=False,
                    original_path=audio_path,
                    preset=preset,
                    error=f"Preview generation failed: {stderr}",
                )

        except Exception as e:
            return EnhancementResult(
                success=False,
                original_path=audio_path,
                preset=preset,
                error=str(e),
            )

    @staticmethod
    def is_available() -> bool:
        """Check if audio enhancement is available."""
        return FFmpegEnhancer.is_available()

    @staticmethod
    def get_available_providers() -> list[str]:
        """Get list of available enhancement providers."""
        providers = []
        if FFmpegEnhancer.is_available():
            providers.append("ffmpeg")
        return providers
