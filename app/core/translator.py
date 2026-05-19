"""Translation service using TranslateGemma via LiteLLM/Ollama."""

import logging
from dataclasses import dataclass
from typing import Optional

from litellm import acompletion

logger = logging.getLogger(__name__)


# Chinese variant conversion using OpenCC
def convert_chinese(text: str, source: str, target: str) -> str:
    """Convert between Simplified and Traditional Chinese using OpenCC.

    Args:
        text: Text to convert
        source: Source variant ('zh-Hans' or 'zh-Hant')
        target: Target variant ('zh-Hans' or 'zh-Hant')

    Returns:
        Converted text
    """
    try:
        from opencc import OpenCC

        if source == "zh-Hant" and target == "zh-Hans":
            # Traditional to Simplified
            cc = OpenCC("t2s")
            return cc.convert(text)
        elif source == "zh-Hans" and target == "zh-Hant":
            # Simplified to Traditional
            cc = OpenCC("s2t")
            return cc.convert(text)
        else:
            return text
    except ImportError:
        logger.warning("OpenCC not installed, cannot convert Chinese variants")
        return text
    except Exception as e:
        logger.error(f"Chinese conversion failed: {e}")
        return text


def is_chinese_variant_conversion(source: str, target: str) -> bool:
    """Check if this is a Chinese variant conversion (not actual translation)."""
    chinese_codes = {"zh-Hans", "zh-Hant", "zh", "zh-cn", "zh-tw"}
    return source in chinese_codes and target in chinese_codes and source != target


# TranslateGemma supported languages (55 languages)
SUPPORTED_LANGUAGES = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "az": "Azerbaijani",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "ga": "Irish",
    "gl": "Galician",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Filipino",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
}

# Common languages shown in UI (subset of SUPPORTED_LANGUAGES)
COMMON_LANGUAGES = {
    "en": "English",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
}

# Common language aliases
LANGUAGE_ALIASES = {
    "zh": "zh-Hans",
    "chinese": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-tw": "zh-Hant",
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "korean": "ko",
    "portuguese": "pt",
    "russian": "ru",
    "italian": "it",
    "dutch": "nl",
    "arabic": "ar",
    "hindi": "hi",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "turkish": "tr",
    "polish": "pl",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "hebrew": "he",
    "czech": "cs",
    "hungarian": "hu",
    "romanian": "ro",
    "ukrainian": "uk",
    "bengali": "bn",
    "tamil": "ta",
    "telugu": "te",
    "marathi": "mr",
    "gujarati": "gu",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
    "urdu": "ur",
    "persian": "fa",
    "farsi": "fa",
    "malay": "ms",
    "filipino": "tl",
    "tagalog": "tl",
    "burmese": "my",
    "khmer": "km",
    "nepali": "ne",
    "mongolian": "mn",
    "kazakh": "kk",
    "uzbek": "uz",
    "azerbaijani": "az",
    "georgian": "ka",
    "armenian": "hy",
    "albanian": "sq",
    "serbian": "sr",
    "croatian": "hr",
    "slovenian": "sl",
    "slovak": "sk",
    "bulgarian": "bg",
    "macedonian": "mk",
    "lithuanian": "lt",
    "latvian": "lv",
    "estonian": "et",
    "belarusian": "be",
    "icelandic": "is",
    "welsh": "cy",
    "irish": "ga",
    "galician": "gl",
    "catalan": "ca",
    "afrikaans": "af",
    "swahili": "sw",
    "amharic": "am",
}


@dataclass
class TranslationResult:
    """Result of a translation operation."""
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    tokens_used: Optional[int] = None


def normalize_language_code(lang: str) -> str:
    """Normalize a language code or name to standard code."""
    lang_lower = lang.lower().strip()

    # Check if it's an alias
    if lang_lower in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[lang_lower]

    # Check if it's already a valid code
    if lang in SUPPORTED_LANGUAGES:
        return lang

    # Check case-insensitive
    for code in SUPPORTED_LANGUAGES:
        if code.lower() == lang_lower:
            return code

    raise ValueError(f"Unsupported language: {lang}")


def get_language_name(code: str) -> str:
    """Get the full language name for a code."""
    normalized = normalize_language_code(code)
    return SUPPORTED_LANGUAGES.get(normalized, code)


class TranslateGemmaTranslator:
    """Translator using TranslateGemma model via Ollama/LiteLLM."""

    # Default model sizes available
    MODELS = {
        "4b": "translategemma:4b",
        "12b": "translategemma:12b",
        "27b": "translategemma:27b",
        "latest": "translategemma:latest",
    }

    # Chunk size for long texts (in characters, conservative estimate)
    CHUNK_SIZE = 2000
    CHUNK_OVERLAP = 100

    def __init__(
        self,
        model: str = "translategemma:4b",
        base_url: str = "http://localhost:11434",
    ):
        """Initialize the translator.

        Args:
            model: Model name (translategemma:4b, 12b, or 27b)
            base_url: Ollama base URL
        """
        self.model = model
        self.base_url = base_url
        self._available: Optional[bool] = None

    def _build_prompt(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """Build the TranslateGemma prompt format."""
        source_code = normalize_language_code(source_lang)
        target_code = normalize_language_code(target_lang)
        source_name = SUPPORTED_LANGUAGES[source_code]
        target_name = SUPPORTED_LANGUAGES[target_code]

        # TranslateGemma expects this specific format with two blank lines before text
        prompt = f"""You are a professional {source_name} ({source_code}) to {target_name} ({target_code}) translator. Your goal is to accurately convey the meaning and nuances of the original {source_name} text while adhering to {target_name} grammar, vocabulary, and cultural sensitivities.
Produce only the {target_name} translation, without any additional explanations or commentary. Please translate the following {source_name} text into {target_name}:


{text}"""
        return prompt

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks for translation, trying to break at sentence boundaries."""
        if len(text) <= self.CHUNK_SIZE:
            return [text]

        chunks = []
        current_pos = 0

        while current_pos < len(text):
            # Determine the end position for this chunk
            end_pos = min(current_pos + self.CHUNK_SIZE, len(text))

            # If not at the end, try to find a sentence boundary
            if end_pos < len(text):
                # Look for sentence endings within the last 200 chars of the chunk
                search_start = max(end_pos - 200, current_pos)
                search_text = text[search_start:end_pos]

                # Try to find sentence boundaries (., !, ?, 。, ！, ？)
                best_break = -1
                for ending in ['. ', '! ', '? ', '。', '！', '？', '\n\n', '\n']:
                    pos = search_text.rfind(ending)
                    if pos != -1:
                        # Calculate actual position relative to search_start
                        actual_pos = search_start + pos + len(ending)
                        if actual_pos > best_break:
                            best_break = actual_pos

                if best_break > current_pos:
                    end_pos = best_break

            chunk = text[current_pos:end_pos].strip()
            if chunk:
                chunks.append(chunk)

            # Move to next chunk with some overlap for context
            current_pos = end_pos

        return chunks

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> TranslationResult:
        """Translate text from source language to target language.

        Args:
            text: Text to translate
            source_lang: Source language code or name
            target_lang: Target language code or name

        Returns:
            TranslationResult with translated text
        """
        # Normalize language codes
        source_code = normalize_language_code(source_lang)
        target_code = normalize_language_code(target_lang)

        if source_code == target_code:
            return TranslationResult(
                source_text=text,
                translated_text=text,
                source_lang=source_code,
                target_lang=target_code,
                model=self.model,
                tokens_used=0,
            )

        # Special case: Chinese variant conversion (Traditional <-> Simplified)
        # Use OpenCC instead of LLM for accurate character conversion
        if is_chinese_variant_conversion(source_code, target_code):
            logger.info(f"Using OpenCC for Chinese variant conversion: {source_code} -> {target_code}")
            converted = convert_chinese(text, source_code, target_code)
            return TranslationResult(
                source_text=text,
                translated_text=converted,
                source_lang=source_code,
                target_lang=target_code,
                model="opencc",
                tokens_used=0,
            )

        # Chunk text if too long
        chunks = self._chunk_text(text)
        logger.info(f"Translating text in {len(chunks)} chunk(s)")

        translated_chunks = []
        total_tokens = 0

        for i, chunk in enumerate(chunks):
            logger.info(f"Translating chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")

            prompt = self._build_prompt(chunk, source_code, target_code)

            # Use LiteLLM to call Ollama
            response = await acompletion(
                model=f"ollama/{self.model}",
                messages=[{"role": "user", "content": prompt}],
                base_url=self.base_url,
            )

            translated = response.choices[0].message.content.strip()
            translated_chunks.append(translated)

            if response.usage:
                total_tokens += response.usage.total_tokens

        # Join translated chunks
        full_translation = "\n\n".join(translated_chunks)

        return TranslationResult(
            source_text=text,
            translated_text=full_translation,
            source_lang=source_code,
            target_lang=target_code,
            model=self.model,
            tokens_used=total_tokens if total_tokens else None,
        )

    def is_available(self) -> bool:
        """Check if TranslateGemma is available."""
        if self._available is not None:
            return self._available

        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url.rstrip('/')}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if any translategemma model is available
                    self._available = any("translategemma" in m for m in models)
                else:
                    self._available = False
        except Exception:
            self._available = False

        return self._available

    @classmethod
    def from_settings(cls) -> "TranslateGemmaTranslator":
        """Create translator from application settings."""
        from ..config import get_settings
        settings = get_settings()

        return cls(
            model=getattr(settings, "translategemma_model", "translategemma:4b"),
            base_url=settings.ollama_base_url,
        )


def get_supported_languages() -> dict[str, str]:
    """Get all supported languages."""
    return SUPPORTED_LANGUAGES.copy()


class AITranslator:
    """Translator using the configured AI provider (GPT-4, Claude, etc.).

    This provides higher quality translations than TranslateGemma but requires
    a configured AI provider with API key.
    """

    # Chunk size for long texts
    CHUNK_SIZE = 3000
    CHUNK_OVERLAP = 100

    def __init__(self, provider=None):
        """Initialize with optional LiteLLM provider."""
        self.provider = provider

    @classmethod
    def from_settings(cls) -> "AITranslator":
        """Create translator from application settings."""
        from .job_store import get_job_store
        from ..config import get_settings

        settings = get_settings()
        provider = None

        # Try to get settings from database first
        try:
            job_store = get_job_store()
            ai_settings = job_store.get_ai_settings()
            if ai_settings:
                from .summarizer import LiteLLMProvider

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
        if settings.llm_provider == "openai" and settings.openai_api_key:
            from .summarizer import LiteLLMProvider

            provider = LiteLLMProvider(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                provider="openai",
            )
        elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            from .summarizer import LiteLLMProvider

            provider = LiteLLMProvider(
                model=settings.anthropic_model,
                api_key=settings.anthropic_api_key,
                provider="anthropic",
            )

        return cls(provider=provider)

    @staticmethod
    def _build_litellm_model(provider: str, model: str) -> str:
        """Build the LiteLLM model string."""
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
            return model

    @staticmethod
    def is_available() -> bool:
        """Check if an AI provider is configured."""
        from .job_store import get_job_store
        from ..config import get_settings

        settings = get_settings()

        try:
            job_store = get_job_store()
            ai_settings = job_store.get_ai_settings()
            if ai_settings:
                return bool(ai_settings.get("api_key") or ai_settings.get("provider") == "ollama")
        except Exception:
            pass

        if settings.llm_provider in ("openai", "openai_compatible"):
            return bool(settings.openai_api_key)
        if settings.llm_provider == "anthropic":
            return bool(settings.anthropic_api_key)

        return False

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks for translation."""
        if len(text) <= self.CHUNK_SIZE:
            return [text]

        chunks = []
        current_pos = 0

        while current_pos < len(text):
            end_pos = min(current_pos + self.CHUNK_SIZE, len(text))

            if end_pos < len(text):
                search_start = max(end_pos - 200, current_pos)
                search_text = text[search_start:end_pos]

                best_break = -1
                for ending in ['. ', '! ', '? ', '。', '！', '？', '\n\n', '\n']:
                    pos = search_text.rfind(ending)
                    if pos != -1:
                        actual_pos = search_start + pos + len(ending)
                        if actual_pos > best_break:
                            best_break = actual_pos

                if best_break > current_pos:
                    end_pos = best_break

            chunk = text[current_pos:end_pos].strip()
            if chunk:
                chunks.append(chunk)

            current_pos = end_pos

        return chunks

    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """Build translation prompt."""
        source_name = SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        return f"""Translate the following text from {source_name} to {target_name}.

Important instructions:
- Produce ONLY the translation, no explanations or commentary
- Preserve the original meaning, tone, and style
- For {target_lang}, use the correct script/variant (e.g., Traditional Chinese uses 繁體字, not 简体字)
- Maintain paragraph structure and formatting

Text to translate:

{text}"""

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> TranslationResult:
        """Translate text using the configured AI provider."""
        source_code = normalize_language_code(source_lang)
        target_code = normalize_language_code(target_lang)

        if source_code == target_code:
            return TranslationResult(
                source_text=text,
                translated_text=text,
                source_lang=source_code,
                target_lang=target_code,
                model="none",
                tokens_used=0,
            )

        # Special case: Chinese variant conversion (Traditional <-> Simplified)
        # Use OpenCC instead of LLM for accurate character conversion
        if is_chinese_variant_conversion(source_code, target_code):
            logger.info(f"Using OpenCC for Chinese variant conversion: {source_code} -> {target_code}")
            converted = convert_chinese(text, source_code, target_code)
            return TranslationResult(
                source_text=text,
                translated_text=converted,
                source_lang=source_code,
                target_lang=target_code,
                model="opencc",
                tokens_used=0,
            )

        if not self.provider:
            raise ValueError("No AI provider configured")

        chunks = self._chunk_text(text)
        logger.info(f"AI translating text in {len(chunks)} chunk(s)")

        translated_chunks = []
        total_tokens = 0

        system_prompt = f"You are a professional translator specializing in {SUPPORTED_LANGUAGES.get(target_code, target_code)}. Produce accurate, natural translations."

        for i, chunk in enumerate(chunks):
            logger.info(f"AI translating chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")

            prompt = self._build_prompt(chunk, source_code, target_code)
            translated, tokens = await self.provider.generate(prompt, system_prompt)

            translated_chunks.append(translated.strip())
            total_tokens += tokens

        full_translation = "\n\n".join(translated_chunks)

        return TranslationResult(
            source_text=text,
            translated_text=full_translation,
            source_lang=source_code,
            target_lang=target_code,
            model=self.provider.model_name,
            tokens_used=total_tokens if total_tokens else None,
        )