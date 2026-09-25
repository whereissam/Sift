"""Tests for the yt-dlp Twitter/X cookie helper used by X video downloads."""

import os

from app.ingest.fetch import auth
from app.ingest.fetch.auth import _netscape_cookie_content, twitter_ytdlp_cookies


class _FakeSettings:
    def __init__(self, auth_token="", ct0="", cookie_file=None):
        self.twitter_auth_token = auth_token
        self.twitter_ct0 = ct0
        self.twitter_cookie_file = cookie_file


def test_netscape_content_has_both_domains_and_values():
    body = _netscape_cookie_content("AUTHVAL", "CT0VAL")
    assert body.startswith("# Netscape HTTP Cookie File")
    for domain in (".x.com", ".twitter.com"):
        assert f"{domain}\tTRUE\t/\tTRUE" in body
    assert "auth_token\tAUTHVAL" in body
    assert "ct0\tCT0VAL" in body


def test_yields_none_without_auth(monkeypatch):
    monkeypatch.setattr(auth, "get_ingest_settings", lambda: _FakeSettings())
    with twitter_ytdlp_cookies() as path:
        assert path is None


def test_prefers_explicit_cookie_file(monkeypatch):
    monkeypatch.setattr(
        auth, "get_ingest_settings", lambda: _FakeSettings(cookie_file="/tmp/my-cookies.txt")
    )
    with twitter_ytdlp_cookies() as path:
        assert path == "/tmp/my-cookies.txt"


def test_writes_temp_file_from_tokens_and_cleans_up(monkeypatch):
    monkeypatch.setattr(
        auth, "get_ingest_settings", lambda: _FakeSettings(auth_token="A", ct0="C")
    )
    seen = None
    with twitter_ytdlp_cookies() as path:
        seen = path
        assert path is not None
        assert os.path.exists(path)
        content = open(path).read()
        assert "auth_token\tA" in content and "ct0\tC" in content
    # File removed on exit.
    assert not os.path.exists(seen)
