"""`app.ingest.platforms.DOWNLOADERS` is the one list of adapters.

The factory used to hardcode the classes twice (a detection list and a
Platform→class mapping) that could drift apart. These tests pin the invariants
the single list has to keep.
"""

from __future__ import annotations

import pytest

import app.ingest.platforms as platforms
from app.ingest import Platform, PlatformDownloader, UnsupportedPlatformError
from app.ingest.fetch.downloader import DownloaderFactory
from app.ingest.platforms import DOWNLOADERS


def test_every_platform_has_exactly_one_adapter():
    declared = [cls.PLATFORM for cls in DOWNLOADERS]
    assert sorted(declared, key=lambda p: p.value) == sorted(Platform, key=lambda p: p.value)


def test_no_adapter_is_left_out_of_the_list():
    """Writing an adapter but forgetting to list it would make it unreachable."""
    defined = {
        cls
        for cls in PlatformDownloader.__subclasses__()
        if cls.__module__.startswith(platforms.__name__ + ".")
    }
    assert defined == set(DOWNLOADERS)


@pytest.mark.parametrize("cls", DOWNLOADERS, ids=lambda c: c.__name__)
def test_platform_property_reports_the_declared_platform(cls):
    # __new__ skips __init__, which may need external tools (spotdl, yt-dlp).
    assert cls.__new__(cls).platform is cls.PLATFORM


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Overlapping hosts: order in DOWNLOADERS decides these.
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", Platform.YOUTUBE),
        ("https://x.com/i/spaces/1vOxwdyYrlqKB", Platform.X_SPACES),
        ("https://x.com/someone/status/1234567890", Platform.X_VIDEO),
        ("https://podcasts.apple.com/us/podcast/x/id1434243584", Platform.APPLE_PODCASTS),
        ("https://www.ximalaya.com/sound/123456", Platform.XIMALAYA),
        ("https://example.com/not-media", None),
    ],
)
def test_detection_order(url, expected):
    assert DownloaderFactory.detect_platform(url) == expected
    assert DownloaderFactory.is_url_supported(url) is (expected is not None)


def test_lookup_by_platform_uses_the_same_list(monkeypatch):
    built = []

    def fake_init(self, download_dir=None, settings=None):
        built.append((type(self), settings))

    for cls in DOWNLOADERS:
        monkeypatch.setattr(cls, "__init__", fake_init)

    for cls in DOWNLOADERS:
        downloader = DownloaderFactory.get_downloader_for_platform(cls.PLATFORM, settings="S")
        assert type(downloader) is cls
    assert built == [(cls, "S") for cls in DOWNLOADERS]


def test_lookup_of_an_unknown_platform_raises():
    with pytest.raises(UnsupportedPlatformError):
        DownloaderFactory.get_downloader_for_platform("not-a-platform")


def test_unsupported_url_raises():
    with pytest.raises(UnsupportedPlatformError):
        DownloaderFactory.get_downloader("https://example.com/not-media")


def test_available_platforms_follow_is_available(monkeypatch):
    unavailable = {DOWNLOADERS[0], DOWNLOADERS[3]}
    for cls in DOWNLOADERS:
        monkeypatch.setattr(
            cls, "is_available", classmethod(lambda c, _off=cls in unavailable: not _off)
        )
    assert DownloaderFactory.get_available_platforms() == [
        cls.PLATFORM for cls in DOWNLOADERS if cls not in unavailable
    ]
