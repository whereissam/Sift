"""Conversion decisions follow the audio's real format, not its file name.

Regression for `sift download -o episode.m4a <apple podcasts url>` saving MP3
bytes under a `.m4a` name: the adapters and `AudioConverter.convert` compared
file *extensions* (the `-o` name, or one guessed from the audio URL) and
skipped conversion whenever they matched, without looking at the bytes.

Uses real ffmpeg/ffprobe on 1-second generated tones; the adapter tests stub
only the network calls, so the real download → convert path runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from sift_core import IngestSettings
from sift_core.media import converter as converter_module
from sift_core.media.converter import AudioConverter
from sift_core.platforms import discord_audio
from sift_core.platforms.apple_podcasts import ApplePodcastsDownloader
from sift_core.platforms.discord_audio import DiscordAudioDownloader
from sift_core.platforms.xiaoyuzhou import XiaoyuzhouDownloader

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs ffmpeg and ffprobe",
)

# What ffprobe reports for a correctly-made file of each target format.
EXPECTED = {"m4a": ("mp4", "aac"), "mp3": ("mp3", "mp3")}


def probe(path: Path) -> tuple[str, str]:
    """(container, audio codec) as ffprobe sees the bytes."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "format=format_name:stream=codec_name", "-of", "json",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    names = set(data["format"]["format_name"].split(","))
    container = "mp4" if "mp4" in names else data["format"]["format_name"]
    return container, data["streams"][0]["codec_name"]


def make_tone(path: Path, codec: str, *extra: str) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1", *extra, "-c:a", codec, str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def sources(tmp_path_factory) -> dict[str, Path]:
    """Real bytes as a feed would serve them."""
    d = tmp_path_factory.mktemp("src")
    return {
        "mp3": make_tone(d / "src.mp3", "libmp3lame"),
        "m4a": make_tone(d / "src.m4a", "aac"),
    }


# ─── AudioConverter ───


@pytest.mark.parametrize(
    ("source", "misnamed_as", "target"),
    [("mp3", "m4a", "m4a"), ("m4a", "mp3", "mp3")],
)
async def test_convert_in_place_when_the_name_lies(tmp_path, sources, source, misnamed_as, target):
    """The original bug: bytes of one format under the target's extension."""
    path = tmp_path / f"episode.{misnamed_as}"
    shutil.copy(sources[source], path)

    out = await AudioConverter().convert(path, output_path=path, output_format=target)

    assert out == path
    assert probe(out) == EXPECTED[target]
    assert not list(tmp_path.glob("*.converting*")), "temp file left behind"


async def test_matching_audio_is_not_re_encoded(tmp_path, sources):
    path = tmp_path / "episode.mp3"
    shutil.copy(sources["mp3"], path)
    before = path.read_bytes()

    out = await AudioConverter().convert(path, output_format="mp3", quality="low")

    assert out == path
    assert path.read_bytes() == before


async def test_matching_audio_under_the_wrong_name_is_moved_not_encoded(tmp_path, sources):
    """Right bytes, wrong extension: rename, don't transcode (no quality loss)."""
    src = tmp_path / "download.mp3"
    shutil.copy(sources["m4a"], src)
    before = src.read_bytes()

    out = await AudioConverter().convert(src, output_format="m4a", keep_original=False)

    assert out == tmp_path / "download.m4a"
    assert out.read_bytes() == before
    assert not src.exists()


async def test_matching_audio_to_a_new_path_keeps_the_original(tmp_path, sources):
    src = tmp_path / "a.mp3"
    shutil.copy(sources["mp3"], src)
    dest = tmp_path / "b.mp3"

    out = await AudioConverter().convert(src, output_path=dest, output_format="mp3")

    assert out == dest and dest.read_bytes() == src.read_bytes()


async def test_mp4_video_is_never_stripped_to_audio(tmp_path):
    """mp4 matches on container alone, so a video's picture survives even
    when its audio codec isn't AAC."""
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
            "-f", "lavfi", "-i", "sine=duration=1",
            "-c:v", "mpeg4", "-c:a", "libmp3lame", "-shortest", str(video),
        ],
        check=True,
    )
    before = video.read_bytes()

    out = await AudioConverter().convert(video, output_format="mp4")

    assert out == video and video.read_bytes() == before


async def test_without_ffprobe_the_extension_rule_still_applies(tmp_path, sources, monkeypatch):
    real_which = shutil.which
    monkeypatch.setattr(
        converter_module.shutil, "which", lambda name: None if name == "ffprobe" else real_which(name)
    )
    path = tmp_path / "episode.mp3"
    shutil.copy(sources["mp3"], path)
    before = path.read_bytes()

    out = await AudioConverter().convert(path, output_format="mp3")

    assert out == path and path.read_bytes() == before


# ─── adapters: the reported symptom, end to end minus the network ───


def _stub_apple(d: ApplePodcastsDownloader, source: Path, audio_url: str):
    async def info(podcast_id):
        return {"feedUrl": "https://feed.example/rss", "collectionName": "Show"}

    async def feed(url):
        return SimpleNamespace(entries=[{"title": "Ep"}], feed={"title": "Show"})

    async def find(feed, podcast_id, episode_id):
        return {"title": "Ep"}

    async def download_file(url, path):
        shutil.copy(source, path)

    d._get_podcast_info, d._get_rss_feed, d._find_episode = info, feed, find
    d._download_file = download_file
    d._get_audio_url = lambda entry: audio_url


def _stub_xiaoyuzhou(d: XiaoyuzhouDownloader, source: Path, audio_url: str):
    async def episode(eid):
        return {"title": "Ep", "enclosure": {"url": audio_url}, "podcast": {"title": "Show"}}

    async def download_file(url, path):
        shutil.copy(source, path)

    d._get_episode_info = episode
    d._download_file = download_file


ADAPTERS = {
    "apple": (
        ApplePodcastsDownloader,
        _stub_apple,
        "https://podcasts.apple.com/us/podcast/x/id1434243584?i=1000",
    ),
    "xiaoyuzhou": (
        XiaoyuzhouDownloader,
        _stub_xiaoyuzhou,
        "https://www.xiaoyuzhoufm.com/episode/6500000000000000000000aa",
    ),
}

CASES = [
    # (source bytes, -o name or None, -f)
    ("mp3", "ep.m4a", "m4a"),  # the reported bug
    ("m4a", "ep.mp3", "mp3"),  # its mirror
    ("m4a", None, "mp3"),      # URL-guessed name lies (tracking URLs, no extension)
    ("mp3", None, "m4a"),
    ("mp3", "ep.mp3", "m4a"),
    ("m4a", "ep.m4a", "m4a"),  # already right: kept as is
]


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
@pytest.mark.parametrize(("source", "out_name", "fmt"), CASES)
async def test_download_output_matches_the_requested_format(
    tmp_path, sources, adapter, source, out_name, fmt
):
    cls, stub, url = ADAPTERS[adapter]
    d = cls(settings=IngestSettings(download_dir=str(tmp_path)))
    # The URL claims mp3 whatever the bytes are — like a redirect/tracking URL.
    stub(d, sources[source], "https://cdn.example/audio.mp3")

    result = await d.download(
        url, output_path=tmp_path / out_name if out_name else None, output_format=fmt
    )

    assert result.success, result.error
    assert result.file_path.suffix == f".{fmt}"
    assert probe(result.file_path) == EXPECTED[fmt]
    if out_name:
        assert result.file_path == (tmp_path / out_name).with_suffix(f".{fmt}")


async def test_discord_converts_to_the_requested_output_path(tmp_path, sources, monkeypatch):
    """Discord used to convert its temp file and ignore `output_path`."""
    payload = sources["mp3"].read_bytes()

    async def fake_get(url, **kwargs):
        return SimpleNamespace(status_code=200, content=payload)

    monkeypatch.setattr(discord_audio, "safe_get", fake_get)
    d = DiscordAudioDownloader(settings=IngestSettings(download_dir=str(tmp_path)))
    out = tmp_path / "voice.m4a"

    result = await d.download(
        "https://cdn.discordapp.com/attachments/111/222/voice.mp3",
        output_path=out,
        output_format="m4a",
    )

    assert result.success, result.error
    assert result.file_path == out
    assert probe(out) == EXPECTED["m4a"]
    assert not list(tmp_path.glob("discord_temp_*")), "temp file left behind"
