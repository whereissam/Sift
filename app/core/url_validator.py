"""URL validation utilities to prevent SSRF attacks."""

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Private/reserved IP ranges that should not be targeted by server-side requests
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (covers AWS 169.254.169.254)
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT (RFC 6598)
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("240.0.0.0/4"),  # reserved / Class E
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]


def validate_url_ssrf(url: str) -> tuple[bool, str | None]:
    """Validate a URL to prevent SSRF attacks.

    Checks that the URL uses http/https, has a valid hostname,
    and does not resolve to a private/reserved IP address.

    Returns:
        (is_valid, error_message) — error_message is None when valid.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed."

    if not parsed.hostname:
        return False, "URL has no hostname"

    try:
        addrs = socket.getaddrinfo(parsed.hostname, None)
        for _, _, _, _, sockaddr in addrs:
            ip = ipaddress.ip_address(sockaddr[0])

            # Reject unspecified (0.0.0.0 / ::) and multicast explicitly
            if ip.is_unspecified:
                return False, "URL resolves to the unspecified address"
            if ip.is_multicast:
                return False, "URL resolves to a multicast address"

            for network in BLOCKED_NETWORKS:
                if ip in network:
                    return False, "URL resolves to a private/reserved IP address"
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {parsed.hostname}"

    return True, None


async def safe_get(
    url: str,
    *,
    client_kwargs: Optional[dict] = None,
    max_redirects: int = 5,
    **get_kwargs,
) -> httpx.Response:
    """Perform an SSRF-safe GET request.

    Validates the URL (and every redirect Location) with validate_url_ssrf,
    disables httpx auto-redirects, and follows 3xx redirects manually after
    re-validating each hop.

    Raises:
        ValueError: if the URL or any redirect target is blocked.
    """
    is_valid, error = validate_url_ssrf(url)
    if not is_valid:
        raise ValueError(f"Blocked URL: {error}")

    client_kwargs = dict(client_kwargs or {})
    get_kwargs.pop("follow_redirects", None)

    async with httpx.AsyncClient(**client_kwargs) as client:
        current_url = url
        for _ in range(max_redirects + 1):
            resp = await client.get(current_url, follow_redirects=False, **get_kwargs)
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    return resp
                next_url = str(resp.url.join(location))
                is_valid, error = validate_url_ssrf(next_url)
                if not is_valid:
                    raise ValueError(f"Blocked redirect URL: {error}")
                current_url = next_url
                continue
            return resp

        raise ValueError(f"Too many redirects (>{max_redirects}) for URL: {url}")


def safe_stream(
    url: str,
    *,
    method: str = "GET",
    client_kwargs: Optional[dict] = None,
    max_redirects: int = 5,
    **request_kwargs,
):
    """Return an async context manager yielding an SSRF-safe streaming response.

    Validates the URL (and every redirect Location) with validate_url_ssrf,
    disables httpx auto-redirects, and follows 3xx redirects manually after
    re-validating each hop.

    Usage:
        async with safe_stream(url, timeout=300.0) as resp:
            async for chunk in resp.aiter_bytes():
                ...

    Raises:
        ValueError: if the URL or any redirect target is blocked.
    """
    return _SafeStream(
        url,
        method=method,
        client_kwargs=client_kwargs,
        max_redirects=max_redirects,
        request_kwargs=request_kwargs,
    )


class _SafeStream:
    """Async context manager backing safe_stream."""

    def __init__(self, url, *, method, client_kwargs, max_redirects, request_kwargs):
        self._url = url
        self._method = method
        self._client_kwargs = dict(client_kwargs or {})
        self._max_redirects = max_redirects
        self._request_kwargs = dict(request_kwargs)
        self._request_kwargs.pop("follow_redirects", None)
        self._client: Optional[httpx.AsyncClient] = None
        self._stream_cm = None

    async def __aenter__(self) -> httpx.Response:
        is_valid, error = validate_url_ssrf(self._url)
        if not is_valid:
            raise ValueError(f"Blocked URL: {error}")

        self._client = httpx.AsyncClient(**self._client_kwargs)
        await self._client.__aenter__()

        current_url = self._url
        for _ in range(self._max_redirects + 1):
            stream_cm = self._client.stream(
                self._method,
                current_url,
                follow_redirects=False,
                **self._request_kwargs,
            )
            resp = await stream_cm.__aenter__()
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    self._stream_cm = stream_cm
                    return resp
                next_url = str(resp.url.join(location))
                await stream_cm.__aexit__(None, None, None)
                is_valid, error = validate_url_ssrf(next_url)
                if not is_valid:
                    await self._client.__aexit__(None, None, None)
                    self._client = None
                    raise ValueError(f"Blocked redirect URL: {error}")
                current_url = next_url
                continue
            self._stream_cm = stream_cm
            return resp

        await self._client.__aexit__(None, None, None)
        self._client = None
        raise ValueError(
            f"Too many redirects (>{self._max_redirects}) for URL: {self._url}"
        )

    async def __aexit__(self, exc_type, exc, tb):
        if self._stream_cm is not None:
            await self._stream_cm.__aexit__(exc_type, exc, tb)
            self._stream_cm = None
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
            self._client = None
