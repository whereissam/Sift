"""Custom middleware for the API."""

import asyncio
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import get_settings
from ..logging_config import get_logger, request_id_ctx

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID for tracing."""

    async def dispatch(self, request: Request, call_next):
        # Use existing request ID from header or generate new one
        raw_id = request.headers.get("X-Request-ID") or ""
        # Sanitize: only allow alphanumeric, hyphens, max 36 chars
        import re
        sanitized_id = re.sub(r"[^a-zA-Z0-9\-]", "", raw_id)[:36]
        request_id = sanitized_id if sanitized_id else str(uuid.uuid4())[:8]

        # Store in context for logging
        token = request_id_ctx.set(request_id)

        try:
            response = await call_next(request)
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware to add request timeout."""

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        timeout = settings.request_timeout

        try:
            return await asyncio.wait_for(
                call_next(request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "request_timeout",
                timeout=timeout,
                method=request.method,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=504,
                content={"detail": f"Request timeout after {timeout} seconds"},
            )
