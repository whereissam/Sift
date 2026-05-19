"""Real-time audio transcription with streaming support and LLM enhancement."""

import asyncio
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np

from .transcriber import AudioTranscriber, TranscriptionSegment

logger = logging.getLogger(__name__)


class AudioBuffer:
    """Circular buffer for streaming audio with sliding window support."""

    def __init__(self, max_duration: float = 30.0, sample_rate: int = 16000):
        """
        Initialize the audio buffer.

        Args:
            max_duration: Maximum duration in seconds to keep in buffer
            sample_rate: Audio sample rate (16kHz for Whisper)
        """
        self.sample_rate = sample_rate
        self.max_samples = int(max_duration * sample_rate)
        self.buffer = np.zeros(self.max_samples, dtype=np.float32)
        self.write_pos = 0
        self.total_samples_written = 0

    def append(self, audio: np.ndarray) -> None:
        """
        Append audio samples to the buffer.

        Uses circular buffer strategy - old samples are overwritten when full.

        Args:
            audio: Audio samples as float32 numpy array
        """
        audio = audio.astype(np.float32)
        n_samples = len(audio)

        if n_samples >= self.max_samples:
            # Audio is longer than buffer - keep only the last max_samples
            self.buffer[:] = audio[-self.max_samples:]
            self.write_pos = 0
            self.total_samples_written += n_samples
            return

        # Check if we need to wrap around
        end_pos = self.write_pos + n_samples
        if end_pos <= self.max_samples:
            # No wrap needed
            self.buffer[self.write_pos:end_pos] = audio
            self.write_pos = end_pos % self.max_samples
        else:
            # Wrap around
            first_part = self.max_samples - self.write_pos
            self.buffer[self.write_pos:] = audio[:first_part]
            self.buffer[:n_samples - first_part] = audio[first_part:]
            self.write_pos = n_samples - first_part

        self.total_samples_written += n_samples

    def get_audio(self, from_sample: int = 0) -> np.ndarray:
        """
        Get audio from a sample position to current write position.

        Args:
            from_sample: Starting sample position (absolute, since session start)

        Returns:
            Audio samples as numpy array
        """
        # Calculate how many samples are available
        available_start = max(0, self.total_samples_written - self.max_samples)

        if from_sample < available_start:
            # Requested start is before available data, adjust
            from_sample = available_start

        if from_sample >= self.total_samples_written:
            # No new samples available
            return np.array([], dtype=np.float32)

        # Calculate how many samples to return
        n_samples = self.total_samples_written - from_sample

        # Get the data from circular buffer
        if n_samples >= self.max_samples:
            # Return entire buffer in correct order
            if self.write_pos == 0:
                return self.buffer.copy()
            return np.concatenate([
                self.buffer[self.write_pos:],
                self.buffer[:self.write_pos]
            ])

        # Calculate start position in circular buffer
        buffer_start = (self.write_pos - (self.total_samples_written - from_sample)) % self.max_samples

        # Handle wrap-around
        if buffer_start + n_samples <= self.max_samples:
            return self.buffer[buffer_start:buffer_start + n_samples].copy()
        else:
            first_part = self.max_samples - buffer_start
            return np.concatenate([
                self.buffer[buffer_start:],
                self.buffer[:n_samples - first_part]
            ])

    def get_duration(self) -> float:
        """Get total duration of audio in buffer (seconds)."""
        return min(self.total_samples_written, self.max_samples) / self.sample_rate

    def get_total_duration(self) -> float:
        """Get total duration since session started (seconds)."""
        return self.total_samples_written / self.sample_rate

    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer.fill(0)
        self.write_pos = 0
        self.total_samples_written = 0


def convert_webm_to_pcm(webm_bytes: bytes, sample_rate: int = 16000) -> np.ndarray:
    """
    Convert WebM/Opus audio to PCM float32 using FFmpeg.

    Args:
        webm_bytes: Raw WebM/Opus audio data
        sample_rate: Target sample rate

    Returns:
        Audio as float32 numpy array
    """
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(webm_bytes)
        temp_path = f.name

    try:
        # Use FFmpeg to convert to raw PCM
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", temp_path,
                "-f", "f32le",  # 32-bit float little-endian
                "-acodec", "pcm_f32le",
                "-ac", "1",  # mono
                "-ar", str(sample_rate),
                "-loglevel", "error",
                "pipe:1"
            ],
            capture_output=True,
            check=True
        )
        audio = np.frombuffer(result.stdout, dtype=np.float32)
        return audio
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion error: {e.stderr.decode()}")
        return np.array([], dtype=np.float32)
    finally:
        Path(temp_path).unlink(missing_ok=True)


class WebmAccumulator:
    """Accumulates WebM/Opus chunks from MediaRecorder for full-stream decoding.

    MediaRecorder.start(interval) produces chunks where only the first contains
    the WebM/EBML header and codec initialization data. Subsequent chunks contain
    only Cluster data and are not valid standalone WebM files. This class
    accumulates all chunks and decodes the full concatenated stream.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._data = bytearray()
        self._decoded_samples = 0

    def add_chunk(self, chunk: bytes) -> None:
        """Add a WebM chunk from MediaRecorder."""
        self._data.extend(chunk)

    def decode_new(self) -> np.ndarray:
        """Decode full accumulated stream, return only new (previously unreturned) samples."""
        if not self._data:
            return np.array([], dtype=np.float32)

        all_audio = convert_webm_to_pcm(bytes(self._data), self.sample_rate)
        if len(all_audio) <= self._decoded_samples:
            return np.array([], dtype=np.float32)

        new = all_audio[self._decoded_samples:]
        self._decoded_samples = len(all_audio)
        return new

    def clear(self) -> None:
        """Clear accumulated data."""
        self._data.clear()
        self._decoded_samples = 0


@dataclass
class ProcessedSegment:
    """A processed and deduplicated segment."""
    start: float
    end: float
    text: str
    confidence: float = 1.0
    is_final: bool = False


class SegmentMerger:
    """Handles intelligent merging and deduplication of transcription segments."""

    def __init__(self, similarity_threshold: float = 0.6):
        self.similarity_threshold = similarity_threshold
        self.finalized_segments: list[ProcessedSegment] = []
        self.pending_text = ""

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity ratio between two texts."""
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    def _find_overlap(self, new_text: str, existing_text: str) -> tuple[int, int]:
        """
        Find where new_text overlaps with end of existing_text.

        Returns:
            (overlap_start_in_existing, overlap_length)
        """
        if not existing_text or not new_text:
            return -1, 0

        # Try to find overlap by checking suffixes of existing against prefixes of new
        min_overlap = 3  # Minimum characters to consider as overlap
        max_check = min(len(existing_text), len(new_text), 100)

        for overlap_len in range(max_check, min_overlap - 1, -1):
            suffix = existing_text[-overlap_len:].lower()
            prefix = new_text[:overlap_len].lower()

            # Check for similar enough match
            similarity = self._text_similarity(suffix, prefix)
            if similarity > 0.8:
                return len(existing_text) - overlap_len, overlap_len

        return -1, 0

    def process_segments(
        self,
        new_segments: list[TranscriptionSegment],
        time_offset: float,
    ) -> tuple[list[ProcessedSegment], str]:
        """
        Process new segments, handling deduplication and merging.

        Args:
            new_segments: New segments from transcription
            time_offset: Time offset to add to segment times

        Returns:
            (new_finalized_segments, current_partial_text)
        """
        if not new_segments:
            return [], self.pending_text

        new_finalized = []
        combined_text = " ".join(seg.text.strip() for seg in new_segments)

        # Check for overlap with pending text
        if self.pending_text:
            overlap_start, overlap_len = self._find_overlap(combined_text, self.pending_text)
            if overlap_len > 0:
                # Remove overlapping portion from new text
                combined_text = combined_text[overlap_len:].strip()

        # Also check against last finalized segment
        if self.finalized_segments:
            last_final = self.finalized_segments[-1]
            overlap_start, overlap_len = self._find_overlap(combined_text, last_final.text)
            if overlap_len > 0:
                combined_text = combined_text[overlap_len:].strip()

        if not combined_text:
            return [], self.pending_text

        # Determine if we should finalize segments
        # Finalize if we have punctuation indicating sentence end
        sentence_endings = ('.', '!', '?', '。', '！', '？')

        # Find the last sentence ending
        last_end_idx = -1
        for i, char in enumerate(combined_text):
            if char in sentence_endings:
                last_end_idx = i

        if last_end_idx > 0:
            # Finalize up to the last sentence ending
            final_text = combined_text[:last_end_idx + 1].strip()
            remaining_text = combined_text[last_end_idx + 1:].strip()

            if final_text:
                # Create finalized segment
                if new_segments:
                    start_time = new_segments[0].start + time_offset
                    end_time = new_segments[-1].end + time_offset
                else:
                    start_time = time_offset
                    end_time = time_offset

                segment = ProcessedSegment(
                    start=start_time,
                    end=end_time,
                    text=final_text,
                    is_final=True,
                )
                self.finalized_segments.append(segment)
                new_finalized.append(segment)

            self.pending_text = remaining_text
        else:
            # No sentence ending, keep as pending
            self.pending_text = combined_text

        return new_finalized, self.pending_text

    def finalize_all(self) -> list[ProcessedSegment]:
        """Finalize any remaining pending text."""
        if self.pending_text:
            segment = ProcessedSegment(
                start=self.finalized_segments[-1].end if self.finalized_segments else 0,
                end=self.finalized_segments[-1].end + 0.5 if self.finalized_segments else 0.5,
                text=self.pending_text,
                is_final=True,
            )
            self.finalized_segments.append(segment)
            self.pending_text = ""
            return [segment]
        return []

    def get_recent_context(self, max_words: int = 50) -> str:
        """Get recent finalized text for context."""
        if not self.finalized_segments:
            return ""

        # Gather recent text
        words = []
        for seg in reversed(self.finalized_segments):
            seg_words = seg.text.split()
            words = seg_words + words
            if len(words) >= max_words:
                break

        return " ".join(words[-max_words:])


class TranscriptPolisher:
    """LLM-powered transcript cleanup and enhancement."""

    CLEANUP_PROMPT = """Clean up and polish this real-time transcription. Fix:
- Remove duplicate words or phrases
- Fix obvious transcription errors
- Add proper punctuation and capitalization
- Merge fragmented sentences
- Keep the original meaning intact

Do NOT add new content or summarize. Only clean up what's there.

Transcript:
{transcript}

Cleaned transcript:"""

    MERGE_PROMPT = """Merge these transcript segments into coherent text. The segments may have:
- Overlapping content at boundaries
- Repeated phrases
- Incomplete sentences

Merge them naturally while preserving all unique content.

Segments:
{segments}

Merged text:"""

    def __init__(self):
        self._provider = None

    def _get_provider(self):
        """Get LLM provider from settings."""
        if self._provider is None:
            try:
                from .summarizer import TranscriptSummarizer
                summarizer = TranscriptSummarizer.from_settings()
                self._provider = summarizer.provider
            except Exception as e:
                logger.warning(f"Could not get LLM provider: {e}")
        return self._provider

    def is_available(self) -> bool:
        """Check if LLM polishing is available."""
        provider = self._get_provider()
        return provider is not None and provider.is_available()

    async def polish_transcript(self, transcript: str) -> tuple[str, int]:
        """
        Polish a transcript using LLM.

        Args:
            transcript: Raw transcript text

        Returns:
            (polished_text, tokens_used)
        """
        provider = self._get_provider()
        if not provider:
            raise ValueError("No LLM provider available")

        prompt = self.CLEANUP_PROMPT.format(transcript=transcript)
        system_prompt = "You are a transcript editor. Clean up transcripts while preserving their original meaning."

        result, tokens = await provider.generate(prompt, system_prompt)
        return result.strip(), tokens

    async def merge_segments(self, segments: list[str]) -> tuple[str, int]:
        """
        Merge multiple transcript segments using LLM.

        Args:
            segments: List of transcript segments

        Returns:
            (merged_text, tokens_used)
        """
        provider = self._get_provider()
        if not provider:
            raise ValueError("No LLM provider available")

        segments_text = "\n---\n".join(segments)
        prompt = self.MERGE_PROMPT.format(segments=segments_text)
        system_prompt = "You are a transcript editor. Merge transcript segments naturally."

        result, tokens = await provider.generate(prompt, system_prompt)
        return result.strip(), tokens


class RealtimeTranscriptionSession:
    """Manages a single live transcription session with improved accuracy."""

    def __init__(
        self,
        model_size: str = "base",
        language: Optional[str] = None,
        min_chunk_duration: float = 3.0,  # Increased from 1.0 for better accuracy
        max_buffer_duration: float = 30.0,
        use_context_prompt: bool = True,
        enable_llm_polish: bool = False,
    ):
        """
        Initialize a realtime transcription session.

        Args:
            model_size: Whisper model size to use
            language: Language code (None for auto-detection)
            min_chunk_duration: Minimum seconds of audio before processing
            max_buffer_duration: Maximum seconds to keep in sliding buffer
            use_context_prompt: Use recent transcript as context for better continuity
            enable_llm_polish: Enable LLM post-processing for cleanup
        """
        self.transcriber = AudioTranscriber(model_size=model_size)
        self.buffer = AudioBuffer(max_duration=max_buffer_duration)
        self.language = language
        self.detected_language: Optional[str] = None
        self.min_chunk_samples = int(min_chunk_duration * 16000)
        self.use_context_prompt = use_context_prompt
        self.enable_llm_polish = enable_llm_polish

        # WebM chunk accumulation (individual chunks are not standalone files)
        self._webm_accumulator = WebmAccumulator()
        self._last_decode_time = 0.0

        # Segment handling
        self.segment_merger = SegmentMerger()
        self.processed_samples = 0

        # LLM polisher
        self.polisher = TranscriptPolisher() if enable_llm_polish else None

        # Session state
        self.is_active = True
        self._lock = asyncio.Lock()

        # Stats
        self.total_tokens_used = 0

    async def process_audio_chunk(self, webm_bytes: bytes) -> AsyncIterator[dict]:
        """
        Process incoming audio chunk and yield transcription updates.

        WebM chunks from MediaRecorder are accumulated and decoded as a full
        stream (individual chunks after the first lack headers). Blocking FFmpeg
        and Whisper calls are run in threads to avoid blocking the event loop.

        Args:
            webm_bytes: WebM/Opus audio chunk from browser

        Yields:
            Transcription updates (partial or segment)
        """
        if not self.is_active:
            return

        async with self._lock:
            # Accumulate the WebM chunk (individual chunks are not standalone)
            self._webm_accumulator.add_chunk(webm_bytes)

            # Only decode when enough time has passed (avoid excessive FFmpeg calls)
            now = time.monotonic()
            min_decode_interval = self.min_chunk_samples / 16000
            if self._last_decode_time > 0 and (now - self._last_decode_time) < min_decode_interval * 0.8:
                return

            # Decode new audio from accumulated stream (in thread — FFmpeg is blocking)
            new_audio = await asyncio.to_thread(self._webm_accumulator.decode_new)
            if len(new_audio) == 0:
                return

            self._last_decode_time = now

            # Append to buffer
            self.buffer.append(new_audio)

            # Check if we have enough unprocessed audio
            unprocessed_samples = self.buffer.total_samples_written - self.processed_samples
            if unprocessed_samples < self.min_chunk_samples:
                return

            # Get audio to transcribe with some lookback for context
            lookback_samples = int(1.0 * 16000)  # 1 second lookback
            start_sample = max(0, self.processed_samples - lookback_samples)
            audio_to_process = self.buffer.get_audio(start_sample)

            if len(audio_to_process) < self.min_chunk_samples:
                return

            # Build initial prompt from recent context
            initial_prompt = None
            if self.use_context_prompt:
                context = self.segment_merger.get_recent_context(max_words=30)
                if context:
                    initial_prompt = context

            # Run transcription in thread (Whisper inference is CPU-intensive)
            try:
                result = await asyncio.to_thread(
                    self.transcriber.transcribe_audio_array,
                    audio_to_process,
                    language=self.language or self.detected_language,
                    initial_prompt=initial_prompt,
                )

                if not result.success:
                    yield {"type": "error", "error": result.error, "recoverable": True}
                    return

                # Update detected language
                if result.language and not self.detected_language:
                    self.detected_language = result.language
                    yield {
                        "type": "language_detected",
                        "language": result.language,
                        "probability": result.language_probability,
                    }

                # Calculate time offset
                time_offset = start_sample / 16000

                if result.segments:
                    # Process segments through merger
                    new_final, partial = self.segment_merger.process_segments(
                        result.segments,
                        time_offset,
                    )

                    # Yield finalized segments
                    for seg in new_final:
                        yield {
                            "type": "segment",
                            "segment": {
                                "start": seg.start,
                                "end": seg.end,
                                "text": seg.text,
                            }
                        }

                    # Yield partial text
                    if partial:
                        yield {
                            "type": "partial",
                            "text": partial,
                        }

                # Update processed position
                # Keep overlap for context continuity
                overlap_samples = int(1.5 * 16000)  # 1.5 second overlap
                self.processed_samples = self.buffer.total_samples_written - overlap_samples

            except Exception as e:
                logger.exception(f"Transcription error: {e}")
                yield {"type": "error", "error": str(e), "recoverable": True}

    async def finalize(self) -> dict:
        """
        Process any remaining audio and return complete result.

        Returns:
            Complete transcription result with all segments
        """
        async with self._lock:
            self.is_active = False

            # Decode any remaining accumulated WebM data
            remaining_audio = await asyncio.to_thread(self._webm_accumulator.decode_new)
            if len(remaining_audio) > 0:
                self.buffer.append(remaining_audio)

            # Process any remaining unprocessed audio
            remaining_samples = self.buffer.total_samples_written - self.processed_samples
            if remaining_samples > 4800:  # At least 0.3 second
                audio_to_process = self.buffer.get_audio(self.processed_samples)
                if len(audio_to_process) > 0:
                    try:
                        context = self.segment_merger.get_recent_context(max_words=30)
                        result = await asyncio.to_thread(
                            self.transcriber.transcribe_audio_array,
                            audio_to_process,
                            language=self.language or self.detected_language,
                            initial_prompt=context if self.use_context_prompt else None,
                        )

                        if result.success and result.segments:
                            time_offset = self.processed_samples / 16000
                            self.segment_merger.process_segments(
                                result.segments,
                                time_offset,
                            )
                    except Exception as e:
                        logger.error(f"Error processing final audio: {e}")

            # Finalize any pending text
            self.segment_merger.finalize_all()

            # Build full text from segments
            segments = self.segment_merger.finalized_segments
            full_text = " ".join(seg.text for seg in segments)

            # Optional LLM polishing
            polished_text = None
            if self.enable_llm_polish and self.polisher and self.polisher.is_available():
                try:
                    polished_text, tokens = await self.polisher.polish_transcript(full_text)
                    self.total_tokens_used += tokens
                    logger.info(f"Polished transcript using {tokens} tokens")
                except Exception as e:
                    logger.error(f"LLM polish failed: {e}")

            return {
                "full_text": polished_text or full_text,
                "raw_text": full_text if polished_text else None,
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in segments
                ],
                "language": self.detected_language or self.language,
                "duration": self.buffer.get_total_duration(),
                "llm_polished": polished_text is not None,
                "tokens_used": self.total_tokens_used if self.total_tokens_used > 0 else None,
            }

    def cleanup(self) -> None:
        """Clean up session resources."""
        self.is_active = False
        self.buffer.clear()
        self._webm_accumulator.clear()
        self.segment_merger = SegmentMerger()
