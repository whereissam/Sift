"""Auth must reach the metadata path, and a stale session must not be fatal.

Two bugs sat behind these tests. Every adapter that needs cookies passed them
only when *downloading*, so `get_metadata` failed on exactly the content the
cookies exist for. And on X, passing an expired cookie made yt-dlp fail on
public posts that work fine anonymously — auth was worse than no auth.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sift_core.platforms.instagram_video import (
    InstagramVideoDownloader,
    instagram_cookie_args,
)
from sift_core.platforms.x_video import _is_auth_rejection, _run_ytdlp
from sift_core.platforms.youtube import youtube_cookie_args


# ---------------------------------------------------------------- cookie args


def _settings(**kwargs):
    base = dict(
        instagram_cookies_from_browser=None,
        instagram_cookies_file=None,
        youtube_cookies_from_browser=None,
        youtube_cookies_file=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "args_fn, browser_key, file_key",
    [
        (instagram_cookie_args, "instagram_cookies_from_browser", "instagram_cookies_file"),
        (youtube_cookie_args, "youtube_cookies_from_browser", "youtube_cookies_file"),
    ],
)
def test_browser_cookies_win_over_an_exported_file(args_fn, browser_key, file_key):
    """Browser cookies stay fresh; an exported file goes stale silently."""
    s = _settings(**{browser_key: "chrome", file_key: "/tmp/cookies.txt"})
    assert args_fn(s) == ["--cookies-from-browser", "chrome"]


@pytest.mark.parametrize(
    "args_fn, file_key",
    [
        (instagram_cookie_args, "instagram_cookies_file"),
        (youtube_cookie_args, "youtube_cookies_file"),
    ],
)
def test_falls_back_to_the_cookies_file(args_fn, file_key):
    assert args_fn(_settings(**{file_key: "/tmp/cookies.txt"})) == [
        "--cookies",
        "/tmp/cookies.txt",
    ]


@pytest.mark.parametrize("args_fn", [instagram_cookie_args, youtube_cookie_args])
def test_no_flags_when_nothing_configured(args_fn):
    assert args_fn(_settings()) == []


# ------------------------------------------------- metadata carries the flags


async def test_instagram_metadata_passes_cookies(monkeypatch):
    """The regression: metadata built its command without any cookie flag, so
    Instagram — which requires a session for almost everything — always
    returned None even with cookies configured."""
    seen: list[list[str]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b'{"id": "abc", "title": "t"}', b""

    async def fake_exec(*cmd, **kwargs):
        seen.append(list(cmd))
        return FakeProcess()

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_exec
    )
    downloader = InstagramVideoDownloader()
    monkeypatch.setattr(downloader, "_yt_dlp_path", "yt-dlp")
    monkeypatch.setattr(
        downloader, "settings", _settings(instagram_cookies_file="/tmp/ig.txt")
    )

    await downloader.get_metadata("https://www.instagram.com/reel/ABC123/")

    assert seen, "yt-dlp was never invoked"
    assert "--cookies" in seen[0]
    assert "/tmp/ig.txt" in seen[0]


# ------------------------------------------------------- X auth-rejection path


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: [twitter] Error(s) while querying API: Could not authenticate you",
        "ERROR: 401 Unauthorized",
        "ERROR: Missing or invalid csrf token",
        "you appear to be logged out",
    ],
)
def test_recognizes_a_rejected_session(stderr):
    assert _is_auth_rejection(stderr)


def test_does_not_mistake_a_missing_post_for_bad_auth():
    """A 404 must not trigger a pointless anonymous retry."""
    assert not _is_auth_rejection("ERROR: [twitter] 123: No video could be found")


async def test_x_retries_anonymously_when_cookies_are_rejected(monkeypatch):
    """An expired X session made public posts fail — yt-dlp treats a rejected
    cookie as fatal rather than falling back."""
    calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self, returncode, stderr):
            self.returncode = returncode
            self._stderr = stderr

        async def communicate(self):
            return b'{"ok": true}', self._stderr

    async def fake_exec(*cmd, **kwargs):
        calls.append(list(cmd))
        if "--cookies" in cmd:
            return FakeProcess(1, b"ERROR: Could not authenticate you")
        return FakeProcess(0, b"")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        "sift_core.platforms.x_video.twitter_ytdlp_cookies",
        lambda settings=None: _fake_cookie_ctx("/tmp/x.txt"),
    )

    returncode, _stdout, _stderr = await _run_ytdlp(["yt-dlp", "--print-json"], "https://x.com/a/status/1")

    assert returncode == 0
    assert len(calls) == 2, "expected an authenticated attempt then an anonymous retry"
    assert "--cookies" in calls[0]
    assert "--cookies" not in calls[1]


async def test_x_does_not_retry_when_the_failure_is_not_about_auth(monkeypatch):
    calls: list[list[str]] = []

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"ERROR: [twitter] 123: No video could be found"

    async def fake_exec(*cmd, **kwargs):
        calls.append(list(cmd))
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        "sift_core.platforms.x_video.twitter_ytdlp_cookies",
        lambda settings=None: _fake_cookie_ctx("/tmp/x.txt"),
    )

    returncode, _stdout, _stderr = await _run_ytdlp(["yt-dlp"], "https://x.com/a/status/1")

    assert returncode == 1
    assert len(calls) == 1, "a 404 should not trigger a retry"


async def test_x_makes_one_call_when_no_cookies_are_configured(monkeypatch):
    calls: list[list[str]] = []

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"ERROR: Could not authenticate you"

    async def fake_exec(*cmd, **kwargs):
        calls.append(list(cmd))
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        "sift_core.platforms.x_video.twitter_ytdlp_cookies", lambda settings=None: _fake_cookie_ctx(None)
    )

    await _run_ytdlp(["yt-dlp"], "https://x.com/a/status/1")

    assert len(calls) == 1, "nothing to fall back from when there were no cookies"


class _fake_cookie_ctx:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------- yt-dlp resolution


def test_yt_dlp_path_override_wins(monkeypatch, tmp_path):
    """Packaged builds ship their own binary and must be able to name it."""
    from sift_core.base import resolve_yt_dlp

    binary = tmp_path / "yt-dlp"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("YT_DLP_PATH", str(binary))
    assert resolve_yt_dlp() == str(binary)


def test_a_bogus_override_fails_loudly(monkeypatch, tmp_path):
    from sift_core.base import resolve_yt_dlp
    from sift_core.exceptions import ToolNotFoundError

    monkeypatch.setenv("YT_DLP_PATH", str(tmp_path / "nope"))
    with pytest.raises(ToolNotFoundError):
        resolve_yt_dlp()


def test_pinned_build_is_preferred_over_a_system_install(monkeypatch, tmp_path):
    """The regression this guards: adapters resolved from PATH, so a stale
    system yt-dlp shadowed the version pinned in pyproject.toml whenever the
    app was started outside `uv run`."""
    from sift_core import base

    monkeypatch.delenv("YT_DLP_PATH", raising=False)
    env_bin = tmp_path / "bin"
    env_bin.mkdir()
    (env_bin / "python").write_text("")
    (env_bin / "yt-dlp").write_text("")
    monkeypatch.setattr(base.sys, "executable", str(env_bin / "python"))
    monkeypatch.setattr(base.shutil, "which", lambda _: "/usr/local/bin/yt-dlp")

    assert base.resolve_yt_dlp() == str(env_bin / "yt-dlp")


def test_falls_back_to_path_when_no_pinned_build_exists(monkeypatch, tmp_path):
    from sift_core import base

    monkeypatch.delenv("YT_DLP_PATH", raising=False)
    monkeypatch.setattr(base.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(base.shutil, "which", lambda _: "/opt/homebrew/bin/yt-dlp")

    assert base.resolve_yt_dlp() == "/opt/homebrew/bin/yt-dlp"


def test_availability_agrees_with_resolution(monkeypatch, tmp_path):
    """is_available() used to check PATH directly, so it reported 'missing' on
    a normal `uv sync` layout where only the pinned build exists."""
    from sift_core import base

    monkeypatch.delenv("YT_DLP_PATH", raising=False)
    monkeypatch.setattr(base.sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(base.shutil, "which", lambda _: None)
    assert base.yt_dlp_available() is False

    monkeypatch.setattr(base.shutil, "which", lambda _: "/usr/bin/yt-dlp")
    assert base.yt_dlp_available() is True
