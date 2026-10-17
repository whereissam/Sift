"""Live link checks: real network, real platforms, the real yt-dlp.

Skipped unless ``SIFT_LIVE=1``. Run locally with ``make check-links``; CI runs
them daily against both the pinned and the newest yt-dlp
(.github/workflows/live-links.yml).

Reading a failure:
- fails on pinned, passes on latest  -> the site changed and yt-dlp already
  caught up: ``uv lock --upgrade-package yt-dlp``
- fails on both                      -> the adapter itself needs a fix
- passes on pinned, fails on latest  -> a yt-dlp regression; hold the pin
"""

import asyncio
import json
import os
import shutil
import subprocess

import pytest

from sift_core import DownloaderFactory, IngestSettings

from .canaries import CANARIES, Canary

pytestmark = pytest.mark.skipif(
    os.environ.get("SIFT_LIVE") != "1",
    reason="live link check; set SIFT_LIVE=1 to run",
)

METADATA_TIMEOUT = 120
DOWNLOAD_TIMEOUT = 600
# Smaller than any real 19-second clip; catches HTML error pages saved as media.
MIN_FILE_BYTES = 20_000


def _require_url(canary: Canary) -> str:
    reason = canary.skip_reason()
    if reason:
        pytest.skip(reason)
    return canary.resolved_url


def _downloader(canary: Canary, tmp_path):
    settings = IngestSettings(download_dir=str(tmp_path))
    downloader = DownloaderFactory.get_downloader_for_platform(canary.platform, settings=settings)
    if not downloader.is_available():
        pytest.skip(f"{canary.platform.value} dependencies are not installed")
    return downloader


def _stream_types(path) -> set[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return {s.get("codec_type") for s in json.loads(out).get("streams", [])}


@pytest.mark.parametrize("canary", CANARIES, ids=lambda c: c.platform.value)
async def test_metadata(canary: Canary, tmp_path):
    url = _require_url(canary)
    downloader = _downloader(canary, tmp_path)

    metadata = await asyncio.wait_for(downloader.get_metadata(url), METADATA_TIMEOUT)

    assert metadata is not None, (
        f"{canary.platform.value} returned no metadata for {url}. "
        f"Run `uv run sift -v download {url}` to see the underlying error."
    )
    assert metadata.title, f"{canary.platform.value} metadata has no title: {metadata}"


@pytest.mark.parametrize(
    "canary",
    [c for c in CANARIES if c.download or os.environ.get("SIFT_LIVE_DOWNLOAD") == "all"],
    ids=lambda c: c.platform.value,
)
async def test_download(canary: Canary, tmp_path):
    url = _require_url(canary)
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed; downloads need it to remux")
    downloader = _downloader(canary, tmp_path)

    if canary.is_video:
        result = await asyncio.wait_for(downloader.download(url), DOWNLOAD_TIMEOUT)
    else:
        result = await asyncio.wait_for(
            downloader.download(url, output_format="mp3", quality="low"), DOWNLOAD_TIMEOUT
        )

    assert result.success, f"{canary.platform.value} download failed: {result.error}"
    assert result.file_path and result.file_path.exists(), f"no file on disk: {result.file_path}"
    size = result.file_path.stat().st_size
    assert size >= MIN_FILE_BYTES, f"{result.file_path.name} is only {size} bytes"

    if shutil.which("ffprobe"):
        streams = _stream_types(result.file_path)
        assert "audio" in streams, f"{result.file_path.name} has no audio stream: {streams}"
        if canary.is_video:
            assert "video" in streams, f"{result.file_path.name} has no video stream: {streams}"
