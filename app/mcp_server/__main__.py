"""Entry point for the Sift MCP server: ``sift-mcp`` (or ``python -m app.mcp_server``).

Runs over stdio by default — the transport Claude Desktop and most local agent
hosts speak. Configure the target Sift instance via ``SIFT_API_URL`` /
``SIFT_API_KEY`` (see ``config.py``).
"""

from __future__ import annotations

import logging
import os

from .config import load_config
from .server import build_server


def main() -> None:
    logging.basicConfig(
        level=os.getenv("SIFT_MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    logging.getLogger(__name__).info(
        "Starting sift-mcp (api=%s, auth=%s)",
        config.api_base,
        "on" if config.api_key else "off",
    )
    server = build_server(config)
    # stdio transport — Claude Desktop, Cursor (local), and raw MCP clients.
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
