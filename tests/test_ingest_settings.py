"""The ingestion core's settings seam (`app.ingest.settings`).

The core reads configuration only through `IngestSettings`: callers can pass
one explicitly, the app registers its own `Settings` (a subclass), and with
neither it loads from env. Cloud transcription credentials come through a
registered provider, never by the core opening the app's database.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.ingest import IngestSettings, download_audio
from app.ingest import settings as ingest_settings
from app.ingest.fetch import auth
from app.ingest.fetch.downloader import DownloaderFactory
from app.ingest.platforms import XimalayaDownloader
from app.ingest.transcribe.transcription_engine import CloudTranscriptionEngine

XIMALAYA_URL = "https://www.ximalaya.com/sound/123456"


@pytest.fixture
def restore_providers():
    """Tests here swap the module-level providers; put the app's back."""
    settings_provider = ingest_settings._settings_provider
    creds_provider = ingest_settings._cloud_credentials_provider
    yield
    ingest_settings._settings_provider = settings_provider
    ingest_settings._cloud_credentials_provider = creds_provider


def test_core_imports_without_loading_app_config_or_store():
    """Using the core as a library must not drag in the app around it."""
    script = textwrap.dedent(
        """
        import sys
        import app.ingest
        from app.ingest.fetch.downloader import _get_platform_downloaders
        from app.ingest.transcribe import transcription_engine, transcriber
        _get_platform_downloaders()
        leaked = sorted(
            m for m in sys.modules
            if m.startswith("app.") and not m.startswith("app.ingest")
        )
        print(",".join(leaked))
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert out.stdout.strip() == ""


def test_app_settings_are_ingest_settings():
    assert issubclass(Settings, IngestSettings)


def test_app_registers_its_cached_settings_with_the_core():
    assert ingest_settings.get_ingest_settings() is get_settings()


def test_app_cache_clear_is_seen_by_the_core():
    before = ingest_settings.get_ingest_settings()
    get_settings.cache_clear()
    try:
        after = ingest_settings.get_ingest_settings()
        assert after is get_settings()
        assert after is not before
    finally:
        get_settings.cache_clear()


def test_without_the_app_the_core_loads_from_env(monkeypatch, restore_providers):
    monkeypatch.setenv("DOWNLOAD_DIR", "/tmp/from-env")
    ingest_settings._settings_from_env.cache_clear()
    ingest_settings.reset_settings_provider()
    try:
        assert ingest_settings.get_ingest_settings().download_dir == "/tmp/from-env"
    finally:
        ingest_settings._settings_from_env.cache_clear()


def test_explicit_settings_reach_the_downloader(tmp_path):
    custom = IngestSettings(download_dir=str(tmp_path / "dl"))
    downloader = DownloaderFactory.get_downloader(XIMALAYA_URL, settings=custom)
    assert isinstance(downloader, XimalayaDownloader)
    assert downloader.settings is custom
    assert downloader.download_dir == tmp_path / "dl"


def test_explicit_settings_reach_the_platform_lookup(tmp_path):
    from app.ingest import Platform

    custom = IngestSettings(download_dir=str(tmp_path))
    downloader = DownloaderFactory.get_downloader_for_platform(
        Platform.XIMALAYA, settings=custom
    )
    assert downloader.settings is custom


async def test_download_audio_passes_settings_through(monkeypatch, tmp_path):
    custom = IngestSettings(download_dir=str(tmp_path))
    seen = {}

    async def fake_download(self, url, **kwargs):
        seen["settings"] = self.settings
        return "result"

    monkeypatch.setattr(XimalayaDownloader, "download", fake_download)
    assert await download_audio(XIMALAYA_URL, settings=custom) == "result"
    assert seen["settings"] is custom


def test_default_downloader_uses_registered_settings():
    downloader = DownloaderFactory.get_downloader(XIMALAYA_URL)
    assert downloader.settings is get_settings()


def test_twitter_cookies_prefer_passed_settings():
    custom = IngestSettings(twitter_cookie_file="/tmp/passed-cookies.txt")
    with auth.twitter_ytdlp_cookies(custom) as path:
        assert path == "/tmp/passed-cookies.txt"


# ─── Cloud transcription credentials ───


def test_cloud_engine_unavailable_without_a_provider(restore_providers):
    ingest_settings.set_cloud_credentials_provider(None)
    assert CloudTranscriptionEngine().is_available() is False


def test_cloud_engine_uses_an_openai_key(restore_providers):
    ingest_settings.set_cloud_credentials_provider(
        lambda: {"provider": "openai", "api_key": "sk-test"}
    )
    engine = CloudTranscriptionEngine()
    assert engine.is_available() is True
    assert engine._api_key == "sk-test"


@pytest.mark.parametrize("provider", ["anthropic", "groq", "ollama", None])
def test_cloud_engine_never_sends_another_providers_key(provider, restore_providers):
    """`transcribe` only calls OpenAI; an Anthropic key must not go there."""
    ingest_settings.set_cloud_credentials_provider(
        lambda: {"provider": provider, "api_key": "not-an-openai-key"}
    )
    engine = CloudTranscriptionEngine()
    assert engine.is_available() is False
    assert engine._api_key is None


def test_cloud_engine_survives_a_failing_provider(restore_providers):
    def boom():
        raise RuntimeError("db locked")

    ingest_settings.set_cloud_credentials_provider(boom)
    assert CloudTranscriptionEngine().is_available() is False


def test_cloud_engine_explicit_key_skips_the_provider(restore_providers):
    ingest_settings.set_cloud_credentials_provider(
        lambda: pytest.fail("provider must not be consulted")
    )
    engine = CloudTranscriptionEngine(api_key="sk-direct")
    assert engine.is_available() is True


def test_store_registers_credentials_from_the_job_store(monkeypatch):
    import app.store as store

    class _FakeStore:
        def get_ai_settings(self):
            return {"provider": "openai", "api_key": "sk-from-db"}

    monkeypatch.setattr(store, "get_job_store", lambda: _FakeStore())
    assert ingest_settings.get_cloud_credentials() == {
        "provider": "openai",
        "api_key": "sk-from-db",
    }
