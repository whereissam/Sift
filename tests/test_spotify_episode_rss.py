"""Spotify episode RSS resolution: oEmbed → iTunes search → enclosure."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from sift_core.exceptions import ContentNotFoundError
from sift_core.platforms import spotify as spotify_mod
from sift_core.platforms.spotify import (
    ResolvedEpisode,
    SpotifyDownloader,
    _pick_itunes_episode,
    _sanitize_filename,
    resolve_episode_via_rss,
)

TITLE = "E82｜聊聊超豪华联盟稳定币OUSD"


# ---------------------------------------------------------------------------
# Result picking
# ---------------------------------------------------------------------------

def test_pick_prefers_exact_title_match():
    results = [
        {"trackName": "Other episode", "episodeUrl": "https://a/x.mp3"},
        {"trackName": TITLE, "episodeUrl": "https://a/right.mp3"},
    ]
    assert _pick_itunes_episode(results, TITLE)["episodeUrl"] == "https://a/right.mp3"


def test_pick_accepts_truncated_itunes_title():
    # iTunes truncates long titles; prefix matching must still hit.
    results = [{"trackName": TITLE[:12], "episodeUrl": "https://a/t.mp3"}]
    assert _pick_itunes_episode(results, TITLE)["episodeUrl"] == "https://a/t.mp3"


def test_pick_skips_results_without_enclosure():
    results = [
        {"trackName": TITLE},  # no episodeUrl
        {"trackName": "loose match", "episodeUrl": "https://a/fallback.mp3"},
    ]
    assert _pick_itunes_episode(results, TITLE)["episodeUrl"] == "https://a/fallback.mp3"
    assert _pick_itunes_episode([{"trackName": TITLE}], TITLE) is None


def test_sanitize_filename():
    assert _sanitize_filename('a/b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    assert len(_sanitize_filename("x" * 500)) <= 150


# ---------------------------------------------------------------------------
# Resolution (network mocked via safe_get)
# ---------------------------------------------------------------------------

def _fake_safe_get(responses):
    """Return an async safe_get returning canned responses per URL."""

    async def fake(url, **kwargs):
        status, payload = responses[url]
        return SimpleNamespace(status_code=status, json=lambda: payload)

    return fake


def test_resolve_episode_happy_path(monkeypatch):
    monkeypatch.setattr(
        spotify_mod,
        "safe_get",
        _fake_safe_get({
            spotify_mod.SPOTIFY_OEMBED_URL: (200, {"title": TITLE}),
            spotify_mod.ITUNES_SEARCH_URL: (
                200,
                {
                    "results": [
                        {
                            "trackName": TITLE,
                            "collectionName": "Web3 101",
                            "episodeUrl": "https://feed/ep.mp3",
                            "trackTimeMillis": 4237000,
                        }
                    ]
                },
            ),
        }),
    )
    ep = asyncio.run(resolve_episode_via_rss("https://open.spotify.com/episode/abc"))
    assert ep.mp3_url == "https://feed/ep.mp3"
    assert ep.show == "Web3 101"
    assert ep.duration_seconds == 4237.0


def test_resolve_episode_not_syndicated(monkeypatch):
    monkeypatch.setattr(
        spotify_mod,
        "safe_get",
        _fake_safe_get({
            spotify_mod.SPOTIFY_OEMBED_URL: (200, {"title": TITLE}),
            spotify_mod.ITUNES_SEARCH_URL: (200, {"results": []}),
        }),
    )
    with pytest.raises(ContentNotFoundError, match="Spotify-exclusive"):
        asyncio.run(resolve_episode_via_rss("https://open.spotify.com/episode/abc"))


def test_resolve_episode_unknown_url(monkeypatch):
    monkeypatch.setattr(
        spotify_mod,
        "safe_get",
        _fake_safe_get({spotify_mod.SPOTIFY_OEMBED_URL: (404, {})}),
    )
    with pytest.raises(ContentNotFoundError):
        asyncio.run(resolve_episode_via_rss("https://open.spotify.com/episode/nope"))


# ---------------------------------------------------------------------------
# Downloader routing
# ---------------------------------------------------------------------------

class _FakeStreamResponse:
    status_code = 200

    def __init__(self, payload: bytes):
        self._payload = payload

    async def aiter_bytes(self, _chunk_size):
        yield self._payload


class _FakeSafeStream:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.requested_url = None

    def __call__(self, url, **kwargs):
        self.requested_url = url
        payload = self._payload

        class _Ctx:
            async def __aenter__(self):
                return _FakeStreamResponse(payload)

            async def __aexit__(self, *args):
                return False

        return _Ctx()


def test_download_episode_via_rss(tmp_path, monkeypatch):
    async def fake_resolve(url):
        return ResolvedEpisode(
            title=TITLE, show="Web3 101", mp3_url="https://feed/ep.mp3",
            duration_seconds=4237.0,
        )

    stream = _FakeSafeStream(b"ID3" + b"\x00" * 4096)
    monkeypatch.setattr(spotify_mod, "resolve_episode_via_rss", fake_resolve)
    monkeypatch.setattr(spotify_mod, "safe_stream", stream)

    dl = SpotifyDownloader(download_dir=tmp_path)
    result = asyncio.run(
        dl.download("https://open.spotify.com/episode/3FErc0AYpIO97DdOmMlCjw")
    )

    assert result.success, result.error
    assert stream.requested_url == "https://feed/ep.mp3"
    assert Path(result.file_path).exists()
    assert Path(result.file_path).suffix == ".mp3"
    assert "Web3 101" in Path(result.file_path).name
    assert result.metadata.show_name == "Web3 101"
    assert result.metadata.duration_seconds == 4237.0
    assert result.metadata.content_id == "3FErc0AYpIO97DdOmMlCjw"


def test_music_without_spotdl_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(spotify_mod.shutil, "which", lambda name: None)
    dl = SpotifyDownloader(download_dir=tmp_path)
    result = asyncio.run(
        dl.download("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
    )
    assert result.success is False
    assert "spotDL" in result.error


def test_availability_no_longer_requires_spotdl(monkeypatch):
    monkeypatch.setattr(spotify_mod.shutil, "which", lambda name: None)
    assert SpotifyDownloader.is_available() is True
