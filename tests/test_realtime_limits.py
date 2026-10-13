"""A live transcription session cannot grow without bound.

Regression tests for the security audit: /api/transcribe/live kept every
byte it received, re-decoded the whole stream with ffmpeg on every message
while nothing decoded, and took min_chunk_duration from the client
unchecked.
"""

import base64
import shutil
import subprocess
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import realtime_routes
from sift_core.transcribe import realtime_transcriber as rt


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def webm_stream(tmp_path_factory):
    """12 s of Opus in WebM, the shape MediaRecorder sends."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path_factory.mktemp("webm") / "tone.webm"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-c:a", "libopus", "-b:a", "32k", "-f", "webm", "-cluster_time_limit", "1000", str(path)],
        check=True,
    )
    return path.read_bytes()


@pytest.fixture
def popen_count(monkeypatch):
    calls = []
    real = rt.subprocess.Popen

    def counting(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(rt.subprocess, "Popen", counting)
    return calls


def _session(**kwargs):
    return rt.RealtimeTranscriptionSession(model_size="tiny", **kwargs)


async def _feed(session, chunk: bytes):
    async for _ in session.process_audio_chunk(chunk):
        pass


class TestStreamingDecoder:
    def test_stream_size_is_capped(self, monkeypatch):
        monkeypatch.setattr(rt, "MAX_SESSION_BYTES", 100)
        decoder = rt.StreamingWebmDecoder()
        with pytest.raises(rt.SessionLimitError):
            decoder.add_chunk(b"x" * 101)
        decoder.clear()

    @needs_ffmpeg
    def test_decodes_incrementally_with_one_process(self, webm_stream, popen_count):
        decoder = rt.StreamingWebmDecoder()
        step = len(webm_stream) // 12
        decoded = 0
        try:
            for i in range(12):
                decoder.add_chunk(webm_stream[i * step:(i + 1) * step if i < 11 else None])
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:  # wait for this chunk's audio
                    got = len(decoder.decode_new())
                    decoded += got
                    if got:
                        break
                    time.sleep(0.02)
            decoded += len(decoder.finish())
        finally:
            decoder.clear()
        assert len(popen_count) == 1  # one ffmpeg for the whole stream
        assert decoded == pytest.approx(12 * 16000, rel=0.01)


class TestSession:
    @needs_ffmpeg
    async def test_session_gives_up_on_undecodable_input(self, monkeypatch, popen_count):
        session = _session(min_chunk_duration=3.0)
        clock = iter(range(0, 10_000, 10))
        monkeypatch.setattr(rt.time, "monotonic", lambda: float(next(clock)))
        try:
            with pytest.raises(rt.SessionLimitError):
                for _ in range(rt.MAX_FAILED_DECODES + 1):
                    await _feed(session, b"\0" * 1024)
        finally:
            session.cleanup()
        assert len(popen_count) == 1

    @needs_ffmpeg
    async def test_cleanup_stops_ffmpeg(self, webm_stream):
        session = _session()
        await _feed(session, webm_stream[:4096])
        proc = session._webm_accumulator._proc
        session.cleanup()
        assert proc.poll() is not None


class TestRoute:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(realtime_routes.router, prefix="/api")
        return TestClient(app)

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 1.0), (-5, 1.0), (1e9, 30.0), ("nan", 3.0), ("x", 3.0), (None, 3.0), (5, 5.0)],
    )
    def test_chunk_duration_is_clamped(self, value, expected):
        assert realtime_routes._clamp_chunk_duration(value) == expected

    def test_oversized_audio_message_closes_session(self, client, monkeypatch):
        monkeypatch.setattr(realtime_routes, "MAX_AUDIO_MESSAGE_BYTES", 1024)
        with client.websocket_connect("/api/transcribe/live") as ws:
            ws.send_json({"type": "start", "config": {"model": "tiny"}})
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"type": "audio", "data": base64.b64encode(b"x" * 4096).decode()})
            msg = ws.receive_json()
            assert msg == {"type": "error", "error": "Audio message too large", "recoverable": False}
        assert realtime_routes._live_sessions == 0

    def test_session_count_is_limited(self, client, monkeypatch):
        monkeypatch.setattr(realtime_routes, "_live_sessions", realtime_routes.MAX_LIVE_SESSIONS)
        with client.websocket_connect("/api/transcribe/live") as ws:
            msg = ws.receive_json()
            assert msg["error"] == "Too many live transcription sessions"
