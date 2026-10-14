"""LLM-powered summarization service for transcripts using LiteLLM."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from litellm import acompletion

logger = logging.getLogger(__name__)


class SummaryType(str, Enum):
    """Types of summaries that can be generated."""
    BULLET_POINTS = "bullet_points"
    CHAPTERS = "chapters"
    KEY_TOPICS = "key_topics"
    ACTION_ITEMS = "action_items"
    FULL = "full"  # Comprehensive summary with all elements


@dataclass
class SummaryResult:
    """Result of a summarization operation."""
    summary_type: SummaryType
    content: str
    model: str
    provider: str
    tokens_used: Optional[int] = None


# Sent instead of letting LiteLLM pick an env key for a caller-chosen base_url.
NO_API_KEY = "sk-no-key"

class LiteLLMProvider:
    """Unified LLM provider using LiteLLM for multiple backends.

    LiteLLM model format examples:
      - ollama/llama3.2 - Local Ollama
      - gpt-4o-mini - OpenAI
      - claude-3-haiku-20240307 - Anthropic
      - groq/llama-3.1-70b-versatile - Groq
      - deepseek/deepseek-chat - DeepSeek
      - openai/custom-model with custom base_url - OpenAI-compatible
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: str = "litellm",
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._provider = provider
        self._available: Optional[bool] = None

    async def generate(self, prompt: str, system_prompt: str = "") -> tuple[str, int]:
        """Generate a response from the LLM using LiteLLM.

        Returns:
            Tuple of (response_text, tokens_used)
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        elif self.base_url and not self.model.startswith("ollama/"):
            # With no key, LiteLLM falls back to the provider's env key
            # (OPENAI_API_KEY, ...) and would send it to this base_url,
            # which can come from an API caller. Keyless local servers
            # ignore the placeholder.
            kwargs["api_key"] = NO_API_KEY
        if self.base_url:
            kwargs["base_url"] = self.base_url

        response = await acompletion(**kwargs)
        content = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0
        return content, tokens

    def is_available(self) -> bool:
        """Check if this provider is available."""
        if self._available is not None:
            return self._available

        # For Ollama, check connectivity
        if self.model.startswith("ollama/"):
            try:
                import httpx
                base_url = self.base_url or "http://localhost:11434"
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"{base_url.rstrip('/')}/api/tags")
                    self._available = response.status_code == 200
            except Exception:
                self._available = False
        else:
            # For cloud providers, just check if API key is set (if required)
            self._available = True

        return self._available

    @property
    def name(self) -> str:
        """Provider name."""
        return self._provider

    @property
    def model_name(self) -> str:
        """Model name being used."""
        return self.model


# Summarization prompts
SYSTEM_PROMPT = """You are an expert at analyzing and summarizing transcripts.
You provide clear, accurate, and well-structured summaries.
Always maintain the original meaning and key points.
Format your responses using markdown for better readability."""

PROMPTS = {
    SummaryType.BULLET_POINTS: """Summarize the following transcript into clear, concise bullet points.
Focus on the main ideas, key arguments, and important details.
Use nested bullets for supporting points.
Aim for 5-15 bullet points depending on content length.

Transcript:
{transcript}

Provide the bullet-point summary:""",

    SummaryType.CHAPTERS: """Analyze this transcript and create chapter markers with timestamps.
Each chapter should have:
- A timestamp (use the format [HH:MM:SS] or [MM:SS])
- A descriptive title
- A brief 1-2 sentence description

Identify natural topic transitions and segment the content accordingly.

Transcript:
{transcript}

Provide the chapters:""",

    SummaryType.KEY_TOPICS: """Extract the key topics and themes from this transcript.
For each topic:
- Provide a clear topic name
- Explain why it's significant
- Note how much of the discussion it covers (major/minor topic)

Group related topics together.

Transcript:
{transcript}

Provide the key topics:""",

    SummaryType.ACTION_ITEMS: """Extract all action items, tasks, commitments, and follow-ups from this transcript.
For each action item:
- What needs to be done
- Who is responsible (if mentioned)
- Any deadlines or timeframes mentioned
- Priority level (high/medium/low) based on context

If this is not a meeting-style transcript, note that and provide any implicit recommendations or suggested actions.

Transcript:
{transcript}

Provide the action items:""",

    SummaryType.FULL: """Provide a comprehensive summary of this transcript including:

## Overview
A 2-3 sentence executive summary of the entire content.

## Key Points
The main ideas and arguments presented (as bullet points).

## Topics Discussed
Major themes and subjects covered.

## Notable Quotes
2-3 significant or memorable quotes from the transcript.

## Conclusion
How the content wraps up and any final takeaways.

Transcript:
{transcript}

Provide the comprehensive summary:""",
}


class TranscriptSummarizer:
    """Service for summarizing transcripts using LLMs."""

    # Approximate token limits for chunking (conservative estimates)
    CHUNK_SIZE = 6000  # ~6000 words per chunk
    OVERLAP = 500  # Overlap between chunks for context

    def __init__(self, provider: Optional[LiteLLMProvider] = None):
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "TranscriptSummarizer":
        """Create summarizer from application settings or database config."""
        from ..config import get_settings
        from ..store import get_job_store
        settings = get_settings()

        provider: Optional[LiteLLMProvider] = None

        # Try to get settings from database first
        try:
            job_store = get_job_store()
            ai_settings = job_store.get_ai_settings()
            if ai_settings:
                model = cls._build_litellm_model(
                    ai_settings["provider"],
                    ai_settings["model"]
                )
                provider = LiteLLMProvider(
                    model=model,
                    api_key=ai_settings.get("api_key"),
                    base_url=ai_settings.get("base_url"),
                    provider=ai_settings["provider"],
                )
                return cls(provider=provider)
        except Exception as e:
            logger.debug(f"Could not load AI settings from database: {e}")

        # Fall back to environment settings
        if settings.llm_provider == "ollama":
            model = f"ollama/{settings.ollama_model}"
            provider = LiteLLMProvider(
                model=model,
                base_url=settings.ollama_base_url,
                provider="ollama",
            )
        elif settings.llm_provider == "openai" and settings.openai_api_key:
            provider = LiteLLMProvider(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                provider="openai",
            )
        elif settings.llm_provider == "openai_compatible" and settings.openai_api_key:
            model = f"openai/{settings.openai_model}"
            provider = LiteLLMProvider(
                model=model,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                provider="custom",
            )
        elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            provider = LiteLLMProvider(
                model=settings.anthropic_model,
                api_key=settings.anthropic_api_key,
                provider="anthropic",
            )
        elif settings.llm_provider == "groq" and settings.groq_api_key:
            model = f"groq/{settings.groq_model}"
            provider = LiteLLMProvider(
                model=model,
                api_key=settings.groq_api_key,
                provider="groq",
            )
        elif settings.llm_provider == "deepseek" and settings.deepseek_api_key:
            model = f"deepseek/{settings.deepseek_model}"
            provider = LiteLLMProvider(
                model=model,
                api_key=settings.deepseek_api_key,
                provider="deepseek",
            )
        elif settings.llm_provider == "gemini" and settings.gemini_api_key:
            model = f"gemini/{settings.gemini_model}"
            provider = LiteLLMProvider(
                model=model,
                api_key=settings.gemini_api_key,
                provider="gemini",
            )

        return cls(provider=provider)

    @staticmethod
    def _build_litellm_model(provider: str, model: str) -> str:
        """Build the LiteLLM model string from provider and model name."""
        if provider == "ollama":
            return f"ollama/{model}"
        elif provider == "groq":
            return f"groq/{model}"
        elif provider == "deepseek":
            return f"deepseek/{model}"
        elif provider == "gemini":
            return f"gemini/{model}"
        elif provider == "custom":
            return f"openai/{model}"
        else:
            # OpenAI and Anthropic models don't need prefix
            return model

    @staticmethod
    def is_available() -> bool:
        """Check if any summarization provider is available."""
        from ..config import get_settings
        from ..store import get_job_store
        settings = get_settings()

        # Check database settings first
        try:
            job_store = get_job_store()
            ai_settings = job_store.get_ai_settings()
            if ai_settings:
                provider = ai_settings["provider"]
                if provider == "ollama":
                    import httpx
                    base_url = ai_settings.get("base_url") or "http://localhost:11434"
                    with httpx.Client(timeout=5.0) as client:
                        response = client.get(f"{base_url.rstrip('/')}/api/tags")
                        if response.status_code == 200:
                            return True
                else:
                    # Cloud providers with API key
                    return bool(ai_settings.get("api_key"))
        except Exception:
            pass

        # Fall back to environment settings
        if settings.llm_provider == "ollama":
            try:
                import httpx
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"{settings.ollama_base_url}/api/tags")
                    if response.status_code == 200:
                        return True
            except Exception:
                pass

        # Check OpenAI
        if settings.llm_provider in ("openai", "openai_compatible") and settings.openai_api_key:
            return True

        # Check Anthropic
        if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            return True

        # Check Groq
        if settings.llm_provider == "groq" and settings.groq_api_key:
            return True

        # Check DeepSeek
        if settings.llm_provider == "deepseek" and settings.deepseek_api_key:
            return True

        # Check Gemini
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            return True

        return False

    def _chunk_transcript(self, transcript: str) -> list[str]:
        """Split transcript into chunks for processing."""
        words = transcript.split()
        if len(words) <= self.CHUNK_SIZE:
            return [transcript]

        chunks = []
        start = 0
        while start < len(words):
            end = start + self.CHUNK_SIZE
            chunk_words = words[start:end]
            chunks.append(" ".join(chunk_words))
            start = end - self.OVERLAP  # Overlap for context

        return chunks

    async def summarize(
        self,
        transcript: str,
        summary_type: SummaryType = SummaryType.BULLET_POINTS,
    ) -> SummaryResult:
        """Summarize a transcript.

        Args:
            transcript: The transcript text to summarize
            summary_type: Type of summary to generate

        Returns:
            SummaryResult with the generated summary
        """
        if not self.provider:
            raise ValueError("No LLM provider configured")

        if not self.provider.is_available():
            raise ValueError(f"LLM provider {self.provider.name} is not available")

        chunks = self._chunk_transcript(transcript)
        logger.info(f"Summarizing transcript in {len(chunks)} chunk(s)")

        if len(chunks) == 1:
            # Single chunk - direct summarization
            prompt = PROMPTS[summary_type].format(transcript=transcript)
            content, tokens = await self.provider.generate(prompt, SYSTEM_PROMPT)
        else:
            # Multiple chunks - summarize each then combine
            chunk_summaries = []
            total_tokens = 0

            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i + 1}/{len(chunks)}")
                prompt = PROMPTS[summary_type].format(transcript=chunk)
                summary, tokens = await self.provider.generate(prompt, SYSTEM_PROMPT)
                chunk_summaries.append(summary)
                total_tokens += tokens

            # Combine chunk summaries
            combined = "\n\n---\n\n".join(chunk_summaries)
            combine_prompt = f"""The following are summaries of different parts of a longer transcript.
Please combine them into a single coherent {summary_type.value.replace('_', ' ')} summary,
removing any redundancy while preserving all unique information.

Part summaries:
{combined}

Provide the combined summary:"""

            content, final_tokens = await self.provider.generate(combine_prompt, SYSTEM_PROMPT)
            tokens = total_tokens + final_tokens

        return SummaryResult(
            summary_type=summary_type,
            content=content,
            model=self.provider.model_name,
            provider=self.provider.name,
            tokens_used=tokens,
        )

    async def summarize_all(self, transcript: str) -> dict[SummaryType, SummaryResult]:
        """Generate all types of summaries for a transcript.

        Returns:
            Dictionary mapping summary types to their results
        """
        results = {}
        for summary_type in SummaryType:
            if summary_type != SummaryType.FULL:  # Skip full to avoid redundancy
                results[summary_type] = await self.summarize(transcript, summary_type)
        return results
