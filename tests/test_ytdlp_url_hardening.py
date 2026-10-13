"""Caller-supplied URLs must not reach yt-dlp as options or off-platform hosts.

Regression tests for the security audit: platform detection used to match a
platform domain anywhere in the string, and every adapter appended the URL to
the yt-dlp argv with no "--", so an option-shaped "URL" was parsed as a
yt-dlp option and a foreign host with a platform-looking path was fetched.
"""

import asyncio
import gzip

import httpx
import pytest

from sift_core.base import Platform, url_host_matches
from sift_core.fetch import url_validator
from sift_core.fetch.downloader import DownloaderFactory
from sift_core.fetch.url_validator import ResponseTooLargeError, safe_get
from sift_core.platforms import (
    InstagramVideoDownloader,
    XiaohongshuVideoDownloader,
    XimalayaDownloader,
    XSpacesDownloader,
    XVideoDownloader,
    YouTubeDownloader,
    YouTubeVideoDownloader,
)


class TestUrlHostMatches:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube.com/watch?v=dQw4w9WgXcQ",  # schemeless is read as https
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
        ],
    )
    def test_accepts_platform_hosts(self, url):
        assert url_host_matches(url, ("youtube.com", "youtu.be"))

    @pytest.mark.parametrize(
        "url",
        [
            "--config-location=/tmp/x/youtube.com/watch?v=dQw4w9WgXcQ",
            "-oexec:x/youtube.com/watch?v=dQw4w9WgXcQ",
            "http://127.0.0.1:8080/youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
            "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com@evil.example/watch?v=dQw4w9WgXcQ",
            "https://evil.example\\@www.youtube.com/watch?v=dQw4w9WgXcQ",
            "file:///youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ --exec x",
            "",
        ],
    )
    def test_rejects_everything_else(self, url):
        assert not url_host_matches(url, ("youtube.com", "youtu.be"))


class TestPlatformDetection:
    @pytest.mark.parametrize(
        "url",
        [
            "--config-location=/scratch/att/ximalaya.com/sound/9",
            "--config-location=/scratch/att/xiaohongshu.com",
            "-oexec:x/xiaohongshu.com/discovery/item/abcdefghij0123456789",
            "http://127.0.0.1:18080/youtube.com/watch?v=aaaaaaaaaaa",
            "https://attacker.example/cdn.discordapp.com/attachments/1/2/a.mp3",
            "https://attacker.example/x.com/i/spaces/1abcdefghij",
            "https://attacker.example/open.spotify.com/episode/abc",
            "https://attacker.example/podcasts.apple.com/us/podcast/x/id1",
        ],
    )
    def test_foreign_or_option_shaped_input_is_unsupported(self, url):
        assert DownloaderFactory.detect_platform(url) is None

    @pytest.mark.parametrize(
        "url,platform",
        [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", Platform.YOUTUBE),
            ("https://x.com/i/spaces/1abcdefghij", Platform.X_SPACES),
            ("https://www.ximalaya.com/sound/998052123", Platform.XIMALAYA),
            ("https://cdn.discordapp.com/attachments/1/2/a.mp3", Platform.DISCORD),
            ("https://open.spotify.com/episode/abc123", Platform.SPOTIFY),
            ("https://www.xiaohongshu.com/explore/abcdef0123456789", Platform.XIAOHONGSHU),
        ],
    )
    def test_real_platform_urls_still_route(self, url, platform):
        assert DownloaderFactory.detect_platform(url) == platform


class _FakeProcess:
    returncode = 1

    async def communicate(self):
        return b"", b"ERROR: offline"


@pytest.mark.parametrize(
    "cls,module,url,call",
    [
        (YouTubeDownloader, "youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "download"),
        (YouTubeDownloader, "youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "get_metadata"),
        (YouTubeVideoDownloader, "youtube_video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "download"),
        (YouTubeVideoDownloader, "youtube_video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "get_metadata"),
        (XSpacesDownloader, "xspaces", "https://x.com/i/spaces/1abcdefghij", "download"),
        (XSpacesDownloader, "xspaces", "https://x.com/i/spaces/1abcdefghij", "get_metadata"),
        (XimalayaDownloader, "ximalaya", "https://www.ximalaya.com/sound/9", "download"),
        (XimalayaDownloader, "ximalaya", "https://www.ximalaya.com/sound/9", "get_metadata"),
        (InstagramVideoDownloader, "instagram_video", "https://www.instagram.com/reel/abc123", "download"),
        (InstagramVideoDownloader, "instagram_video", "https://www.instagram.com/reel/abc123", "get_metadata"),
        (XiaohongshuVideoDownloader, "xiaohongshu_video", "https://www.xiaohongshu.com/explore/abcdef0123456789", "download"),
        (XiaohongshuVideoDownloader, "xiaohongshu_video", "https://www.xiaohongshu.com/explore/abcdef0123456789", "get_metadata"),
        (XVideoDownloader, "x_video", "https://x.com/someone/status/123", "download"),
        (XVideoDownloader, "x_video", "https://x.com/someone/status/123", "get_metadata"),
    ],
)
async def test_url_follows_end_of_options_marker(monkeypatch, tmp_path, cls, module, url, call):
    argvs = []

    async def fake_exec(*argv, **kwargs):
        argvs.append(list(argv))
        return _FakeProcess()

    mod = __import__(f"sift_core.platforms.{module}", fromlist=["x"])
    monkeypatch.setattr(mod, "resolve_yt_dlp", lambda: "yt-dlp", raising=False)
    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

    downloader = cls(download_dir=tmp_path)
    if call == "download":
        await downloader.download(url)
    else:
        await downloader.get_metadata(url)

    assert argvs, "yt-dlp was not invoked"
    for argv in argvs:
        assert argv[-2:] == ["--", url]


class TestSafeGetByteCap:
    @pytest.fixture(autouse=True)
    def _public_dns(self, monkeypatch):
        monkeypatch.setattr(url_validator, "validate_url_ssrf", lambda url: (True, None))

    @staticmethod
    def _client(body: bytes, headers: dict) -> dict:
        def handler(request):
            return httpx.Response(200, content=body, headers=headers)

        return {"transport": httpx.MockTransport(handler)}

    async def test_gzip_bomb_is_rejected_after_decoding(self):
        bomb = gzip.compress(b"\0" * (4 * 1024 * 1024))
        assert len(bomb) < 64 * 1024
        with pytest.raises(ResponseTooLargeError):
            await safe_get(
                "https://feeds.example.org/feed.xml",
                client_kwargs=self._client(bomb, {"content-encoding": "gzip"}),
                max_bytes=1024 * 1024,
            )

    async def test_small_gzip_body_is_decoded_once(self):
        body = b"<rss>hello</rss>"
        resp = await safe_get(
            "https://feeds.example.org/feed.xml",
            client_kwargs=self._client(gzip.compress(body), {"content-encoding": "gzip"}),
        )
        assert resp.status_code == 200
        assert resp.content == body
        assert resp.text == body.decode()

    async def test_declared_length_over_cap_fails_early(self):
        with pytest.raises(ResponseTooLargeError):
            await safe_get(
                "https://feeds.example.org/feed.xml",
                client_kwargs=self._client(b"x" * 2048, {}),
                max_bytes=1024,
            )
