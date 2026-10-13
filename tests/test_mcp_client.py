"""Tests for the Sift MCP HTTP client (app/mcp_server/client.py).

Drives the client against an in-process ``httpx.MockTransport`` so we assert the
exact path / params / headers it sends and how it maps responses + errors —
no network, no running Sift server.
"""

from __future__ import annotations

import httpx
import pytest

from app.mcp_server.client import SiftAPIError, SiftClient
from app.mcp_server.config import MCPConfig


def _client(handler, *, api_key: str | None = None) -> SiftClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://sift.test")
    cfg = MCPConfig(api_url="http://sift.test", api_key=api_key)
    return SiftClient(cfg, http_client=http)


class TestRequests:
    @pytest.mark.asyncio
    async def test_transcribe_posts_url(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            import json

            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"job_id": "j1", "status": "processing"})

        client = _client(handler)
        job = await client.transcribe(url="https://x.com/ep", diarize=True)
        assert job["job_id"] == "j1"
        assert seen["method"] == "POST"
        assert seen["path"] == "/api/transcribe"
        assert seen["body"] == {"url": "https://x.com/ep", "diarize": True}

    @pytest.mark.asyncio
    async def test_summarize_sends_mode_as_query(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["mode"] = request.url.params.get("summary_type")
            return httpx.Response(200, json={"content": "• point"})

        client = _client(handler)
        out = await client.summarize("j1", "bullet_points")
        assert out["content"] == "• point"
        assert seen["path"] == "/api/summarize/job/j1"
        assert seen["mode"] == "bullet_points"

    @pytest.mark.asyncio
    async def test_get_knowledge_returns_status_and_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json={"run_state": "pending"})

        client = _client(handler)
        status, body = await client.get_knowledge("j1", min_confidence=0.7)
        # 202 must NOT raise — the caller branches on it.
        assert status == 202
        assert body["run_state"] == "pending"

    @pytest.mark.asyncio
    async def test_api_key_header_sent(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["key"] = request.headers.get("X-API-Key")
            return httpx.Response(200, json={})

        client = _client(handler, api_key="secret-123")
        await client.get_transcription("j1")
        assert seen["key"] == "secret-123"


class TestErrors:
    @pytest.mark.asyncio
    async def test_404_maps_to_sift_api_error_with_detail(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Job not found"})

        client = _client(handler)
        with pytest.raises(SiftAPIError) as exc:
            await client.get_transcription("ghost")
        assert exc.value.status == 404
        assert "Job not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_transport_error_maps_to_sift_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _client(handler)
        with pytest.raises(SiftAPIError) as exc:
            await client.get_clips("j1")
        assert exc.value.status is None
        assert "Could not reach Sift API" in str(exc.value)


class TestIdsStayInOnePathSegment:
    """An id can never reach another endpoint (security audit regression)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "job_id",
        [
            "../cleanup?delete_all=true&max_age_hours=0#",
            "../../add?url=https://www.youtube.com/watch?v=x&action=download",
            "a/b",
            "x#frag",
        ],
    )
    async def test_path_tricks_are_encoded(self, job_id):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.raw_path.decode()))
            return httpx.Response(200, json={})

        client = _client(handler)
        await client.analyze_contradictions(job_id)
        await client.get_transcription(job_id)
        (post, get) = seen
        assert post[0] == "POST"
        assert post[1].startswith("/api/jobs/") and post[1].endswith("/analyze-contradictions")
        assert post[1].count("/") == 4 and "?" not in post[1]
        assert get[1].startswith("/api/transcribe/") and get[1].count("/") == 3
        assert "?" not in get[1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("job_id", ["..", ".", "", None])
    async def test_dot_segments_are_refused(self, job_id):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"request sent: {request.url}")

        client = _client(handler)
        with pytest.raises(SiftAPIError):
            await client.analyze_contradictions(job_id)

    @pytest.mark.asyncio
    async def test_int_ids_still_work(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={})

        await _client(handler).get_topic(42)
        assert seen == ["/api/topics/42"]
