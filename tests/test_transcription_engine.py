"""Tests for multi-engine transcription architecture."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from app.core.transcription_engine import (
    TranscriptionEngine,
    WhisperEngine,
    SenseVoiceEngine,
    AppleSpeechEngine,
    CloudTranscriptionEngine,
    get_engine,
    get_available_engines,
    get_best_engine,
    EngineInfo,
)
from app.core.transcriber import TranscriptionResult, TranscriptionSegment
from app.api.schemas import TranscriptionEngineType


class TestTranscriptionEngineEnum:
    """Tests for TranscriptionEngine enum."""

    def test_engine_values(self):
        assert TranscriptionEngine.WHISPER == "whisper"
        assert TranscriptionEngine.SENSEVOICE == "sensevoice"
        assert TranscriptionEngine.APPLE == "apple"
        assert TranscriptionEngine.CLOUD == "cloud"

    def test_engine_from_string(self):
        assert TranscriptionEngine("whisper") == TranscriptionEngine.WHISPER
        assert TranscriptionEngine("sensevoice") == TranscriptionEngine.SENSEVOICE

    def test_invalid_engine_raises(self):
        with pytest.raises(ValueError):
            TranscriptionEngine("invalid_engine")


class TestTranscriptionEngineTypeSchema:
    """Tests for the API schema enum."""

    def test_auto_value(self):
        assert TranscriptionEngineType.AUTO == "auto"

    def test_matches_engine_values(self):
        """All non-AUTO engine types should match TranscriptionEngine values."""
        for et in TranscriptionEngineType:
            if et != TranscriptionEngineType.AUTO:
                assert TranscriptionEngine(et.value)


class TestGetEngine:
    """Tests for get_engine factory function."""

    def test_get_whisper_engine(self):
        engine = get_engine(TranscriptionEngine.WHISPER)
        assert isinstance(engine, WhisperEngine)

    def test_get_sensevoice_engine(self):
        engine = get_engine(TranscriptionEngine.SENSEVOICE)
        assert isinstance(engine, SenseVoiceEngine)

    def test_get_apple_engine(self):
        engine = get_engine(TranscriptionEngine.APPLE)
        assert isinstance(engine, AppleSpeechEngine)

    def test_get_cloud_engine(self):
        engine = get_engine(TranscriptionEngine.CLOUD)
        assert isinstance(engine, CloudTranscriptionEngine)

    def test_get_engine_with_kwargs(self):
        engine = get_engine(TranscriptionEngine.WHISPER, model_size="large-v3")
        assert isinstance(engine, WhisperEngine)
        assert engine.model_size == "large-v3"


class TestGetAvailableEngines:
    """Tests for get_available_engines."""

    def test_returns_list_of_engine_info(self):
        engines = get_available_engines()
        assert isinstance(engines, list)
        assert len(engines) == 4
        for info in engines:
            assert isinstance(info, EngineInfo)

    def test_all_engines_represented(self):
        engines = get_available_engines()
        engine_ids = {e.engine for e in engines}
        assert TranscriptionEngine.WHISPER in engine_ids
        assert TranscriptionEngine.SENSEVOICE in engine_ids
        assert TranscriptionEngine.APPLE in engine_ids
        assert TranscriptionEngine.CLOUD in engine_ids

    def test_engine_info_has_required_fields(self):
        engines = get_available_engines()
        for info in engines:
            assert info.name
            assert info.description
            assert isinstance(info.languages, list)
            assert isinstance(info.models, list)
            assert isinstance(info.requires_download, bool)
            assert isinstance(info.available, bool)


class TestGetBestEngine:
    """Tests for get_best_engine auto-selection."""

    @patch.object(SenseVoiceEngine, "is_available", return_value=True)
    def test_selects_sensevoice_for_chinese(self, _mock):
        result = get_best_engine(language="zh")
        assert result == TranscriptionEngine.SENSEVOICE

    @patch.object(SenseVoiceEngine, "is_available", return_value=True)
    def test_selects_sensevoice_for_english(self, _mock):
        result = get_best_engine(language="en")
        assert result == TranscriptionEngine.SENSEVOICE

    @patch.object(SenseVoiceEngine, "is_available", return_value=True)
    def test_selects_sensevoice_for_auto(self, _mock):
        result = get_best_engine(language=None)
        assert result == TranscriptionEngine.SENSEVOICE

    @patch.object(SenseVoiceEngine, "is_available", return_value=False)
    @patch.object(WhisperEngine, "is_available", return_value=True)
    def test_falls_back_to_whisper(self, _mock_w, _mock_sv):
        result = get_best_engine(language="zh")
        assert result == TranscriptionEngine.WHISPER

    @patch.object(SenseVoiceEngine, "is_available", return_value=False)
    @patch.object(WhisperEngine, "is_available", return_value=False)
    @patch.object(AppleSpeechEngine, "is_available", return_value=True)
    def test_falls_back_to_apple(self, _mock_a, _mock_w, _mock_sv):
        result = get_best_engine(language="en")
        assert result == TranscriptionEngine.APPLE

    @patch.object(SenseVoiceEngine, "is_available", return_value=False)
    @patch.object(WhisperEngine, "is_available", return_value=False)
    @patch.object(AppleSpeechEngine, "is_available", return_value=False)
    @patch.object(CloudTranscriptionEngine, "is_available", return_value=True)
    def test_falls_back_to_cloud(self, _mock_c, _mock_a, _mock_w, _mock_sv):
        result = get_best_engine(language="en")
        assert result == TranscriptionEngine.CLOUD

    @patch.object(SenseVoiceEngine, "is_available", return_value=False)
    @patch.object(WhisperEngine, "is_available", return_value=False)
    @patch.object(AppleSpeechEngine, "is_available", return_value=False)
    @patch.object(CloudTranscriptionEngine, "is_available", return_value=False)
    def test_defaults_to_whisper_when_none_available(self, *_mocks):
        result = get_best_engine(language="en")
        assert result == TranscriptionEngine.WHISPER

    @patch.object(SenseVoiceEngine, "is_available", return_value=True)
    @patch.object(WhisperEngine, "is_available", return_value=True)
    def test_prefers_whisper_for_unsupported_sensevoice_language(self, _mock_w, _mock_sv):
        # SenseVoice only supports zh/en/ja/ko/yue
        result = get_best_engine(language="fr")
        assert result == TranscriptionEngine.WHISPER


class TestWhisperEngineInfo:
    """Tests for WhisperEngine metadata."""

    def test_engine_info(self):
        engine = WhisperEngine()
        info = engine.get_info()
        assert info.engine == TranscriptionEngine.WHISPER
        assert info.requires_download is True
        assert "whisper" in info.name.lower()


class TestSenseVoiceEngineInfo:
    """Tests for SenseVoiceEngine metadata."""

    def test_engine_info(self):
        engine = SenseVoiceEngine()
        info = engine.get_info()
        assert info.engine == TranscriptionEngine.SENSEVOICE
        assert info.requires_download is True
        assert "zh" in info.languages

    def test_default_model_id(self):
        engine = SenseVoiceEngine()
        assert engine.model_id == "iic/SenseVoiceSmall"


class TestAppleSpeechEngineInfo:
    """Tests for AppleSpeechEngine metadata."""

    def test_engine_info(self):
        engine = AppleSpeechEngine()
        info = engine.get_info()
        assert info.engine == TranscriptionEngine.APPLE
        assert info.requires_download is False
        assert info.platform_restriction == "macOS"


class TestCloudEngineInfo:
    """Tests for CloudTranscriptionEngine metadata."""

    def test_engine_info(self):
        engine = CloudTranscriptionEngine()
        info = engine.get_info()
        assert info.engine == TranscriptionEngine.CLOUD
        assert info.requires_download is False


class TestBackwardCompatibility:
    """Tests for backward compatibility aliases."""

    def test_audiograb_error_alias(self):
        from app.core.exceptions import SiftError, AudioGrabError, XDownloaderError
        assert AudioGrabError is SiftError
        assert XDownloaderError is SiftError

    def test_audiograb_error_importable_from_core(self):
        from app.core import AudioGrabError, SiftError
        assert AudioGrabError is SiftError
