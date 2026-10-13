"""The local MCP server (`sift_core.local_mcp`, ``sift-core-mcp``).

Tools are driven through ``FastMCP.call_tool`` with the core functions they
wrap faked out, so these run offline. The live check is in the PR description.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import sift_core.local_mcp as local_mcp
import sift_core.transcribe.transcription_engine as engines
from sift_core import AudioMetadata, DownloadResult, IngestSettings, Platform
from sift_core.exceptions import ContentNotFoundError
from sift_core.fetch.transcript_fetcher import FetchedTranscript
from sift_core.transcribe.transcriber import TranscriptionResult, TranscriptionSegment

APPLE = "https://podcasts.apple.com/us/podcast/x/id1434243584"
YOUTUBE = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _parse(result) -> dict:
    """call_tool returns content blocks (older mcp) or (content, structured)."""
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


@pytest.fixture
def settings(tmp_path) -> IngestSettings:
    return IngestSettings(download_dir=str(tmp_path / "dl"))


@pytest.fixture
def server(settings):
    return local_mcp.build_server(settings)


async def call(server, name, **args) -> dict:
    return _parse(await server.call_tool(name, args))


async def test_tool_surface(server):
    names = {t.name for t in await server.list_tools()}
    assert names == {"capabilities", "get_metadata", "download", "fetch_transcript", "transcribe"}


async def test_capabilities_lists_every_platform_and_engine(server, settings):
    out = await call(server, "capabilities")
    assert out["ok"] is True
    assert {p["platform"] for p in out["platforms"]} == {p.value for p in Platform}
    assert {e["engine"] for e in out["transcription_engines"]} == {
        e.value for e in engines.TranscriptionEngine
    }
    assert out["download_dir"] == str(Path(settings.download_dir))


# ─── get_metadata ───


async def test_get_metadata_passes_settings_and_serializes(server, settings, monkeypatch):
    seen = {}

    async def fake(url, settings=None):
        seen["settings"] = settings
        return AudioMetadata(platform=Platform.APPLE_PODCASTS, content_id="1", title="Ep 1")

    monkeypatch.setattr(local_mcp, "get_metadata", fake)
    out = await call(server, "get_metadata", url=APPLE)
    assert out["ok"] is True
    assert out["platform"] == "apple_podcasts"
    assert out["metadata"]["platform"] == "apple_podcasts"  # enum → value
    assert out["metadata"]["title"] == "Ep 1"
    assert out["metadata"]["published_at"] is None
    assert seen["settings"] is settings


async def test_get_metadata_rejects_unsupported_urls(server):
    out = await call(server, "get_metadata", url="https://example.com/x")
    assert out["ok"] is False and "Unsupported" in out["error"]


async def test_get_metadata_reports_core_errors_instead_of_raising(server, monkeypatch):
    async def boom(url, settings=None):
        raise ContentNotFoundError("episode gone")

    monkeypatch.setattr(local_mcp, "get_metadata", boom)
    out = await call(server, "get_metadata", url=APPLE)
    assert out == {"ok": False, "error": "episode gone", "platform": "apple_podcasts"}


# ─── download ───


async def test_download_returns_the_file(server, settings, monkeypatch, tmp_path):
    seen = {}

    async def fake(url, output_format, quality, settings=None):
        seen.update(format=output_format, quality=quality, settings=settings)
        return DownloadResult(success=True, file_path=tmp_path / "a.mp3", file_size_bytes=42)

    monkeypatch.setattr(local_mcp, "download_audio", fake)
    out = await call(server, "download", url=APPLE, format="mp3", quality="highest")
    assert out["ok"] is True
    assert out["file_path"] == str(tmp_path / "a.mp3")
    assert out["file_size_bytes"] == 42
    assert seen == {"format": "mp3", "quality": "highest", "settings": settings}


async def test_download_failure_is_reported(server, monkeypatch):
    async def fake(url, **kw):
        return DownloadResult(success=False, error="yt-dlp failed")

    monkeypatch.setattr(local_mcp, "download_audio", fake)
    assert await call(server, "download", url=APPLE) == {"ok": False, "error": "yt-dlp failed"}


# ─── fetch_transcript ───


def _fake_fetcher(monkeypatch, fetched: FetchedTranscript, seen: dict):
    class FakeFetcher(local_mcp.TranscriptFetcher):
        def __init__(self, settings=None):
            seen["settings"] = settings

        async def fetch_transcript(self, url, language=None):
            seen["language"] = language
            return fetched

    monkeypatch.setattr(local_mcp, "TranscriptFetcher", FakeFetcher)


async def test_fetch_transcript_caps_text_and_omits_segments_by_default(
    server, settings, monkeypatch
):
    seen = {}
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    _fake_fetcher(
        monkeypatch,
        FetchedTranscript(success=True, text="x" * 50, segments=segments, source="youtube_auto"),
        seen,
    )
    out = await call(server, "fetch_transcript", url=YOUTUBE, language="en", max_chars=10)
    assert out["ok"] is True
    assert out["text"] == "x" * 10
    assert out["truncated"] is True and out["total_chars"] == 50
    assert out["segment_count"] == 1 and "segments" not in out
    assert out["source"] == "youtube_auto"
    assert seen == {"settings": settings, "language": "en"}

    full = await call(server, "fetch_transcript", url=YOUTUBE, include_segments=True)
    assert full["truncated"] is False and full["segments"] == segments


async def test_fetch_transcript_only_for_youtube_and_spotify(server):
    out = await call(server, "fetch_transcript", url=APPLE)
    assert out["ok"] is False and "transcribe" in out["error"]


# ─── transcribe ───


class _FakeEngine:
    def __init__(self, available=True, result=None):
        self.available = available
        self.result = result
        self.calls = []

    def is_available(self):
        return self.available

    async def transcribe(self, audio_path, language=None, **kw):
        self.calls.append((Path(audio_path), language))
        return self.result


def _use_engine(monkeypatch, engine: _FakeEngine, best=engines.TranscriptionEngine.WHISPER):
    monkeypatch.setattr(engines, "get_best_engine", lambda language=None: best)
    monkeypatch.setattr(engines, "get_engine", lambda chosen: engine)


async def test_transcribe_downloads_urls_first(server, settings, monkeypatch, tmp_path):
    audio = tmp_path / "ep.m4a"

    async def fake_download(url, settings=None):
        assert settings is not None
        return DownloadResult(success=True, file_path=audio)

    monkeypatch.setattr(local_mcp, "download_audio", fake_download)
    engine = _FakeEngine(
        result=TranscriptionResult(
            success=True,
            text="hi there",
            segments=[TranscriptionSegment(start=0.0, end=1.5, text="hi there")],
            language="en",
            duration=1.5,
        )
    )
    _use_engine(monkeypatch, engine)

    out = await call(server, "transcribe", source=APPLE, include_segments=True)
    assert engine.calls == [(audio, None)]
    assert out["ok"] is True
    assert out["engine"] == "whisper" and out["audio_path"] == str(audio)
    assert out["text"] == "hi there"
    assert out["segments"][0]["text"] == "hi there" and out["segments"][0]["end"] == 1.5


async def test_transcribe_local_file(server, monkeypatch, tmp_path):
    audio = tmp_path / "local.wav"
    audio.write_bytes(b"RIFF")
    engine = _FakeEngine(result=TranscriptionResult(success=True, text="ok"))
    _use_engine(monkeypatch, engine)

    out = await call(server, "transcribe", source=str(audio), language="zh")
    assert out["ok"] is True
    assert engine.calls == [(audio, "zh")]


async def test_transcribe_missing_file(server):
    out = await call(server, "transcribe", source="/nope/missing.wav")
    assert out["ok"] is False and "File not found" in out["error"]


async def test_transcribe_explains_a_missing_engine(server, monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    _use_engine(monkeypatch, _FakeEngine(available=False))
    out = await call(server, "transcribe", source=str(audio))
    assert out["ok"] is False
    assert "sift-core[transcribe]" in out["error"]
    assert out["audio_path"] == str(audio)


async def test_transcribe_honours_an_explicit_engine(server, monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    chosen = []
    engine = _FakeEngine(result=TranscriptionResult(success=True, text="ok"))
    monkeypatch.setattr(
        engines, "get_best_engine", lambda language=None: pytest.fail("must not auto-pick")
    )
    monkeypatch.setattr(engines, "get_engine", lambda e: chosen.append(e) or engine)
    out = await call(server, "transcribe", source=str(audio), engine="apple")
    assert out["engine"] == "apple"
    assert chosen == [engines.TranscriptionEngine.APPLE]


# ─── stdio safety ───


def test_server_module_does_not_load_the_app():
    """sift-core-mcp must run from a plain `pip install 'sift-core[mcp]'`."""
    import subprocess

    script = (
        "import sys, sift_core.local_mcp as m; m.build_server(); "
        "print(','.join(x for x in sys.modules if x == 'app' or x.startswith('app.')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert out.stdout.strip() == ""
