"""Sift MCP server (P19) — a Model Context Protocol capability surface.

Exposes Sift's primitives (ingest, transcript, summary, clips, and the P18
knowledge layer) as MCP tools so Claude Desktop, Cursor, and custom agents can
call them directly. The server is a thin HTTP client of the Sift REST API with
``X-API-Key`` passthrough — it works against a local or remote Sift instance and
holds no database coupling of its own.

This first pass ships the tools backed by P18 + existing routes. Tools that
depend on unbuilt phases (RAG/P11, semantic search/P10, cross-episode
synthesis/P13+P20, vault export/P21) are intentionally omitted until their
substrate exists.
"""

from .client import SiftAPIError, SiftClient
from .config import MCPConfig, load_config
from .server import build_server

__all__ = [
    "SiftClient",
    "SiftAPIError",
    "MCPConfig",
    "load_config",
    "build_server",
]
