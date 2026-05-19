"""Audio transcription using faster-whisper."""

import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    import numpy as np

from .checkpoint import CheckpointManager, TranscriptionCheckpoint

logger = logging.getLogger(__name__)

# Add faster-whisper to path if installed locally
FASTER_WHISPER_PATH = Path(__file__).parent.parent.parent / "faster-whisper"
if FASTER_WHISPER_PATH.exists():
    sys.path.insert(0, str(FASTER_WHISPER_PATH))


class WhisperModel(str, Enum):
    """Available Whisper model sizes."""

    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"
    LARGE_V3_TURBO = "turbo"
    DISTIL_LARGE_V3 = "distil-large-v3"


class TranscriptionFormat(str, Enum):
    """Output format for transcription."""

    TEXT = "text"  # Plain text
    SRT = "srt"  # SubRip subtitle
    VTT = "vtt"  # WebVTT subtitle
    JSON = "json"  # JSON with timestamps


@dataclass
class TranscriptionSegment:
    """A segment of transcribed text."""

    start: float
    end: float
    text: str
    speaker: Optional[str] = None


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    success: bool
    text: Optional[str] = None
    segments: Optional[list[TranscriptionSegment]] = None
    language: Optional[str] = None
    language_probability: Optional[float] = None
    duration: Optional[float] = None
    error: Optional[str] = None


class AudioTranscriber:
    """Transcribe audio files using faster-whisper."""

    _model = None
    _current_model_size = None

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
        checkpoint_dir: Optional[Path] = None,
        remote_service_url: Optional[str] = None,
    ):
        """
        Initialize the transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large-v3, turbo)
            device: Device to use (auto, cpu, cuda)
            compute_type: Compute type (auto, int8, float16, float32)
            checkpoint_dir: Directory for saving checkpoints
            remote_service_url: URL of remote whisper service (for GPU transcription)
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        self.remote_service_url = remote_service_url or self._get_remote_service_url()

    def _get_remote_service_url(self) -> Optional[str]:
        """Get remote whisper service URL from config."""
        try:
            from ..config import get_settings
            return get_settings().whisper_service_url
        except Exception:
            return None

    async def _transcribe_remote(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        task: str = "transcribe",
        vad_filter: bool = True,
        word_timestamps: bool = False,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe using remote whisper service."""
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.remote_service_url}/transcribe",
                    json={
                        "audio_path": str(audio_path),
                        "language": language,
                        "task": task,
                        "vad_filter": vad_filter,
                        "word_timestamps": word_timestamps,
                        "initial_prompt": initial_prompt,
                    },
                )
                response.raise_for_status()
                data = response.json()

                if not data.get("success"):
                    return TranscriptionResult(
                        success=False,
                        error=data.get("error", "Remote transcription failed"),
                    )

                segments = [
                    TranscriptionSegment(
                        start=s["start"],
                        end=s["end"],
                        text=s["text"],
                    )
                    for s in data.get("segments", [])
                ]

                return TranscriptionResult(
                    success=True,
                    text=data.get("text"),
                    segments=segments,
                    language=data.get("language"),
                    language_probability=data.get("language_probability"),
                    duration=data.get("duration"),
                )

        except httpx.HTTPError as e:
            logger.error(f"Remote transcription HTTP error: {e}")
            return TranscriptionResult(
                success=False,
                error=f"Remote transcription failed: {e}",
            )
        except Exception as e:
            logger.exception(f"Remote transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    def _get_model(self):
        """Get or create the Whisper model (lazy loading with singleton pattern)."""
        if (
            AudioTranscriber._model is None
            or AudioTranscriber._current_model_size != self.model_size
        ):
            try:
                from faster_whisper import WhisperModel as FasterWhisperModel

                logger.info(f"Loading Whisper model: {self.model_size}")

                # Determine device and compute type
                device = self.device
                compute_type = self.compute_type

                if device == "auto":
                    try:
                        import torch

                        device = "cuda" if torch.cuda.is_available() else "cpu"
                    except ImportError:
                        device = "cpu"

                if compute_type == "auto":
                    compute_type = "int8" if device == "cpu" else "float16"

                AudioTranscriber._model = FasterWhisperModel(
                    self.model_size,
                    device=device,
                    compute_type=compute_type,
                )
                AudioTranscriber._current_model_size = self.model_size
                logger.info(
                    f"Model loaded: {self.model_size} on {device} with {compute_type}"
                )

            except ImportError as e:
                raise ImportError(
                    "faster-whisper not installed. Install it with: pip install faster-whisper"
                ) from e

        return AudioTranscriber._model

    async def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
        task: str = "transcribe",
        vad_filter: bool = True,
        word_timestamps: bool = False,
        initial_prompt: Optional[str] = None,
        job_id: Optional[str] = None,
        output_format: str = "text",
        checkpoint_interval: int = 5,
        use_remote: Optional[bool] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file with checkpoint support.

        Args:
            audio_path: Path to the audio file
            language: Language code (auto-detect if None)
            task: "transcribe" or "translate" (to English)
            vad_filter: Use VAD to filter silence
            word_timestamps: Include word-level timestamps
            initial_prompt: Optional prompt to guide transcription
            job_id: Job ID for checkpoint tracking
            output_format: Output format (text, srt, vtt, json)
            use_remote: Force use of remote service (None=auto, True=force, False=local)
            checkpoint_interval: Save checkpoint every N segments

        Returns:
            TranscriptionResult with text and segments
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            return TranscriptionResult(
                success=False,
                error=f"Audio file not found: {audio_path}",
            )

        # Use remote service if available and not explicitly disabled
        should_use_remote = (
            use_remote is True or
            (use_remote is None and self.remote_service_url)
        )

        if should_use_remote and self.remote_service_url:
            logger.info(f"Using remote whisper service at {self.remote_service_url}")
            return await self._transcribe_remote(
                audio_path=audio_path,
                language=language,
                task=task,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt,
            )

        # Check for existing checkpoint to resume
        checkpoint = None
        resume_from = 0.0
        existing_segments = []

        if job_id:
            checkpoint = self.checkpoint_manager.load(job_id)
            if checkpoint:
                resume_from = checkpoint.last_end_time
                existing_segments = [
                    TranscriptionSegment(
                        start=s["start"],
                        end=s["end"],
                        text=s["text"],
                    )
                    for s in checkpoint.segments
                ]
                logger.info(
                    f"Resuming job {job_id} from {resume_from:.2f}s "
                    f"({len(existing_segments)} segments already done)"
                )

        try:
            model = self._get_model()

            logger.info(f"Transcribing: {audio_path.name}")

            # Get audio duration first for progress tracking
            from faster_whisper.audio import decode_audio
            audio_array = decode_audio(str(audio_path))
            total_duration = len(audio_array) / 16000  # 16kHz sample rate

            # Run transcription
            segments_generator, info = model.transcribe(
                str(audio_path),
                language=language,
                task=task,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt,
                beam_size=5,
            )

            # Collect segments with checkpoint saving
            segments = list(existing_segments)
            full_text_parts = [s.text for s in existing_segments]

            # Create or update checkpoint
            if job_id:
                checkpoint = TranscriptionCheckpoint(
                    job_id=job_id,
                    audio_path=str(audio_path),
                    model_size=self.model_size,
                    language=language,
                    task=task,
                    output_format=output_format,
                    last_end_time=resume_from,
                    segments=[{"start": s.start, "end": s.end, "text": s.text} for s in existing_segments],
                    detected_language=info.language,
                    language_probability=info.language_probability,
                    total_duration=total_duration,
                )

            segment_count = len(existing_segments)
            for segment in segments_generator:
                # Skip segments we've already processed (resume support)
                if segment.end <= resume_from:
                    continue

                segments.append(
                    TranscriptionSegment(
                        start=segment.start,
                        end=segment.end,
                        text=segment.text.strip(),
                    )
                )
                full_text_parts.append(segment.text.strip())
                segment_count += 1

                # Save checkpoint periodically
                if job_id and segment_count % checkpoint_interval == 0:
                    checkpoint.last_end_time = segment.end
                    checkpoint.segments.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text.strip(),
                    })
                    self.checkpoint_manager.save(checkpoint)

            full_text = " ".join(full_text_parts)

            # Delete checkpoint on successful completion
            if job_id:
                self.checkpoint_manager.delete(job_id)

            logger.info(
                f"Transcription complete: {len(segments)} segments, "
                f"language={info.language} ({info.language_probability:.2%})"
            )

            return TranscriptionResult(
                success=True,
                text=full_text,
                segments=segments,
                language=info.language,
                language_probability=info.language_probability,
                duration=info.duration,
            )

        except Exception as e:
            # Save checkpoint on error so we can resume
            if job_id and checkpoint:
                self.checkpoint_manager.save(checkpoint)
                logger.info(f"Saved checkpoint for job {job_id} after error")

            logger.exception(f"Transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    def get_resumable_jobs(self) -> list[dict]:
        """Get list of jobs that can be resumed."""
        return self.checkpoint_manager.get_resumable_jobs()

    def can_resume(self, job_id: str) -> bool:
        """Check if a job can be resumed."""
        return self.checkpoint_manager.exists(job_id)

    @staticmethod
    def format_as_srt(segments: list[TranscriptionSegment]) -> str:
        """Format segments as SRT subtitle."""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = _format_timestamp_srt(seg.start)
            end = _format_timestamp_srt(seg.end)
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def format_as_vtt(segments: list[TranscriptionSegment]) -> str:
        """Format segments as WebVTT subtitle."""
        lines = ["WEBVTT", ""]
        for seg in segments:
            start = _format_timestamp_vtt(seg.start)
            end = _format_timestamp_vtt(seg.end)
            lines.append(f"{start} --> {end}")
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    def transcribe_audio_array(
        self,
        audio: "np.ndarray",
        sample_rate: int = 16000,
        language: Optional[str] = None,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio from numpy array directly.

        This method is optimized for real-time streaming transcription,
        accepting audio data directly without needing a file.

        Args:
            audio: Audio samples as numpy array (float32, mono)
            sample_rate: Sample rate of the audio (default 16000 for Whisper)
            language: Language code (auto-detect if None)
            vad_filter: Use VAD to filter silence
            initial_prompt: Optional prompt to provide context (e.g., recent transcript)

        Returns:
            TranscriptionResult with text and segments
        """
        import numpy as np

        if len(audio) == 0:
            return TranscriptionResult(
                success=True,
                text="",
                segments=[],
            )

        try:
            model = self._get_model()

            # Ensure audio is float32
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # Resample if needed (Whisper expects 16kHz)
            if sample_rate != 16000:
                try:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
                except ImportError:
                    logger.warning("librosa not available, assuming 16kHz sample rate")

            # Run transcription on array
            segments_generator, info = model.transcribe(
                audio,
                language=language,
                vad_filter=vad_filter,
                beam_size=5,
                initial_prompt=initial_prompt,
            )

            # Collect segments
            segments = []
            full_text_parts = []

            for segment in segments_generator:
                segments.append(
                    TranscriptionSegment(
                        start=segment.start,
                        end=segment.end,
                        text=segment.text.strip(),
                    )
                )
                full_text_parts.append(segment.text.strip())

            full_text = " ".join(full_text_parts)

            return TranscriptionResult(
                success=True,
                text=full_text,
                segments=segments,
                language=info.language,
                language_probability=info.language_probability,
                duration=len(audio) / 16000,
            )

        except Exception as e:
            logger.exception(f"Array transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    @staticmethod
    def is_available() -> bool:
        """Check if faster-whisper is available."""
        from importlib.util import find_spec

        return find_spec("faster_whisper") is not None

    @staticmethod
    def format_as_dialogue(segments: list[TranscriptionSegment]) -> str:
        """
        Format as dialogue with speaker labels.

        Example output:
            SPEAKER_00: Hello everyone.
            SPEAKER_01: Hi, thanks for having me.
        """
        lines = []
        current_speaker = None
        current_text = []

        for seg in segments:
            speaker = seg.speaker or "SPEAKER_UNKNOWN"
            if speaker != current_speaker:
                # Flush previous speaker's text
                if current_speaker is not None and current_text:
                    lines.append(f"{current_speaker}: {' '.join(current_text)}")
                current_speaker = speaker
                current_text = [seg.text.strip()]
            else:
                current_text.append(seg.text.strip())

        # Flush final speaker
        if current_speaker is not None and current_text:
            lines.append(f"{current_speaker}: {' '.join(current_text)}")

        return "\n".join(lines)

    @staticmethod
    def format_as_srt_with_speakers(segments: list[TranscriptionSegment]) -> str:
        """
        Format as SRT with speaker prefixes.

        Example output:
            1
            00:00:01,000 --> 00:00:03,500
            [SPEAKER_00] Hello everyone.
        """
        lines = []
        for i, seg in enumerate(segments, 1):
            start = _format_timestamp_srt(seg.start)
            end = _format_timestamp_srt(seg.end)
            speaker = seg.speaker or "SPEAKER_UNKNOWN"
            lines.append(str(i))
            lines.append(f"{start} --> {end}")
            lines.append(f"[{speaker}] {seg.text}")
            lines.append("")
        return "\n".join(lines)


def _format_timestamp_srt(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Format seconds as VTT timestamp (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


# Convenience function
async def transcribe_audio(
    audio_path: str | Path,
    model_size: str = "base",
    language: Optional[str] = None,
    job_id: Optional[str] = None,
) -> TranscriptionResult:
    """
    Transcribe an audio file with optional checkpoint support.

    Args:
        audio_path: Path to audio file
        model_size: Whisper model size
        language: Language code (auto-detect if None)
        job_id: Job ID for checkpoint tracking (enables resume on failure)

    Returns:
        TranscriptionResult
    """
    transcriber = AudioTranscriber(model_size=model_size)
    return await transcriber.transcribe(audio_path, language=language, job_id=job_id)
