"""Configuration for the Sift MCP server.

Deliberately decoupled from the heavy ``app.config`` settings — the MCP server
is a standalone process that only needs to know where the Sift API lives and
which key to present. Everything comes from the environment so the same binary
works in Claude Desktop, Cursor, or a remote agent host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 120.0


@dataclass(frozen=True)
class MCPConfig:
    """Resolved MCP server configuration."""

    api_url: str = DEFAULT_API_URL
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT

    @property
    def api_base(self) -> str:
        """Base for `/api/...` paths, with any trailing slash trimmed."""
        return self.api_url.rstrip("/")


def load_config() -> MCPConfig:
    """Build config from the environment.

    - ``SIFT_API_URL`` — base URL of the Sift server (default localhost:8000)
    - ``SIFT_API_KEY`` — value sent as ``X-API-Key`` (omit if Sift auth is off)
    - ``SIFT_MCP_TIMEOUT`` — per-request timeout in seconds
    """
    raw_timeout = os.getenv("SIFT_MCP_TIMEOUT")
    try:
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    return MCPConfig(
        api_url=os.getenv("SIFT_API_URL", DEFAULT_API_URL),
        api_key=os.getenv("SIFT_API_KEY") or None,
        timeout=timeout,
    )
