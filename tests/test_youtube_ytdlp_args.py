"""yt-dlp arguments for YouTube that decide whether a download works at all.

Regression tests: forcing `player_client=web` made every YouTube download
fail ("No video formats found"); mp4 downloads picked AV1/VP9 + Opus,
which many players cannot open; and an mp3 download returned an earlier
.m4a of the same video.
"""

import json

import pytest

from sift_core.platforms import YouTubeDownloader, YouTubeVideoDownloader
from sift_core.platforms import youtube, youtube_video

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class _Process:
    def __init__(self, returncode=1, stdout=b""):
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b"ERROR: offline"


def _record(monkeypatch, module, process=None):
    argvs = []

    async def fake_exec(*argv, **kwargs):
        argvs.append(list(argv))
        return process or _Process()

    monkeypatch.setattr(module, "resolve_yt_dlp", lambda: "yt-dlp")
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    return argvs


@pytest.mark.parametrize(
    "cls,module", [(YouTubeDownloader, youtube), (YouTubeVideoDownloader, youtube_video)]
)
async def test_player_client_is_left_to_ytdlp(monkeypatch, tmp_path, cls, module):
    argvs = _record(monkeypatch, module)
    await cls(download_dir=tmp_path).download(URL)
    (argv,) = argvs
    assert not any(a.startswith("youtube:player_client") for a in argv)


@pytest.mark.parametrize("quality,height", [("low", 360), ("high", 720), ("highest", 1080)])
async def test_mp4_prefers_h264_and_aac(monkeypatch, tmp_path, quality, height):
    argvs = _record(monkeypatch, youtube_video)
    await YouTubeVideoDownloader(download_dir=tmp_path).download(URL, quality=quality)
    argv = argvs[0]
    spec = argv[argv.index("-f") + 1]
    first, *fallbacks = spec.split("/")
    assert first == f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[ext=m4a]"
    assert f"bestvideo[height<={height}]+bestaudio" in fallbacks


async def test_mp3_download_returns_the_mp3_not_an_older_m4a(monkeypatch, tmp_path):
    (tmp_path / "Song [dQw4w9WgXcQ].m4a").write_bytes(b"old")
    (tmp_path / "Song [dQw4w9WgXcQ].mp3").write_bytes(b"new")
    # --print-json reports the pre-extraction name, which no longer exists.
    info = {"id": "dQw4w9WgXcQ", "title": "Song", "_filename": str(tmp_path / "Song.webm")}
    _record(monkeypatch, youtube, _Process(0, json.dumps(info).encode()))
    result = await YouTubeDownloader(download_dir=tmp_path).download(URL, output_format="mp3")
    assert result.success
    assert result.file_path.suffix == ".mp3"
