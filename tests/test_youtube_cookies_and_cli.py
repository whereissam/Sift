"""Tests for YouTube cookie configuration and the repaired CLI."""

import asyncio
from types import SimpleNamespace

import pytest

from sift_core.platforms.youtube import youtube_cookie_args


# ---------------------------------------------------------------------------
# YouTube cookie args
# ---------------------------------------------------------------------------

def _settings(browser=None, file=None):
    return SimpleNamespace(
        youtube_cookies_from_browser=browser, youtube_cookies_file=file
    )


def test_browser_cookies_take_precedence():
    args = youtube_cookie_args(_settings(browser="chrome", file="/tmp/c.txt"))
    assert args == ["--cookies-from-browser", "chrome"]


def test_cookie_file_fallback():
    args = youtube_cookie_args(_settings(file="/tmp/c.txt"))
    assert args == ["--cookies", "/tmp/c.txt"]


def test_no_cookies_configured():
    assert youtube_cookie_args(_settings()) == []


def test_browser_profile_syntax_passes_through():
    args = youtube_cookie_args(_settings(browser="chrome:Default"))
    assert args == ["--cookies-from-browser", "chrome:Default"]


def test_settings_field_exists_with_default_none():
    from app.config import Settings

    assert Settings.model_fields["youtube_cookies_from_browser"].default is None


def test_youtube_video_downloader_uses_shared_helper():
    from sift_core.platforms import youtube_video

    assert youtube_video.youtube_cookie_args is youtube_cookie_args


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_module_imports():
    """Regression: the CLI previously crashed on import (stale SpaceURLParser)."""
    import sift_core.cli  # noqa: F401


def test_cli_download_rejects_unsupported_url(monkeypatch, capsys):
    import sift_core.cli as cli
    from sift_core.fetch.downloader import DownloaderFactory

    monkeypatch.setattr(
        DownloaderFactory, "detect_platform", staticmethod(lambda url: None)
    )
    args = SimpleNamespace(url="https://not-a-platform.example/x")
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.download_command(args))
    assert exc.value.code == 1
    assert "Unsupported" in capsys.readouterr().err


def test_cli_download_success_path(monkeypatch, capsys, tmp_path):
    import sift_core.cli as cli
    from sift_core.base import Platform as CorePlatform
    from sift_core.fetch.downloader import DownloaderFactory

    monkeypatch.setattr(
        DownloaderFactory,
        "detect_platform",
        staticmethod(lambda url: CorePlatform.YOUTUBE),
    )

    media = tmp_path / "a.m4a"
    media.write_bytes(b"x" * 2048)

    async def fake_download_audio(url, output_path, output_format, quality):
        return SimpleNamespace(
            success=True,
            file_path=media,
            file_size_mb=0.01,
            metadata=SimpleNamespace(duration_seconds=125),
            error=None,
        )

    monkeypatch.setattr(cli, "download_audio", fake_download_audio)

    args = SimpleNamespace(
        url="https://youtu.be/dQw4w9WgXcQ", output=None, format="m4a", quality="high"
    )
    asyncio.run(cli.download_command(args))
    out = capsys.readouterr().out
    assert "Download complete!" in out
    assert "2m 5s" in out
