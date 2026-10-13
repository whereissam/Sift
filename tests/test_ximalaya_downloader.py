"""Unit tests for the Ximalaya (喜马拉雅) downloader URL handling."""

import pytest

from sift_core.base import Platform
from sift_core.fetch.downloader import DownloaderFactory
from sift_core.exceptions import ContentNotFoundError
from sift_core.platforms.ximalaya import XimalayaDownloader


def test_can_handle_any_ximalaya_url():
    assert XimalayaDownloader.can_handle_url("https://www.ximalaya.com/sound/998052123")
    assert XimalayaDownloader.can_handle_url("https://www.ximalaya.com/waiyu/3240558/")
    assert not XimalayaDownloader.can_handle_url("https://www.youtube.com/watch?v=abc")


def test_extract_sound_id_from_episode_url():
    assert (
        XimalayaDownloader.extract_content_id("https://www.ximalaya.com/sound/998052123")
        == "998052123"
    )
    # Category-prefixed sound URLs are also accepted.
    assert (
        XimalayaDownloader.extract_content_id("https://www.ximalaya.com/waiyu/sound/12345")
        == "12345"
    )


def test_album_url_raises_actionable_error():
    with pytest.raises(ContentNotFoundError) as exc:
        XimalayaDownloader.extract_content_id("https://www.ximalaya.com/waiyu/3240558/")
    assert "sound/" in str(exc.value)


def test_factory_detects_and_routes_ximalaya():
    url = "https://www.ximalaya.com/sound/998052123"
    assert DownloaderFactory.detect_platform(url) == Platform.XIMALAYA
    assert isinstance(DownloaderFactory.get_downloader(url), XimalayaDownloader)
    assert isinstance(
        DownloaderFactory.get_downloader_for_platform(Platform.XIMALAYA),
        XimalayaDownloader,
    )
