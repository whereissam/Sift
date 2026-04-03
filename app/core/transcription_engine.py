"""Multi-engine transcription architecture.

Supports multiple ASR backends:
- whisper: faster-whisper (legacy, 99 languages)
- sensevoice: SenseVoice-Small via FunASR (best for zh+en, fast)
- apple: macOS SFSpeechRecognizer (zero setup, macOS only)
- cloud: Cloud APIs (gpt-4o-mini-transcribe, Groq Whisper)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TranscriptionEngine(str, Enum):
    """Available transcription engines."""

    WHISPER = "whisper"
    SENSEVOICE = "sensevoice"
    APPLE = "apple"
    CLOUD = "cloud"


@dataclass
class EngineInfo:
    """Information about a transcription engine."""

    engine: TranscriptionEngine
    available: bool
    name: str
    description: str
    languages: list[str]
    models: list[str]
    requires_download: bool
    platform_restriction: Optional[str] = None  # e.g., "macOS"


class BaseTranscriptionEngine(ABC):
    """Abstract base class for transcription engines."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> "TranscriptionResult":
        """Transcribe an audio file."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available."""
        ...

    @abstractmethod
    def get_info(self) -> EngineInfo:
        """Get engine information."""
        ...


# Re-export shared types from transcriber for backward compat
from .transcriber import TranscriptionResult, TranscriptionSegment


class WhisperEngine(BaseTranscriptionEngine):
    """Wrapper around existing faster-whisper transcriber."""

    def __init__(self, model_size: str = "base", device: str = "auto", compute_type: str = "auto"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        from .transcriber import AudioTranscriber

        model_size = model or self.model_size
        transcriber = AudioTranscriber(
            model_size=model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        return await transcriber.transcribe(
            audio_path=audio_path,
            language=language,
            **kwargs,
        )

    def is_available(self) -> bool:
        try:
            from faster_whisper import WhisperModel
            return True
        except ImportError:
            return False

    def get_info(self) -> EngineInfo:
        return EngineInfo(
            engine=TranscriptionEngine.WHISPER,
            available=self.is_available(),
            name="Whisper (faster-whisper)",
            description="OpenAI Whisper via CTranslate2. Supports 99 languages. Good general-purpose accuracy.",
            languages=["auto", "en", "zh", "ja", "ko", "es", "fr", "de", "and 90+ more"],
            models=["tiny", "base", "small", "medium", "large-v3", "turbo", "distil-large-v3"],
            requires_download=True,
        )


class SenseVoiceEngine(BaseTranscriptionEngine):
    """SenseVoice-Small via FunASR — optimized for Chinese + English."""

    _model = None
    _current_model_id = None

    def __init__(self, model_id: str = "iic/SenseVoiceSmall"):
        self.model_id = model_id

    def _get_model(self):
        """Lazy-load SenseVoice model."""
        if SenseVoiceEngine._model is None or SenseVoiceEngine._current_model_id != self.model_id:
            from funasr import AutoModel

            logger.info(f"Loading SenseVoice model: {self.model_id}")
            SenseVoiceEngine._model = AutoModel(
                model=self.model_id,
                trust_remote_code=True,
                device="cpu",
            )
            SenseVoiceEngine._current_model_id = self.model_id
            logger.info("SenseVoice model loaded")

        return SenseVoiceEngine._model

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        import asyncio

        audio_path = Path(audio_path)
        if not audio_path.exists():
            return TranscriptionResult(
                success=False,
                error=f"Audio file not found: {audio_path}",
            )

        try:
            sv_model = self._get_model()

            # SenseVoice language mapping
            lang_map = {
                "zh": "zh",
                "en": "en",
                "ja": "ja",
                "ko": "ko",
                "yue": "yue",  # Cantonese
            }
            sv_language = lang_map.get(language, "auto") if language else "auto"

            # Run in thread pool to avoid blocking
            result = await asyncio.to_thread(
                sv_model.generate,
                input=str(audio_path),
                cache={},
                language=sv_language,
                use_itn=True,  # Inverse text normalization (numbers, dates)
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,
            )

            if not result or len(result) == 0:
                return TranscriptionResult(
                    success=False,
                    error="SenseVoice returned no results",
                )

            # Parse SenseVoice output
            segments = []
            full_text_parts = []

            for item in result:
                text = item.get("text", "")
                # SenseVoice may include emotion/event tags like <|HAPPY|>, strip them
                import re
                text = re.sub(r"<\|[^|]*\|>", "", text).strip()

                if not text:
                    continue

                # SenseVoice returns timestamps if available
                if "timestamp" in item and item["timestamp"]:
                    for ts_entry in item["timestamp"]:
                        if isinstance(ts_entry, (list, tuple)) and len(ts_entry) >= 3:
                            start_ms, end_ms, seg_text = ts_entry[0], ts_entry[1], ts_entry[2]
                            seg_text = re.sub(r"<\|[^|]*\|>", "", str(seg_text)).strip()
                            if seg_text:
                                segments.append(TranscriptionSegment(
                                    start=start_ms / 1000.0,
                                    end=end_ms / 1000.0,
                                    text=seg_text,
                                ))
                                full_text_parts.append(seg_text)
                else:
                    # No timestamps, treat as single segment
                    full_text_parts.append(text)
                    segments.append(TranscriptionSegment(
                        start=0.0,
                        end=0.0,
                        text=text,
                    ))

            full_text = " ".join(full_text_parts) if full_text_parts else ""

            # Detect language from result if available
            detected_lang = language or "auto"
            for item in result:
                if "key" in item and item["key"]:
                    # Some FunASR models return language info
                    pass

            # Estimate duration from audio
            duration = None
            try:
                import subprocess
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(audio_path)],
                    capture_output=True, text=True, timeout=10,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    duration = float(probe.stdout.strip())
            except Exception:
                pass

            return TranscriptionResult(
                success=True,
                text=full_text,
                segments=segments if segments else None,
                language=detected_lang,
                language_probability=0.99 if language else 0.95,
                duration=duration,
            )

        except Exception as e:
            logger.exception(f"SenseVoice transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    def is_available(self) -> bool:
        try:
            import funasr
            return True
        except ImportError:
            return False

    def get_info(self) -> EngineInfo:
        return EngineInfo(
            engine=TranscriptionEngine.SENSEVOICE,
            available=self.is_available(),
            name="SenseVoice (FunASR)",
            description="Alibaba SenseVoice-Small. 15x faster than Whisper-Large, excellent Chinese + English accuracy.",
            languages=["auto", "zh", "en", "ja", "ko", "yue"],
            models=["iic/SenseVoiceSmall"],
            requires_download=True,
        )


class AppleSpeechEngine(BaseTranscriptionEngine):
    """macOS SFSpeechRecognizer — zero setup, on-device."""

    def __init__(self):
        self._authorized = None

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        import asyncio
        import sys

        if sys.platform != "darwin":
            return TranscriptionResult(
                success=False,
                error="Apple Speech is only available on macOS",
            )

        audio_path = Path(audio_path)
        if not audio_path.exists():
            return TranscriptionResult(
                success=False,
                error=f"Audio file not found: {audio_path}",
            )

        try:
            # Convert to WAV first (Apple Speech works best with WAV/M4A)
            wav_path = audio_path.with_suffix(".apple_tmp.wav")
            needs_cleanup = False
            if audio_path.suffix.lower() not in (".wav", ".m4a", ".caf", ".aac"):
                import subprocess
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
                    capture_output=True, timeout=120,
                )
                needs_cleanup = True
                process_path = wav_path
            else:
                process_path = audio_path

            # Get audio duration for chunking
            duration = await self._get_duration(process_path)

            # Apple Speech has ~1 min limit per request, chunk if needed
            if duration and duration > 55:
                result = await self._transcribe_chunked(process_path, language, duration)
            else:
                result = await asyncio.to_thread(
                    self._transcribe_file, str(process_path), language
                )

            if needs_cleanup and wav_path.exists():
                wav_path.unlink()

            return result

        except Exception as e:
            logger.exception(f"Apple Speech transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    async def _get_duration(self, audio_path: Path) -> Optional[float]:
        try:
            import subprocess
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(audio_path)],
                capture_output=True, text=True, timeout=10,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                return float(probe.stdout.strip())
        except Exception:
            pass
        return None

    async def _transcribe_chunked(
        self, audio_path: Path, language: Optional[str], duration: float
    ) -> TranscriptionResult:
        """Split audio into chunks and transcribe each."""
        import asyncio
        import subprocess
        import tempfile

        chunk_duration = 50  # seconds per chunk
        segments = []
        full_text_parts = []
        offset = 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_idx = 0
            while offset < duration:
                chunk_path = Path(tmpdir) / f"chunk_{chunk_idx:04d}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(audio_path),
                     "-ss", str(offset), "-t", str(chunk_duration),
                     "-ar", "16000", "-ac", "1", str(chunk_path)],
                    capture_output=True, timeout=60,
                )

                if not chunk_path.exists():
                    break

                result = await asyncio.to_thread(
                    self._transcribe_file, str(chunk_path), language
                )

                if result.success and result.text:
                    full_text_parts.append(result.text)
                    if result.segments:
                        for seg in result.segments:
                            segments.append(TranscriptionSegment(
                                start=seg.start + offset,
                                end=seg.end + offset,
                                text=seg.text,
                            ))

                offset += chunk_duration
                chunk_idx += 1

        return TranscriptionResult(
            success=True,
            text=" ".join(full_text_parts),
            segments=segments if segments else None,
            language=language or "auto",
            language_probability=0.9,
            duration=duration,
        )

    def _transcribe_file(self, file_path: str, language: Optional[str] = None) -> TranscriptionResult:
        """Synchronous transcription using SFSpeechRecognizer via PyObjC."""
        import threading

        try:
            import objc
            objc.loadBundle(
                "Speech",
                bundle_path="/System/Library/Frameworks/Speech.framework",
                module_globals=globals(),
            )
            from Foundation import NSURL, NSLocale
        except ImportError:
            return TranscriptionResult(
                success=False,
                error="PyObjC not installed. Install with: uv pip install pyobjc-core pyobjc-framework-Speech",
            )

        # Map language to Apple locale
        locale_map = {
            "en": "en-US",
            "zh": "zh-CN",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "es": "es-ES",
            "fr": "fr-FR",
            "de": "de-DE",
        }
        locale_id = locale_map.get(language, "en-US") if language else "en-US"

        result_text = []
        is_done = threading.Event()
        error_msg = [None]

        locale = NSLocale.alloc().initWithLocaleIdentifier_(locale_id)
        recognizer = globals().get("SFSpeechRecognizer")
        if recognizer is None:
            return TranscriptionResult(
                success=False,
                error="SFSpeechRecognizer not available",
            )

        recognizer_instance = recognizer.alloc().initWithLocale_(locale)
        if recognizer_instance is None or not recognizer_instance.isAvailable():
            return TranscriptionResult(
                success=False,
                error=f"Speech recognition not available for locale {locale_id}",
            )

        audio_url = NSURL.fileURLWithPath_(file_path)

        request_cls = globals().get("SFSpeechURLRecognitionRequest")
        if request_cls is None:
            return TranscriptionResult(
                success=False,
                error="SFSpeechURLRecognitionRequest not available",
            )

        request = request_cls.alloc().initWithURL_(audio_url)
        request.setShouldReportPartialResults_(False)

        if recognizer_instance.supportsOnDeviceRecognition():
            request.setRequiresOnDeviceRecognition_(True)

        def handler(result, error):
            if error is not None:
                error_msg[0] = str(error)
                is_done.set()
                return
            if result is not None and result.isFinal():
                result_text.append(result.bestTranscription().formattedString())
                is_done.set()

        recognizer_instance.recognitionTaskWithRequest_resultHandler_(request, handler)

        is_done.wait(timeout=120)

        if error_msg[0]:
            return TranscriptionResult(
                success=False,
                error=f"Apple Speech error: {error_msg[0]}",
            )

        text = result_text[0] if result_text else ""

        return TranscriptionResult(
            success=True,
            text=text,
            segments=[TranscriptionSegment(start=0.0, end=0.0, text=text)] if text else None,
            language=language or "en",
            language_probability=0.9,
            duration=None,
        )

    def is_available(self) -> bool:
        import sys
        if sys.platform != "darwin":
            return False
        try:
            import objc
            objc.loadBundle(
                "Speech",
                bundle_path="/System/Library/Frameworks/Speech.framework",
                module_globals={},
            )
            return True
        except (ImportError, Exception):
            return False

    def get_info(self) -> EngineInfo:
        return EngineInfo(
            engine=TranscriptionEngine.APPLE,
            available=self.is_available(),
            name="Apple Speech (macOS)",
            description="Built-in macOS speech recognition. Zero setup, no model download. On-device processing.",
            languages=["en", "zh", "ja", "ko", "es", "fr", "de", "and 50+ more"],
            models=["on-device"],
            requires_download=False,
            platform_restriction="macOS",
        )


class CloudTranscriptionEngine(BaseTranscriptionEngine):
    """Cloud-based transcription via OpenAI or Groq APIs."""

    def __init__(self):
        self._provider = None
        self._api_key = None

    def _load_settings(self):
        """Load AI provider settings."""
        try:
            from ..config import get_settings
            settings = get_settings()
            # Try to get from AI settings in database
            from .job_store import JobStore
            store = JobStore(settings.download_dir)
            ai_settings = store.get_ai_settings()
            if ai_settings:
                self._provider = ai_settings.get("provider")
                self._api_key = ai_settings.get("api_key")
        except Exception:
            pass

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> TranscriptionResult:
        self._load_settings()

        if not self._api_key:
            return TranscriptionResult(
                success=False,
                error="No cloud API key configured. Set up an AI provider in Settings.",
            )

        audio_path = Path(audio_path)
        if not audio_path.exists():
            return TranscriptionResult(
                success=False,
                error=f"Audio file not found: {audio_path}",
            )

        try:
            import httpx

            # Default to OpenAI's transcription API
            api_url = "https://api.openai.com/v1/audio/transcriptions"
            model_name = model or "gpt-4o-mini-transcribe"

            async with httpx.AsyncClient(timeout=600.0) as client:
                with open(audio_path, "rb") as f:
                    files = {"file": (audio_path.name, f, "audio/mpeg")}
                    data = {"model": model_name}
                    if language:
                        data["language"] = language

                    response = await client.post(
                        api_url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        files=files,
                        data=data,
                    )
                    response.raise_for_status()
                    result = response.json()

            text = result.get("text", "")

            return TranscriptionResult(
                success=True,
                text=text,
                segments=None,
                language=language or result.get("language", "auto"),
                language_probability=0.99,
                duration=result.get("duration"),
            )

        except Exception as e:
            logger.exception(f"Cloud transcription error: {e}")
            return TranscriptionResult(
                success=False,
                error=str(e),
            )

    def is_available(self) -> bool:
        self._load_settings()
        return bool(self._api_key)

    def get_info(self) -> EngineInfo:
        return EngineInfo(
            engine=TranscriptionEngine.CLOUD,
            available=self.is_available(),
            name="Cloud (OpenAI / Groq)",
            description="Cloud-based transcription for maximum quality. Requires API key in Settings.",
            languages=["auto", "en", "zh", "ja", "ko", "and 90+ more"],
            models=["gpt-4o-mini-transcribe", "whisper-1"],
            requires_download=False,
        )


# ─── Engine Registry ───

_engines: dict[TranscriptionEngine, BaseTranscriptionEngine] = {}


def get_engine(engine: TranscriptionEngine, **kwargs) -> BaseTranscriptionEngine:
    """Get or create a transcription engine instance."""
    if engine == TranscriptionEngine.WHISPER:
        return WhisperEngine(**kwargs)
    elif engine == TranscriptionEngine.SENSEVOICE:
        return SenseVoiceEngine(**kwargs)
    elif engine == TranscriptionEngine.APPLE:
        return AppleSpeechEngine()
    elif engine == TranscriptionEngine.CLOUD:
        return CloudTranscriptionEngine()
    else:
        raise ValueError(f"Unknown engine: {engine}")


def get_available_engines() -> list[EngineInfo]:
    """List all engines and their availability."""
    engines = [
        SenseVoiceEngine(),
        WhisperEngine(),
        AppleSpeechEngine(),
        CloudTranscriptionEngine(),
    ]
    return [e.get_info() for e in engines]


def get_best_engine(language: Optional[str] = None) -> TranscriptionEngine:
    """Auto-select the best available engine for a language.

    Priority:
    1. SenseVoice for zh/en/ja/ko (much better accuracy)
    2. Whisper for other languages (99 language support)
    3. Apple Speech as fallback (zero setup)
    4. Cloud as last resort
    """
    sv = SenseVoiceEngine()
    if sv.is_available():
        sv_langs = {"zh", "en", "ja", "ko", "yue", None}  # None = auto
        if language in sv_langs:
            return TranscriptionEngine.SENSEVOICE

    wh = WhisperEngine()
    if wh.is_available():
        return TranscriptionEngine.WHISPER

    apple = AppleSpeechEngine()
    if apple.is_available():
        return TranscriptionEngine.APPLE

    cloud = CloudTranscriptionEngine()
    if cloud.is_available():
        return TranscriptionEngine.CLOUD

    # Default to whisper even if not installed (will fail with helpful message)
    return TranscriptionEngine.WHISPER
