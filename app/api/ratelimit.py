"""Rate limiting using slowapi."""

import ipaddress

from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from ..config import get_settings

# Trusted proxy IPs - only trust X-Forwarded-For from these addresses
_TRUSTED_PROXIES = {
    ipaddress.ip_address("127.0.0.1"),
    ipaddress.ip_address("::1"),
}


def get_real_ip(request) -> str:
    """Get client IP, checking X-Forwarded-For only from trusted proxies."""
    client_ip = get_remote_address(request)

    try:
        if ipaddress.ip_address(client_ip) in _TRUSTED_PROXIES:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
    except ValueError:
        pass

    return client_ip


settings = get_settings()

# Create limiter instance
# If rate limiting is disabled, use a very high limit effectively disabling it
limiter = Limiter(
    key_func=get_real_ip,
    default_limits=[settings.rate_limit] if settings.rate_limit_enabled else [],
    enabled=settings.rate_limit_enabled,
)


class WriteRateLimitMiddleware(SlowAPIMiddleware):
    """Apply ``default_limits`` to state-changing requests only.

    Routes with their own ``@limiter.limit`` keep that limit. Reads are left
    alone: the web UI polls job status every few seconds, and a per-IP
    default would throttle it.
    """

    async def dispatch(self, request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        return await super().dispatch(request, call_next)
