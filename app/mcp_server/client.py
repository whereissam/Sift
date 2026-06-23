"""Async HTTP client for the Sift REST API, used by the MCP tools.

Thin wrapper over ``httpx.AsyncClient`` that:
  * targets the configured Sift base URL,
  * attaches the ``X-API-Key`` header when a key is configured (passthrough),
  * normalizes errors into ``SiftAPIError`` with the server's detail message,
  * exposes one method per endpoint the MCP tools need, plus the small
    compositions the API doesn't offer directly (per-episode entities / topics /
    predictions, transcript-segment slicing).

The underlying ``httpx.AsyncClient`` is injectable so tests can drive the tools
against an in-process FastAPI app (ASGI transport) with no network.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import MCPConfig


class SiftAPIError(Exception):
    """Raised when the Sift API returns an error or is unreachable.

    ``status`` is the HTTP status (or ``None`` for transport-level failures);
    ``detail`` is the server-supplied message when present.
    """

    def __init__(self, message: str, *, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class SiftClient:
    """Async client over the Sift API. One method per MCP-relevant endpoint."""

    def __init__(
        self,
        config: MCPConfig,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self._config = config
        self._owns_client = http_client is None
        headers = {"X-API-Key": config.api_key} if config.api_key else {}
        self._client = http_client or httpx.AsyncClient(
            base_url=config.api_base,
            headers=headers,
            timeout=config.timeout,
        )
        # When a client is injected (tests / ASGI), make sure the key still
        # rides along — the caller may not have set it.
        if http_client is not None and config.api_key:
            self._client.headers.setdefault("X-API-Key", config.api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "SiftClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ===== low-level =====

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> tuple[int, Any]:
        """Return ``(status_code, parsed_body)``. Raise ``SiftAPIError`` on
        transport failure or any ``>= 400`` response. ``2xx`` (incl. ``202``)
        is returned so callers can branch on, e.g., a pending extraction."""
        try:
            resp = await self._client.request(method, path, params=params, json=json)
        except httpx.HTTPError as e:
            raise SiftAPIError(
                f"Could not reach Sift API at {self._config.api_base}: {e}"
            ) from e

        if resp.status_code >= 400:
            raise SiftAPIError(_error_detail(resp), status=resp.status_code)

        return resp.status_code, _safe_json(resp)

    # ===== ingest / transcript =====

    async def transcribe(
        self,
        *,
        url: Optional[str] = None,
        job_id: Optional[str] = None,
        language: Optional[str] = None,
        diarize: bool = False,
    ) -> dict:
        """POST /api/transcribe — submit a URL (or a completed download job)."""
        body: dict[str, Any] = {"diarize": diarize}
        if url:
            body["url"] = url
        if job_id:
            body["job_id"] = job_id
        if language:
            body["language"] = language
        _, data = await self._request("POST", "/api/transcribe", json=body)
        return data

    async def get_transcription(self, job_id: str) -> dict:
        """GET /api/transcribe/{job_id} — full job incl. segments + text."""
        _, data = await self._request("GET", f"/api/transcribe/{job_id}")
        return data

    # ===== summary / clips =====

    async def summarize(self, job_id: str, summary_type: str) -> dict:
        """POST /api/summarize/job/{job_id}?summary_type=… (generate-on-demand)."""
        _, data = await self._request(
            "POST",
            f"/api/summarize/job/{job_id}",
            params={"summary_type": summary_type},
        )
        return data

    async def get_clips(self, job_id: str) -> dict:
        """GET /api/jobs/{job_id}/clips — previously generated clips."""
        _, data = await self._request("GET", f"/api/jobs/{job_id}/clips")
        return data

    # ===== knowledge (P18) =====

    async def get_knowledge(
        self, job_id: str, *, min_confidence: float = 0.5
    ) -> tuple[int, dict]:
        """GET /api/jobs/{job_id}/knowledge. Returns ``(status, body)`` so the
        caller can tell a cached result (200) from a still-extracting one (202)."""
        return await self._request(
            "GET",
            f"/api/jobs/{job_id}/knowledge",
            params={"min_confidence": min_confidence},
        )

    async def get_entity(self, id_or_slug: str) -> dict:
        _, data = await self._request("GET", f"/api/entities/{id_or_slug}")
        return data

    async def get_topic(self, topic_id: str) -> dict:
        _, data = await self._request("GET", f"/api/topics/{topic_id}")
        return data

    async def get_prediction(self, claim_id: str) -> dict:
        _, data = await self._request("GET", f"/api/predictions/{claim_id}")
        return data

    # ===== export (P21) =====

    async def export_job(self, job_id: str, body: dict) -> dict:
        """POST /api/jobs/{job_id}/export — render + (optionally) write a note."""
        _, data = await self._request("POST", f"/api/jobs/{job_id}/export", json=body)
        return data


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def _error_detail(resp: httpx.Response) -> str:
    """Pull FastAPI's ``{"detail": ...}`` when present, else a generic line."""
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return f"Sift API {resp.status_code}: {body['detail']}"
    except ValueError:
        pass
    return f"Sift API returned HTTP {resp.status_code}"
