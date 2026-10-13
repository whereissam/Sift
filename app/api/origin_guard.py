"""Keep other websites (and DNS-rebound hostnames) away from the local API.

Sift binds to 127.0.0.1 with no API key by default, so a page on any site
the user visits can reach it. CORS only stops that page reading responses:
a form POST, an ``<img>`` GET or a WebSocket still reaches the handler. This
middleware rejects those requests before routing, whether or not API_KEY is
set.

- State-changing requests (anything but GET/HEAD/OPTIONS) and WebSocket
  upgrades are refused when they come from an origin that is not trusted.
- When the server is bound to loopback, requests must name a loopback Host,
  so a hostname rebound to 127.0.0.1 cannot talk to the API.

Requests from non-browser clients (CLI, MCP, curl, webhooks) carry no Origin
or Sec-Fetch-Site header and are unaffected.
"""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Browser extensions and the Tauri desktop shell are first-party clients.
_EXTENSION_SCHEMES = ("chrome-extension", "moz-extension", "safari-web-extension")
_TAURI_ORIGINS = frozenset(
    {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _host_of(host_header: str) -> str:
    """Hostname from a Host header value, lowercased, without the port."""
    try:
        return (urlsplit(f"//{host_header}").hostname or "").lower()
    except ValueError:
        return ""


class OriginPolicy:
    """Decides which browser origins may call the API."""

    def __init__(self, cors_origins: Iterable[str]):
        origins = [o.rstrip("/") for o in cors_origins]
        self.allow_any = "*" in origins
        self.origins = frozenset(origins)

    def is_trusted_origin(self, origin: str, host_header: str) -> bool:
        if self.allow_any or origin in self.origins or origin in _TAURI_ORIGINS:
            return True
        try:
            parts = urlsplit(origin)
        except ValueError:
            return False
        if parts.scheme in _EXTENSION_SCHEMES:
            return True
        # Same origin: the page was served by this host (e.g. nginx in front
        # of the API passes the browser's Host through).
        return bool(parts.netloc) and parts.netloc.lower() == host_header.lower()

    def is_cross_site(self, headers: Headers) -> bool:
        """True when a browser sent this request on behalf of another site."""
        # Custom headers cannot be attached to a cross-site request without a
        # CORS preflight, which CORSMiddleware already refuses.
        if headers.get("x-api-key") or headers.get("authorization"):
            return False
        origin = headers.get("origin")
        if origin is not None:
            # "null" is sent by sandboxed frames and opaque redirects.
            return origin == "null" or not self.is_trusted_origin(
                origin, headers.get("host", "")
            )
        return headers.get("sec-fetch-site") in ("cross-site", "same-site")


def policy_from_settings(settings) -> OriginPolicy:
    """The OriginPolicy for the configured CORS origins."""
    raw = settings.cors_origins
    origins = ["*"] if raw == "*" else [o.strip() for o in raw.split(",") if o.strip()]
    return OriginPolicy(origins)


def loopback_only_hosts(bind_host: str, allowed_hosts: Optional[str]) -> Optional[frozenset]:
    """The Host names the API should answer to, or None for any.

    ``allowed_hosts`` ("a,b" or "*") wins when set. Otherwise a server bound
    to loopback answers only to loopback names; a server bound elsewhere
    cannot know its public names, so it accepts any.
    """
    if allowed_hosts:
        names = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
        return None if "*" in names else frozenset(names | LOOPBACK_HOSTS)
    if bind_host.strip("[]").lower() in LOOPBACK_HOSTS:
        return LOOPBACK_HOSTS
    return None


class OriginGuardMiddleware:
    """ASGI middleware: refuse cross-site writes, WebSockets and foreign Hosts."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        policy: OriginPolicy,
        allowed_hosts: Optional[frozenset] = None,
    ):
        self.app = app
        self.policy = policy
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        reason = None
        if (
            self.allowed_hosts is not None
            and _host_of(headers.get("host", "")) not in self.allowed_hosts
        ):
            reason = "Host not allowed"
        elif (
            scope["type"] == "websocket" or scope.get("method") not in SAFE_METHODS
        ) and self.policy.is_cross_site(headers):
            reason = "Cross-origin request rejected"

        if reason is None:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await WebSocketClose(code=1008, reason=reason)(scope, receive, send)
        else:
            status = 400 if reason == "Host not allowed" else 403
            await JSONResponse({"detail": reason}, status_code=status)(scope, receive, send)
