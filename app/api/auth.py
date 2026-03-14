"""Optional API authentication via X-API-Key header."""

import hmac

from fastapi import Header, HTTPException

from ..config import get_settings


async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    """
    Verify API key if authentication is enabled.

    If API_KEY is not set in config, authentication is disabled (open access).
    If API_KEY is set, requests must include a matching X-API-Key header.

    Usage:
        # In .env file:
        API_KEY=your-secret-key

        # In requests:
        curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/health
    """
    settings = get_settings()

    # Auth disabled if no API_KEY configured
    if settings.api_key is None:
        return

    # Auth enabled - verify header
    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
