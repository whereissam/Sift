"""URL validation utilities to prevent SSRF attacks."""

import ipaddress
import socket
from urllib.parse import urlparse

# Private/reserved IP ranges that should not be targeted by server-side requests
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
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
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    return False, "URL resolves to a private/reserved IP address"
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {parsed.hostname}"

    return True, None
