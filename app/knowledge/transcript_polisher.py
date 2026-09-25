"""LLM-powered cleanup of a realtime transcript.

Lives in the knowledge layer because it needs an LLM provider. The realtime
session in `sift_core.transcribe` takes one of these by injection instead of
constructing it, which is what keeps the ingestion core free of any dependency
on the layers above it (see `tests/test_layering.py`).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
