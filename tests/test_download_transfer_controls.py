"""yt-dlp transfer controls: concurrent fragments and download rate limit.

Both come from `IngestSettings` (env: DOWNLOAD_CONCURRENT_FRAGMENTS,
DOWNLOAD_RATE_LIMIT), can be overridden per call from the CLI and the local
MCP server, and reach yt-dlp through the single `yt_dlp_transfer_args` helper.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import sift_core.local_mcp as local_mcp
from sift_core import DownloadResult, IngestSettings
from sift_core.base import yt_dlp_transfer_args
from sift_core.platforms import (
    InstagramVideoDownloader,
    XiaohongshuVideoDownloader,
    XimalayaDownloader,
    XSpacesDownloader,
    XVideoDownloader,
    YouTubeDownloader,
    YouTubeVideoDownloader,
)
from sift_core.settings import normalize_rate_limit


# ─── rate limit parsing ───


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("500K", "500K"),
        ("2m", "2M"),
        (" 1.5M ", "1.5M"),
        ("1048576", "1048576"),
        ("1G", "1G"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_rate_limit_accepts(raw, expected):
    assert normalize_rate_limit(raw) == expected


@pytest.mark.parametrize(
    "raw", ["fast", "2MB", "-1M", "0", "0K", "1M --exec rm", "--limit-rate", 5]
)
def test_normalize_rate_limit_rejects(raw):
    with pytest.raises(ValueError):
        normalize_rate_limit(raw)


# ─── settings ───


def test_defaults_match_the_old_hardcoded_flags():
    s = IngestSettings(_env_file=None)
    assert s.download_concurrent_fragments == 16
    assert s.download_rate_limit is None


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_CONCURRENT_FRAGMENTS", "4")
    monkeypatch.setenv("DOWNLOAD_RATE_LIMIT", "750k")
    s = IngestSettings(_env_file=None)
    assert s.download_concurrent_fragments == 4
    assert s.download_rate_limit == "750K"


def test_app_settings_inherit_the_fields(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("DOWNLOAD_RATE_LIMIT", "1M")
    assert Settings(_env_file=None).download_rate_limit == "1M"


@pytest.mark.parametrize("bad", [0, 65, -3])
def test_concurrent_fragments_out_of_range_is_rejected(bad):
    with pytest.raises(ValueError):
        IngestSettings(_env_file=None, download_concurrent_fragments=bad)


def test_invalid_rate_limit_in_settings_is_rejected():
    with pytest.raises(ValueError):
        IngestSettings(_env_file=None, download_rate_limit="lots")


def test_overrides_without_values_return_the_same_object():
    s = IngestSettings(_env_file=None)
    assert s.with_download_overrides() is s


def test_overrides_copy_and_leave_the_original_alone():
    s = IngestSettings(_env_file=None, download_rate_limit="1M")
    out = s.with_download_overrides(concurrent_fragments=2, rate_limit="300k")
    assert (out.download_concurrent_fragments, out.download_rate_limit) == (2, "300K")
    assert (s.download_concurrent_fragments, s.download_rate_limit) == (16, "1M")


@pytest.mark.parametrize(
    "kwargs", [{"concurrent_fragments": 0}, {"concurrent_fragments": 100}, {"rate_limit": "x"}]
)
def test_overrides_are_validated(kwargs):
    with pytest.raises(ValueError):
        IngestSettings(_env_file=None).with_download_overrides(**kwargs)


# ─── argv ───


def test_transfer_args_without_rate_limit():
    s = IngestSettings(_env_file=None)
    assert yt_dlp_transfer_args(s) == [
        "--concurrent-fragments", "16", "--fragment-retries", "5",
    ]


def test_transfer_args_with_rate_limit():
    s = IngestSettings(_env_file=None, download_concurrent_fragments=3, download_rate_limit="2M")
    assert yt_dlp_transfer_args(s) == [
        "--concurrent-fragments", "3", "--fragment-retries", "5", "--limit-rate", "2M",
    ]


YT_DLP_ADAPTERS = [
    (YouTubeDownloader, "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    (YouTubeVideoDownloader, "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    (XSpacesDownloader, "https://x.com/i/spaces/1vOxwdyYrlqKB"),
    (XVideoDownloader, "https://x.com/someone/status/1234567890"),
    (InstagramVideoDownloader, "https://www.instagram.com/reel/Cabc123/"),
    (XiaohongshuVideoDownloader, "https://www.xiaohongshu.com/explore/abc123"),
    (XimalayaDownloader, "https://www.ximalaya.com/sound/123456"),
]


@pytest.mark.parametrize("adapter, url", YT_DLP_ADAPTERS, ids=lambda v: getattr(v, "__name__", ""))
def test_every_yt_dlp_adapter_passes_the_settings_to_yt_dlp(adapter, url, monkeypatch, tmp_path):
    """The download argv carries the configured flags, not the old hardcoded 16."""
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

    monkeypatch.setenv("YT_DLP_PATH", str(tmp_path / "yt-dlp"))
    (tmp_path / "yt-dlp").write_text("")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    settings = IngestSettings(
        _env_file=None,
        download_dir=str(tmp_path / "dl"),
        download_concurrent_fragments=5,
        download_rate_limit="640K",
    )
    downloader = adapter(settings=settings)
    try:
        asyncio.run(downloader.download(url))
    except Exception:
        pass  # the stubbed failure surfaces as an error; only the argv matters

    downloads = [argv for argv in calls if "-o" in argv]
    assert downloads, f"{adapter.__name__} never ran a yt-dlp download"
    for argv in downloads:
        joined = " ".join(argv)
        assert "--concurrent-fragments 5" in joined
        assert "--limit-rate 640K" in joined
        assert "--concurrent-fragments 16" not in joined
        # The flags stay ahead of "--", so they can't be mistaken for the URL.
        assert argv.index("--limit-rate") < argv.index("--")


# ─── CLI ───


def _cli_args(**overrides):
    base = dict(
        url="https://youtu.be/dQw4w9WgXcQ",
        output=None,
        format="m4a",
        quality="high",
        concurrent_fragments=None,
        limit_rate=None,
    )
    return SimpleNamespace(**{**base, **overrides})


def _patch_cli(monkeypatch, tmp_path, seen):
    import sift_core.cli as cli
    from sift_core.base import Platform
    from sift_core.fetch.downloader import DownloaderFactory

    monkeypatch.setattr(
        DownloaderFactory, "detect_platform", staticmethod(lambda url: Platform.YOUTUBE)
    )
    monkeypatch.setattr(cli, "get_ingest_settings", lambda: IngestSettings(_env_file=None))

    async def fake_download_audio(url, output_path, output_format, quality, settings):
        seen["settings"] = settings
        return SimpleNamespace(
            success=True, file_path=tmp_path / "a.m4a", file_size_mb=None,
            metadata=None, error=None,
        )

    monkeypatch.setattr(cli, "download_audio", fake_download_audio)
    return cli


def test_cli_overrides_reach_the_downloader(monkeypatch, tmp_path):
    seen: dict = {}
    cli = _patch_cli(monkeypatch, tmp_path, seen)
    asyncio.run(cli.download_command(_cli_args(concurrent_fragments=2, limit_rate="1m")))
    assert seen["settings"].download_concurrent_fragments == 2
    assert seen["settings"].download_rate_limit == "1M"


def test_cli_rejects_a_bad_rate_limit(monkeypatch, tmp_path, capsys):
    seen: dict = {}
    cli = _patch_cli(monkeypatch, tmp_path, seen)
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.download_command(_cli_args(limit_rate="fast")))
    assert exc.value.code == 2
    assert "invalid rate limit" in capsys.readouterr().err
    assert "settings" not in seen


def test_cli_parser_accepts_the_flags(monkeypatch):
    import sift_core.cli as cli

    captured = {}

    async def fake_download_command(args):
        captured.update(vars(args))

    monkeypatch.setattr(cli, "download_command", fake_download_command)
    monkeypatch.setattr(
        "sys.argv",
        ["sift", "download", "-N", "4", "--limit-rate", "2M", "https://youtu.be/dQw4w9WgXcQ"],
    )
    asyncio.run(cli.main())
    assert captured["concurrent_fragments"] == 4
    assert captured["limit_rate"] == "2M"


# ─── local MCP ───


def _parse(result) -> dict:
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


APPLE = "https://podcasts.apple.com/us/podcast/x/id1434243584"


async def test_mcp_download_applies_overrides(monkeypatch, tmp_path):
    base = IngestSettings(_env_file=None, download_dir=str(tmp_path))
    server = local_mcp.build_server(base)
    seen = {}

    async def fake(url, output_format, quality, settings=None):
        seen["settings"] = settings
        return DownloadResult(success=True, file_path=tmp_path / "a.m4a", file_size_bytes=1)

    monkeypatch.setattr(local_mcp, "download_audio", fake)
    out = _parse(
        await server.call_tool(
            "download", {"url": APPLE, "rate_limit": "500k", "concurrent_fragments": 3}
        )
    )
    assert out["ok"] is True
    assert seen["settings"].download_rate_limit == "500K"
    assert seen["settings"].download_concurrent_fragments == 3
    assert base.download_rate_limit is None


async def test_mcp_download_reports_a_bad_rate_limit(monkeypatch, tmp_path):
    server = local_mcp.build_server(IngestSettings(_env_file=None, download_dir=str(tmp_path)))

    async def fake(*a, **kw):  # pragma: no cover - must not be reached
        raise AssertionError("download ran with an invalid rate limit")

    monkeypatch.setattr(local_mcp, "download_audio", fake)
    out = _parse(await server.call_tool("download", {"url": APPLE, "rate_limit": "fast"}))
    assert out["ok"] is False
    assert "invalid rate limit" in out["error"]


async def test_mcp_transcribe_applies_overrides_to_its_download(monkeypatch, tmp_path):
    server = local_mcp.build_server(IngestSettings(_env_file=None, download_dir=str(tmp_path)))
    seen = {}

    async def fake(url, settings=None):
        seen["settings"] = settings
        return DownloadResult(success=False, error="stop here")

    monkeypatch.setattr(local_mcp, "download_audio", fake)
    out = _parse(await server.call_tool("transcribe", {"source": APPLE, "rate_limit": "2M"}))
    assert out == {"ok": False, "error": "stop here"}
    assert seen["settings"].download_rate_limit == "2M"
