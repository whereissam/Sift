"""Speaker diarization using pyannote-audio."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SpeakerSegment:
    """A segment attributed to a speaker."""

    speaker: str  # e.g., "SPEAKER_00"
    start: float
    end: float


@dataclass
class DiarizedSegment:
    """A transcription segment with speaker label."""

    speaker: str
    start: float
    end: float
    text: str


class SpeakerDiarizer:
    """Speaker diarization using pyannote-audio."""

    _pipeline = None  # Singleton pattern like transcriber

    def __init__(self, hf_token: Optional[str] = None):
        """
        Initialize with HuggingFace token.

        Args:
            hf_token: HuggingFace token for pyannote model access.
                     Get one at https://huggingface.co/settings/tokens
                     Accept conditions at https://huggingface.co/pyannote/speaker-diarization-3.1
        """
        self.hf_token = hf_token

    def _get_pipeline(self):
        """Lazy-load the diarization pipeline."""
        if SpeakerDiarizer._pipeline is None:
            try:
                from pyannote.audio import Pipeline
                import torch

                logger.info("Loading pyannote diarization pipeline...")

                # Use HF token from config if not provided
                token = self.hf_token
                if not token:
                    from ..config import get_settings
                    settings = get_settings()
                    token = settings.huggingface_token

                # If still no token, try to use cached token from `huggingface-cli login`
                if not token:
                    try:
                        from huggingface_hub import get_token
                        token = get_token()
                    except Exception:
                        pass

                if not token:
                    raise ValueError(
                        "HuggingFace token required for pyannote. "
                        "Either set HUGGINGFACE_TOKEN in .env, or run: huggingface-cli login"
                    )

                SpeakerDiarizer._pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=token,
                )

                # Move to GPU if available
                if torch.cuda.is_available():
                    SpeakerDiarizer._pipeline = SpeakerDiarizer._pipeline.to(
                        torch.device("cuda")
                    )
                    logger.info("Diarization pipeline loaded on GPU")
                else:
                    logger.info("Diarization pipeline loaded on CPU")

            except ImportError as e:
                raise ImportError(
                    "pyannote.audio not installed. Install with: uv sync --extra diarize"
                ) from e

        return SpeakerDiarizer._pipeline

    async def diarize(
        self,
        audio_path: Path,
        num_speakers: Optional[int] = None,
        min_speakers: int = 1,
        max_speakers: int = 10,
    ) -> list[SpeakerSegment]:
        """
        Run speaker diarization on audio file.

        Args:
            audio_path: Path to the audio file
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum number of speakers (default: 1)
            max_speakers: Maximum number of speakers (default: 10)

        Returns:
            List of SpeakerSegment with speaker labels and timestamps
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        pipeline = self._get_pipeline()

        logger.info(f"Running diarization on: {audio_path.name}")

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()

        def _run_diarization():
            import torchaudio

            # Load audio as waveform (workaround for torchcodec issues)
            waveform, sample_rate = torchaudio.load(str(audio_path))

            # Resample to 16kHz if needed
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(sample_rate, 16000)
                waveform = resampler(waveform)
                sample_rate = 16000

            # Create audio dict for pyannote
            audio_input = {"waveform": waveform, "sample_rate": sample_rate}

            if num_speakers:
                diarization = pipeline(audio_input, num_speakers=num_speakers)
            else:
                diarization = pipeline(
                    audio_input,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
            return diarization

        diarization = await loop.run_in_executor(None, _run_diarization)

        # Convert to SpeakerSegment list
        # Handle both old and new pyannote output formats
        segments = []
        if hasattr(diarization, 'speaker_diarization'):
            # New format (pyannote 3.x)
            annotation = diarization.speaker_diarization
        else:
            # Old format
            annotation = diarization

        for turn, _, speaker in annotation.itertracks(yield_label=True):
            segments.append(
                SpeakerSegment(
                    speaker=speaker,
                    start=turn.start,
                    end=turn.end,
                )
            )

        logger.info(f"Diarization complete: {len(segments)} speaker turns found")
        return segments

    def assign_speakers_to_segments(
        self,
        transcription_segments: list,
        speaker_segments: list[SpeakerSegment],
    ) -> list[DiarizedSegment]:
        """
        Merge transcription with speaker labels.

        For each transcription segment, find the speaker with the most overlap.

        Args:
            transcription_segments: List of TranscriptionSegment from whisper
            speaker_segments: List of SpeakerSegment from diarization

        Returns:
            List of DiarizedSegment with speaker labels
        """
        diarized = []

        for trans_seg in transcription_segments:
            # Find speaker with most overlap
            best_speaker = "SPEAKER_UNKNOWN"
            best_overlap = 0.0

            for spk_seg in speaker_segments:
                # Calculate overlap between transcription and speaker segment
                overlap_start = max(trans_seg.start, spk_seg.start)
                overlap_end = min(trans_seg.end, spk_seg.end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = spk_seg.speaker

            diarized.append(
                DiarizedSegment(
                    speaker=best_speaker,
                    start=trans_seg.start,
                    end=trans_seg.end,
                    text=trans_seg.text,
                )
            )

        return diarized

    @staticmethod
    def is_available() -> bool:
        """Check if pyannote is available."""
        from importlib.util import find_spec

        return find_spec("pyannote.audio") is not None

    @staticmethod
    def format_as_dialogue(segments: list[DiarizedSegment]) -> str:
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
            if seg.speaker != current_speaker:
                # Flush previous speaker's text
                if current_speaker is not None and current_text:
                    lines.append(f"{current_speaker}: {' '.join(current_text)}")
                current_speaker = seg.speaker
                current_text = [seg.text.strip()]
            else:
                current_text.append(seg.text.strip())

        # Flush final speaker
        if current_speaker is not None and current_text:
            lines.append(f"{current_speaker}: {' '.join(current_text)}")

        return "\n".join(lines)

    @staticmethod
    def format_as_srt_with_speakers(segments: list[DiarizedSegment]) -> str:
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
            lines.append(str(i))
            lines.append(f"{start} --> {end}")
            lines.append(f"[{seg.speaker}] {seg.text}")
            lines.append("")
        return "\n".join(lines)


def _format_timestamp_srt(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
