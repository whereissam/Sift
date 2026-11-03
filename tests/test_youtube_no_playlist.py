"""YouTube adapters never expand a `watch?v=…&list=…` URL into the list.

The adapters accept such URLs and record only the `v=` video, but without
`--no-playlist` yt-dlp downloads every item of the list (a channel's uploads
list is thousands of videos) while the job records the first one.
"""

from __future__ import annotations

import asyncio

import pytest

from sift_core import IngestSettings
from sift_core.platforms import YouTubeDownloader, YouTubeVideoDownloader

LIST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw&list=UUK8sQmJBp8GCxrOtXWBpyEA"


@pytest.fixture
def captured_argv(monkeypatch, tmp_path):
    calls: list[tuple] = []

    class FailedProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"stubbed: no network in tests"

        async def wait(self):
            return 1

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return FailedProcess()

    (tmp_path / "yt-dlp").write_text("")
    monkeypatch.setenv("YT_DLP_PATH", str(tmp_path / "yt-dlp"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


@pytest.mark.parametrize("adapter", [YouTubeDownloader, YouTubeVideoDownloader])
def test_list_urls_are_accepted_as_the_single_video(adapter):
    assert adapter.can_handle_url(LIST_URL)
    assert adapter.extract_content_id(LIST_URL) == "jNQXAC9IVRw"


@pytest.mark.parametrize("adapter", [YouTubeDownloader, YouTubeVideoDownloader])
@pytest.mark.parametrize("call", ["download", "get_metadata"])
def test_yt_dlp_is_told_not_to_expand_the_list(adapter, call, captured_argv, tmp_path):
    downloader = adapter(
        settings=IngestSettings(_env_file=None, download_dir=str(tmp_path / "dl"))
    )
    try:
        asyncio.run(getattr(downloader, call)(LIST_URL))
    except Exception:
        pass  # the stubbed failure surfaces as an error; only the argv matters

    assert captured_argv, f"{adapter.__name__}.{call} never ran yt-dlp"
    for argv in captured_argv:
        assert "--no-playlist" in argv
        assert argv.index("--no-playlist") < argv.index("--")
