"""A live transcription session cannot grow without bound.

Regression tests for the security audit: /api/transcribe/live kept every
byte it received, re-decoded the whole stream with ffmpeg on every message
while nothing decoded, and took min_chunk_duration from the client
unchecked.
"""

import base64

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import realtime_routes
from sift_core.transcribe import realtime_transcriber as rt


@pytest.fixture
def ffmpeg_calls(monkeypatch):
    """Replace ffmpeg: record the stream size and decode nothing."""
    sizes = []

    def fake_convert(webm_bytes, sample_rate=16000):
        sizes.append(len(webm_bytes))
        return np.array([], dtype=np.float32)

    monkeypatch.setattr(rt, "convert_webm_to_pcm", fake_convert)
    return sizes


def _session(**kwargs):
    return rt.RealtimeTranscriptionSession(model_size="tiny", **kwargs)


async def _feed(session, chunk: bytes):
    async for _ in session.process_audio_chunk(chunk):
        pass


class TestAccumulator:
    def test_stream_size_is_capped(self, monkeypatch):
        monkeypatch.setattr(rt, "MAX_SESSION_BYTES", 100)
        acc = rt.WebmAccumulator()
        acc.add_chunk(b"x" * 100)
        with pytest.raises(rt.SessionLimitError):
            acc.add_chunk(b"x")


class TestSession:
    async def test_undecodable_input_is_throttled(self, ffmpeg_calls):
        session = _session(min_chunk_duration=3.0)
        for _ in range(30):
            await _feed(session, b"\0" * 1024)
        # Old behaviour: 30 decodes of a growing stream (quadratic work).
        assert len(ffmpeg_calls) == 1

    async def test_session_gives_up_on_undecodable_input(self, ffmpeg_calls, monkeypatch):
        session = _session(min_chunk_duration=3.0)
        clock = iter(range(0, 10_000, 10))
        monkeypatch.setattr(rt.time, "monotonic", lambda: float(next(clock)))
        with pytest.raises(rt.SessionLimitError):
            for _ in range(rt.MAX_FAILED_DECODES + 1):
                await _feed(session, b"\0" * 1024)
        assert len(ffmpeg_calls) == rt.MAX_FAILED_DECODES


class TestRoute:
    @pytest.fixture
    def client(self, ffmpeg_calls):
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
