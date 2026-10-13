"""AI-powered viral clip generator for social media using LiteLLM."""

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from litellm import acompletion

logger = logging.getLogger(__name__)


class SocialPlatform(str, Enum):
    """Supported social media platforms with their constraints."""

    TIKTOK = "tiktok"  # 9:16, max 180s
    INSTAGRAM_REELS = "reels"  # 9:16, max 90s
    YOUTUBE_SHORTS = "shorts"  # 9:16, max 60s
    TWITTER_X = "twitter"  # 16:9, max 140s


# Platform duration limits in seconds
PLATFORM_MAX_DURATION = {
    SocialPlatform.TIKTOK: 180,
    SocialPlatform.INSTAGRAM_REELS: 90,
    SocialPlatform.YOUTUBE_SHORTS: 60,
    SocialPlatform.TWITTER_X: 140,
}


@dataclass
class ClipSuggestion:
    """A suggested viral clip with metadata."""

    clip_id: str
    start_time: float
    end_time: float
    duration: float
    transcript_text: str
    hook: str  # Opening hook for engagement
    caption: str  # Social media caption
    hashtags: list[str]
    viral_score: float  # 0.0-1.0 confidence score
    engagement_factors: dict[str, float]  # humor, controversy, emotion, etc.
    compatible_platforms: list[SocialPlatform]
    exported_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "clip_id": self.clip_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "transcript_text": self.transcript_text,
            "hook": self.hook,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "viral_score": self.viral_score,
            "engagement_factors": self.engagement_factors,
            "compatible_platforms": [p.value for p in self.compatible_platforms],
            "exported_files": self.exported_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClipSuggestion":
        """Create from dictionary."""
        return cls(
            clip_id=data["clip_id"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            duration=data["duration"],
            transcript_text=data["transcript_text"],
            hook=data["hook"],
            caption=data["caption"],
            hashtags=data["hashtags"],
            viral_score=data["viral_score"],
            engagement_factors=data["engagement_factors"],
            compatible_platforms=[
                SocialPlatform(p) for p in data["compatible_platforms"]
            ],
            exported_files=data.get("exported_files", {}),
        )


@dataclass
class ClipGenerationResult:
    """Result of clip generation."""

    success: bool
    job_id: str
    clips: list[ClipSuggestion]
    model: str
    provider: str
    tokens_used: Optional[int] = None
    error: Optional[str] = None


# Sent instead of letting LiteLLM pick an env key for a caller-chosen base_url.
NO_API_KEY = "sk-no-key"

class LiteLLMProvider:
    """Unified LLM provider using LiteLLM for multiple backends."""

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


# System prompt for viral content identification
SYSTEM_PROMPT = """You are an expert social media content strategist specializing in identifying viral-worthy content from transcripts.

You analyze transcripts to find the most engaging, shareable segments that would perform well on platforms like TikTok, Instagram Reels, YouTube Shorts, and Twitter/X.

You understand:
- What makes content go viral (hooks, emotional triggers, controversy, humor, value)
- Platform-specific best practices and duration limits
- How to craft engaging captions and hashtags
- The importance of strong opening hooks

Always return your analysis in valid JSON format."""

CLIP_GENERATION_PROMPT = """Analyze the following transcript and identify up to {max_clips} viral-worthy segments for social media.

For each segment, provide:
1. Precise start and end timestamps (in seconds)
2. The transcript text for that segment
3. A compelling opening hook (the first words that grab attention)
4. An engaging social media caption
5. Relevant hashtags (5-10)
6. A viral score (0.0-1.0) based on engagement potential
7. Engagement factors breakdown (scores 0.0-1.0 for: humor, emotion, controversy, value, relatability)
8. Which platforms it's suitable for based on duration:
   - TikTok: max 180 seconds
   - Instagram Reels: max 90 seconds
   - YouTube Shorts: max 60 seconds
   - Twitter/X: max 140 seconds

Target clip duration: {target_duration} seconds (if specified, otherwise find natural breakpoints)
Minimum viral score threshold: {min_viral_score}
Focus on platforms: {platforms}

TRANSCRIPT WITH TIMESTAMPS:
{transcript}

Return ONLY a valid JSON array with this structure (no markdown, no code blocks):
[
  {{
    "start_time": 45.5,
    "end_time": 72.3,
    "transcript_text": "The actual transcript text for this segment...",
    "hook": "You won't believe what happened...",
    "caption": "This changed everything for me 🔥 Watch till the end!",
    "hashtags": ["viral", "mindblown", "mustwatch"],
    "viral_score": 0.85,
    "engagement_factors": {{
      "humor": 0.3,
      "emotion": 0.8,
      "controversy": 0.2,
      "value": 0.9,
      "relatability": 0.7
    }},
    "compatible_platforms": ["tiktok", "reels", "shorts", "twitter"]
  }}
]"""


class ClipGenerator:
    """Service for generating viral clip suggestions from transcripts."""

    def __init__(self, provider: Optional[LiteLLMProvider] = None):
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "ClipGenerator":
        """Create clip generator from application settings or database config."""
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
                    ai_settings["provider"], ai_settings["model"]
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
        """Check if any AI provider is available for clip generation."""
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

        if settings.llm_provider in ("openai", "openai_compatible"):
            return bool(settings.openai_api_key)
        if settings.llm_provider == "anthropic":
            return bool(settings.anthropic_api_key)
        if settings.llm_provider == "groq":
            return bool(settings.groq_api_key)
        if settings.llm_provider == "deepseek":
            return bool(settings.deepseek_api_key)
        if settings.llm_provider == "gemini":
            return bool(settings.gemini_api_key)

        return False

    def _format_transcript_with_timestamps(self, segments: list[dict]) -> str:
        """Format transcript segments with timestamps for the LLM."""
        lines = []
        for segment in segments:
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            text = segment.get("text", "")
            speaker = segment.get("speaker", "")

            # Format timestamp as [MM:SS]
            start_min, start_sec = divmod(int(start), 60)
            end_min, end_sec = divmod(int(end), 60)

            if speaker:
                lines.append(
                    f"[{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] "
                    f"({speaker}) {text}"
                )
            else:
                lines.append(
                    f"[{start_min:02d}:{start_sec:02d}-{end_min:02d}:{end_sec:02d}] {text}"
                )

        return "\n".join(lines)

    def _parse_llm_response(self, response: str) -> list[dict]:
        """Parse LLM response and extract clip suggestions."""
        # Try to extract JSON from the response
        response = response.strip()

        # Remove markdown code blocks if present
        if response.startswith("```"):
            response = re.sub(r"^```(?:json)?\n?", "", response)
            response = re.sub(r"\n?```$", "", response)

        # Find JSON array in response
        json_match = re.search(r"\[[\s\S]*\]", response)
        if json_match:
            response = json_match.group()

        try:
            clips = json.loads(response)
            if isinstance(clips, list):
                return clips
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")

        return []

    def _determine_compatible_platforms(
        self, duration: float, requested_platforms: list[SocialPlatform]
    ) -> list[SocialPlatform]:
        """Determine which platforms a clip duration is compatible with."""
        compatible = []
        for platform in requested_platforms:
            max_duration = PLATFORM_MAX_DURATION.get(platform, 180)
            if duration <= max_duration:
                compatible.append(platform)
        return compatible

    async def generate_clips(
        self,
        segments: list[dict],
        job_id: str,
        max_clips: int = 5,
        target_duration: Optional[int] = None,
        platforms: Optional[list[SocialPlatform]] = None,
        min_viral_score: float = 0.5,
    ) -> ClipGenerationResult:
        """Generate viral clip suggestions from transcript segments.

        Args:
            segments: List of transcript segments with start, end, text, speaker
            job_id: ID of the transcription job
            max_clips: Maximum number of clips to generate
            target_duration: Target clip duration in seconds (optional)
            platforms: List of target platforms (default: all)
            min_viral_score: Minimum viral score threshold (0.0-1.0)

        Returns:
            ClipGenerationResult with generated clips
        """
        if not self.provider:
            return ClipGenerationResult(
                success=False,
                job_id=job_id,
                clips=[],
                model="",
                provider="",
                error="No LLM provider configured",
            )

        if not self.provider.is_available():
            return ClipGenerationResult(
                success=False,
                job_id=job_id,
                clips=[],
                model=self.provider.model_name,
                provider=self.provider.name,
                error=f"LLM provider {self.provider.name} is not available",
            )

        # Default to all platforms
        if platforms is None:
            platforms = list(SocialPlatform)

        # Format transcript with timestamps
        transcript = self._format_transcript_with_timestamps(segments)

        # Build prompt
        target_duration_str = (
            f"{target_duration} seconds" if target_duration else "varies by platform"
        )
        platforms_str = ", ".join([p.value for p in platforms])

        prompt = CLIP_GENERATION_PROMPT.format(
            max_clips=max_clips,
            target_duration=target_duration_str,
            min_viral_score=min_viral_score,
            platforms=platforms_str,
            transcript=transcript,
        )

        try:
            logger.info(f"Generating clip suggestions for job {job_id}...")
            response, tokens = await self.provider.generate(prompt, SYSTEM_PROMPT)

            # Parse response
            raw_clips = self._parse_llm_response(response)

            if not raw_clips:
                return ClipGenerationResult(
                    success=False,
                    job_id=job_id,
                    clips=[],
                    model=self.provider.model_name,
                    provider=self.provider.name,
                    tokens_used=tokens,
                    error="Failed to parse clip suggestions from LLM response",
                )

            # Convert to ClipSuggestion objects
            clips = []
            for raw in raw_clips:
                try:
                    duration = raw["end_time"] - raw["start_time"]

                    # Parse platforms from response
                    raw_platforms = raw.get("compatible_platforms", [])
                    compatible = []
                    for p in raw_platforms:
                        try:
                            platform = SocialPlatform(p)
                            if platform in platforms:
                                compatible.append(platform)
                        except ValueError:
                            pass

                    # If no compatible platforms from LLM, determine based on duration
                    if not compatible:
                        compatible = self._determine_compatible_platforms(
                            duration, platforms
                        )

                    # Skip if viral score below threshold
                    viral_score = raw.get("viral_score", 0.5)
                    if viral_score < min_viral_score:
                        continue

                    clip = ClipSuggestion(
                        clip_id=str(uuid.uuid4()),
                        start_time=raw["start_time"],
                        end_time=raw["end_time"],
                        duration=duration,
                        transcript_text=raw.get("transcript_text", ""),
                        hook=raw.get("hook", ""),
                        caption=raw.get("caption", ""),
                        hashtags=raw.get("hashtags", []),
                        viral_score=viral_score,
                        engagement_factors=raw.get("engagement_factors", {}),
                        compatible_platforms=compatible,
                    )
                    clips.append(clip)
                except (KeyError, TypeError) as e:
                    logger.warning(f"Skipping invalid clip data: {e}")
                    continue

            # Sort by viral score descending and limit to max_clips
            clips.sort(key=lambda c: c.viral_score, reverse=True)
            clips = clips[:max_clips]

            logger.info(f"Generated {len(clips)} clip suggestions for job {job_id}")

            return ClipGenerationResult(
                success=True,
                job_id=job_id,
                clips=clips,
                model=self.provider.model_name,
                provider=self.provider.name,
                tokens_used=tokens,
            )

        except Exception as e:
            logger.error(f"Error generating clips: {e}")
            return ClipGenerationResult(
                success=False,
                job_id=job_id,
                clips=[],
                model=self.provider.model_name if self.provider else "",
                provider=self.provider.name if self.provider else "",
                error=str(e),
            )
