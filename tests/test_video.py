"""Tests for the audio-to-video (YouTube-ready MP4) module."""

import json as _json
import os as _os
import shutil as _shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sift_core.exceptions import FFmpegError
from sift_core.media.video import (
    AudioToVideo,
    _default_output_path,
    _resolution_dims,
)


@pytest.fixture
def maker(monkeypatch):
    """AudioToVideo with ffmpeg/ffprobe presence faked."""
    monkeypatch.setattr("sift_core.media.video.shutil.which", lambda name: f"/usr/bin/{name}")
    return AudioToVideo()


def test_default_output_path_derives_youtube_suffix():
    assert _default_output_path(Path("a/b/podcast.m4a")) == Path("a/b/podcast.youtube.mp4")


def test_default_output_path_handles_non_ascii_and_spaces():
    assert _default_output_path(Path("对话 周晨.m4a")) == Path("对话 周晨.youtube.mp4")


def test_resolution_dims_known():
    assert _resolution_dims("480p") == (854, 480)
    assert _resolution_dims("720p") == (1280, 720)
    assert _resolution_dims("1080p") == (1920, 1080)


def test_resolution_dims_unknown_raises():
    with pytest.raises(FFmpegError, match="Unsupported resolution"):
        _resolution_dims("240p")


def test_missing_ffmpeg_raises(monkeypatch):
    monkeypatch.setattr("sift_core.media.video.shutil.which", lambda name: None)
    with pytest.raises(FFmpegError, match="not found in PATH"):
        AudioToVideo()


def test_maker_constructs_with_binaries(maker):
    assert maker._ffmpeg == "/usr/bin/ffmpeg"
    assert maker._ffprobe == "/usr/bin/ffprobe"


async def test_probe_audio_codec_selects_primary_stream(maker):
    payload = _json.dumps({"streams": [{"codec_name": "AAC"}]})
    maker._run = AsyncMock(return_value=(payload, "", 0))
    codec = await maker._probe_audio_codec(Path("in.m4a"))
    assert codec == "aac"  # normalized lowercase
    cmd = maker._run.call_args.args[0]
    assert "-select_streams" in cmd and "a:0" in cmd  # primary audio only


async def test_probe_audio_codec_no_stream_raises(maker):
    maker._run = AsyncMock(return_value=('{"streams": []}', "", 0))
    with pytest.raises(FFmpegError, match="No audio stream"):
        await maker._probe_audio_codec(Path("in.m4a"))


async def test_find_attached_cover_returns_index(maker):
    payload = _json.dumps({"streams": [
        {"index": 0, "codec_type": "audio", "disposition": {"attached_pic": 0}},
        {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 1}},
    ]})
    maker._run = AsyncMock(return_value=(payload, "", 0))
    assert await maker._find_attached_cover(Path("in.m4a")) == 1


async def test_find_attached_cover_ignores_normal_video(maker):
    payload = _json.dumps({"streams": [
        {"index": 0, "codec_type": "audio", "disposition": {"attached_pic": 0}},
        {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 0}},
    ]})
    maker._run = AsyncMock(return_value=(payload, "", 0))
    assert await maker._find_attached_cover(Path("in.m4a")) is None


async def test_find_attached_cover_none_when_audio_only(maker):
    payload = _json.dumps({"streams": [
        {"index": 0, "codec_type": "audio", "disposition": {"attached_pic": 0}},
    ]})
    maker._run = AsyncMock(return_value=(payload, "", 0))
    assert await maker._find_attached_cover(Path("in.m4a")) is None


async def test_extract_cover_writes_png_and_maps_index(maker, tmp_path):
    async def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"\x89PNG")  # simulate ffmpeg writing the file
        return ("", "", 0)

    maker._run = fake_run
    out = await maker._extract_cover(Path("in.m4a"), 3, tmp_path)
    assert out == tmp_path / "cover.png"
    assert out.exists()


async def test_extract_cover_uses_exact_stream_map(maker, tmp_path):
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"\x89PNG")
        return ("", "", 0)

    maker._run = fake_run
    await maker._extract_cover(Path("in.m4a"), 3, tmp_path)
    assert "-map" in captured["cmd"]
    assert "0:3" in captured["cmd"]
    assert "-frames:v" in captured["cmd"]


async def test_extract_cover_failure_raises(maker, tmp_path):
    maker._run = AsyncMock(return_value=("", "boom", 1))
    with pytest.raises(FFmpegError, match="cover art"):
        await maker._extract_cover(Path("in.m4a"), 3, tmp_path)


def _build(maker, **overrides):
    kwargs = dict(
        image=None, image_is_generated=True,
        audio_path=Path("in.m4a"), output_path=Path("out.tmp.mp4"),
        width=1280, height=720, fps=2, audio_copy=True,
    )
    kwargs.update(overrides)
    return maker._build_command(**kwargs)


def test_build_command_generated_background(maker):
    cmd = _build(maker, image_is_generated=True)
    joined = " ".join(cmd)
    assert "lavfi" in joined
    assert "color=c=0x0f0f14:s=1280x720:r=2" in joined
    assert "-loop" not in cmd  # generated bg is not a looped image


def test_build_command_with_image_loops(maker):
    cmd = _build(maker, image=Path("cover.png"), image_is_generated=False)
    assert "-loop" in cmd and "1" in cmd
    assert "-framerate" in cmd
    assert str(Path("cover.png")) in cmd


def test_build_command_explicit_mapping_and_codecs(maker):
    cmd = _build(maker)
    assert cmd.count("-map") == 2
    assert "0:v:0" in cmd and "1:a:0" in cmd
    assert "libx264" in cmd
    assert "yuv420p" in cmd
    assert "-fps_mode" in cmd and "cfr" in cmd
    assert "-shortest" in cmd
    assert "+faststart" in cmd
    assert cmd[-1] == str(Path("out.tmp.mp4"))


def test_build_command_aspect_preserving_filter(maker):
    cmd = _build(maker)
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    assert "pad=1280:720" in vf
    assert "format=yuv420p" in vf


def test_build_command_audio_copy(maker):
    cmd = _build(maker, audio_copy=True)
    idx = cmd.index("-c:a")
    assert cmd[idx + 1] == "copy"
    assert "aac" not in cmd


def test_build_command_audio_encode(maker):
    cmd = _build(maker, audio_copy=False)
    idx = cmd.index("-c:a")
    assert cmd[idx + 1] == "aac"
    assert "128k" in cmd


def test_preflight_missing_input_raises(maker, tmp_path):
    with pytest.raises(FFmpegError, match="Input file not found"):
        maker._preflight(tmp_path / "nope.m4a", tmp_path / "out.mp4", None)


def test_preflight_existing_output_refused(maker, tmp_path):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"x")
    out = tmp_path / "out.mp4"
    out.write_bytes(b"y")
    with pytest.raises(FFmpegError, match="refusing to overwrite"):
        maker._preflight(src, out, None)


def test_preflight_missing_image_raises(maker, tmp_path):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"x")
    with pytest.raises(FFmpegError, match="Image file not found"):
        maker._preflight(src, tmp_path / "out.mp4", tmp_path / "missing.png")


def test_preflight_unwritable_destination(maker, tmp_path, monkeypatch):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"x")
    monkeypatch.setattr("sift_core.media.video.os.access", lambda p, m: False)
    with pytest.raises(FFmpegError, match="not writable"):
        maker._preflight(src, tmp_path / "out.mp4", None)


def test_preflight_passes_for_valid_inputs(maker, tmp_path):
    src = tmp_path / "in.m4a"
    src.write_bytes(b"x")
    maker._preflight(src, tmp_path / "out.mp4", None)  # no raise


def test_is_copy_mux_failure_true_for_tag_error(maker):
    assert maker._is_copy_mux_failure("Could not find tag for codec in stream")


def test_is_copy_mux_failure_false_for_missing_encoder(maker):
    assert not maker._is_copy_mux_failure("Unknown encoder 'libx264'")


@pytest.fixture
def wired(maker, monkeypatch):
    """maker with probe/cover stubbed; _run touches its output file on success."""
    maker._probe_audio_codec = AsyncMock(return_value="aac")
    maker._find_attached_cover = AsyncMock(return_value=None)
    maker.calls = []

    async def fake_run(cmd):
        maker.calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"\x00" * 16)  # simulate ffmpeg output
        return ("", "", 0)

    maker._run = fake_run
    return maker


async def test_create_aac_copies_audio_and_writes_default_output(wired, tmp_path):
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    out = await wired.create(src)
    assert out == tmp_path / "podcast.youtube.mp4"
    assert out.exists()
    # audio stream-copied, generated background used
    cmd = wired.calls[-1]
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "lavfi" in " ".join(cmd)


async def test_create_non_aac_encodes_audio(wired, tmp_path):
    wired._probe_audio_codec = AsyncMock(return_value="mp3")
    src = tmp_path / "podcast.mp3"
    src.write_bytes(b"audio")
    await wired.create(src)
    cmd = wired.calls[-1]
    assert cmd[cmd.index("-c:a") + 1] == "aac"


async def test_create_refuses_existing_output(wired, tmp_path):
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    (tmp_path / "podcast.youtube.mp4").write_bytes(b"old")
    with pytest.raises(FFmpegError, match="refusing to overwrite"):
        await wired.create(src)


async def test_create_handles_non_ascii_paths(wired, tmp_path):
    src = tmp_path / "对话 周晨 完整版.m4a"
    src.write_bytes(b"audio")
    out = await wired.create(src)
    assert out.name == "对话 周晨 完整版.youtube.mp4"
    assert out.exists()


async def test_create_uses_embedded_cover(wired, tmp_path):
    wired._find_attached_cover = AsyncMock(return_value=1)
    wired._extract_cover = AsyncMock(
        side_effect=lambda i, idx, wd: (Path(wd) / "cover.png").write_bytes(b"\x89PNG")
        or (Path(wd) / "cover.png")
    )
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    await wired.create(src)
    cmd = wired.calls[-1]
    assert "-loop" in cmd
    assert "lavfi" not in " ".join(cmd)


async def test_create_copy_failure_retries_with_aac(maker, tmp_path):
    maker._probe_audio_codec = AsyncMock(return_value="aac")
    maker._find_attached_cover = AsyncMock(return_value=None)
    maker.calls = []
    seq = [("", "Could not find tag for codec", 1)]  # first: copy mux failure

    async def fake_run(cmd):
        maker.calls.append(list(cmd))
        if seq:
            return seq.pop(0)
        Path(cmd[-1]).write_bytes(b"\x00")  # retry succeeds
        return ("", "", 0)

    maker._run = fake_run
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    out = await maker.create(src)
    assert out.exists()
    assert len(maker.calls) == 2
    assert maker.calls[0][maker.calls[0].index("-c:a") + 1] == "copy"
    assert maker.calls[1][maker.calls[1].index("-c:a") + 1] == "aac"


async def test_create_non_mux_failure_does_not_retry(maker, tmp_path):
    maker._probe_audio_codec = AsyncMock(return_value="aac")
    maker._find_attached_cover = AsyncMock(return_value=None)
    calls = []

    async def fake_run(cmd):
        calls.append(cmd)
        return ("", "Unknown encoder libx264", 1)  # infrastructure failure

    maker._run = fake_run
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    with pytest.raises(FFmpegError, match="Video creation failed"):
        await maker.create(src)
    assert len(calls) == 1  # no retry


async def test_create_failed_fallback_preserves_both_errors(maker, tmp_path):
    maker._probe_audio_codec = AsyncMock(return_value="aac")
    maker._find_attached_cover = AsyncMock(return_value=None)
    outs = [("", "Could not find tag for codec", 1), ("", "aac encoder exploded", 1)]

    async def fake_run(cmd):
        return outs.pop(0)

    maker._run = fake_run
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    with pytest.raises(FFmpegError) as exc:
        await maker.create(src)
    msg = str(exc.value)
    assert "Could not find tag" in msg and "aac encoder exploded" in msg


async def test_create_leaves_no_temp_on_failure(maker, tmp_path):
    maker._probe_audio_codec = AsyncMock(return_value="aac")
    maker._find_attached_cover = AsyncMock(return_value=None)
    maker._run = AsyncMock(return_value=("", "Unknown encoder libx264", 1))
    src = tmp_path / "podcast.m4a"
    src.write_bytes(b"audio")
    with pytest.raises(FFmpegError):
        await maker.create(src)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "podcast.m4a"]
    assert leftovers == []  # TemporaryDirectory cleaned up


async def test_to_video_command_invokes_create(tmp_path, monkeypatch, capsys):
    from sift_core import cli

    src = tmp_path / "in.m4a"
    src.write_bytes(b"audio")
    out = tmp_path / "in.youtube.mp4"
    out.write_bytes(b"\x00" * 2048)

    created = {}

    class FakeMaker:
        async def create(self, input_path, output_path=None, resolution="720p", fps=2):
            created["input"] = Path(input_path)
            created["resolution"] = resolution
            created["fps"] = fps
            return out

    monkeypatch.setattr(cli, "AudioToVideo", lambda: FakeMaker(), raising=False)
    args = SimpleNamespace(
        input=str(src), output=None, resolution="1080p", fps=1
    )
    await cli.to_video_command(args)
    assert created["input"] == src
    assert created["resolution"] == "1080p"
    assert created["fps"] == 1
    assert "Video ready" in capsys.readouterr().out


async def test_to_video_command_missing_input_exits(tmp_path):
    from sift_core import cli

    args = SimpleNamespace(input=str(tmp_path / "nope.m4a"), output=None,
                           resolution="720p", fps=2)
    with pytest.raises(SystemExit):
        await cli.to_video_command(args)


async def test_to_video_command_missing_ffmpeg_exits_cleanly(tmp_path, monkeypatch, capsys):
    from sift_core import cli

    src = tmp_path / "in.m4a"
    src.write_bytes(b"audio")

    def boom(*args, **kwargs):
        raise FFmpegError("ffmpeg not found in PATH. Please install it: brew install ffmpeg")

    monkeypatch.setattr(cli, "AudioToVideo", boom, raising=False)
    args = SimpleNamespace(input=str(src), output=None, resolution="720p", fps=2)
    with pytest.raises(SystemExit):
        await cli.to_video_command(args)
    assert "Video creation failed" in capsys.readouterr().err


@pytest.mark.skipif(
    not _os.environ.get("RUN_FFMPEG_INTEGRATION") or _shutil.which("ffmpeg") is None,
    reason="opt-in: set RUN_FFMPEG_INTEGRATION=1 and install ffmpeg",
)
async def test_integration_creates_youtube_ready_mp4(tmp_path):
    # Build a 1s AAC/m4a fixture with ffmpeg.
    src = tmp_path / "fixture.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "aac", str(src)],
        check=True, capture_output=True,
    )
    out = await AudioToVideo().create(src)
    assert out.exists()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,pix_fmt:format=duration",
         "-of", "json", str(out)],
        check=True, capture_output=True, text=True,
    )
    data = _json.loads(probe.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["pix_fmt"] == "yuv420p"
    assert streams["audio"]["codec_name"] == "aac"
    assert abs(float(data["format"]["duration"]) - 1.0) < 0.5
