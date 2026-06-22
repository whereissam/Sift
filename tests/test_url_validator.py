"""Tests for SSRF URL validation and safe fetch helpers."""

from unittest.mock import patch

import pytest

from app.core.url_validator import (
    _PinnedTransport,
    _resolve_and_pin,
    safe_get,
    safe_stream,
    validate_url_ssrf,
)


def _fake_getaddrinfo(ip: str):
    """Build a getaddrinfo replacement that always resolves to a fixed IP."""
    family = 10 if ":" in ip else 2  # AF_INET6 / AF_INET

    def _resolver(host, *args, **kwargs):
        return [(family, 1, 6, "", (ip, 0))]

    return _resolver


class TestValidateUrlSsrf:
    """Tests for validate_url_ssrf."""

    def test_rejects_non_http_scheme(self):
        ok, err = validate_url_ssrf("file:///etc/passwd")
        assert ok is False
        assert err is not None

    def test_rejects_missing_hostname(self):
        ok, err = validate_url_ssrf("http://")
        assert ok is False

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.5",
            "172.16.0.1",
            "192.168.1.1",
            "127.0.0.1",
            "169.254.169.254",  # AWS metadata (link-local)
            "100.100.100.200",  # Alibaba metadata
            "100.64.0.1",  # CGNAT
            "0.0.0.0",  # unspecified
            "240.0.0.1",  # reserved / Class E
            "224.0.0.1",  # multicast
            "::1",  # IPv6 loopback
            "::ffff:169.254.169.254",  # IPv4-mapped IPv6
        ],
    )
    def test_blocks_private_and_reserved(self, ip):
        with patch("socket.getaddrinfo", _fake_getaddrinfo(ip)):
            ok, err = validate_url_ssrf("http://evil.example.com/")
        assert ok is False, f"{ip} should be blocked"
        assert err is not None

    def test_allows_public_ip(self):
        with patch("socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")):
            ok, err = validate_url_ssrf("https://example.com/")
        assert ok is True
        assert err is None


class TestSafeFetchHelpers:
    """Tests that the safe fetch helpers reject blocked URLs."""

    @pytest.mark.asyncio
    async def test_safe_get_rejects_blocked_url(self):
        with patch("socket.getaddrinfo", _fake_getaddrinfo("169.254.169.254")):
            with pytest.raises(ValueError):
                await safe_get("http://metadata.example.com/")

    @pytest.mark.asyncio
    async def test_safe_stream_rejects_blocked_url(self):
        with patch("socket.getaddrinfo", _fake_getaddrinfo("100.100.100.200")):
            with pytest.raises(ValueError):
                async with safe_stream("http://metadata.example.com/"):
                    pass


class TestDnsPinning:
    """Tests for the DNS-pinning resolver and transport."""

    def test_resolve_and_pin_returns_validated_ip(self):
        with patch("socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")):
            assert _resolve_and_pin("example.com") == "93.184.216.34"

    def test_resolve_and_pin_rejects_blocked_ip(self):
        # The classic rebinding payload: a public-looking host now resolving
        # to the cloud metadata endpoint.
        with patch("socket.getaddrinfo", _fake_getaddrinfo("169.254.169.254")):
            with pytest.raises(ValueError):
                _resolve_and_pin("rebind.example.com")

    def test_resolve_and_pin_unresolvable(self):
        import socket

        def _boom(*a, **k):
            raise socket.gaierror("no such host")

        with patch("socket.getaddrinfo", _boom):
            with pytest.raises(ValueError):
                _resolve_and_pin("nope.invalid")

    @pytest.mark.asyncio
    async def test_pinned_transport_rewrites_host_and_sets_sni(self):
        import httpx

        captured = {}

        async def _fake_super(self, request):
            captured["host"] = request.url.host
            captured["sni"] = request.extensions.get("sni_hostname")
            captured["host_header"] = request.headers.get("host")
            return httpx.Response(200)

        transport = _PinnedTransport()
        req = httpx.Request("GET", "https://example.com/path")
        with patch("socket.getaddrinfo", _fake_getaddrinfo("93.184.216.34")):
            with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super):
                await transport.handle_async_request(req)

        # Connection is pinned to the validated IP, but TLS/cert still use the
        # original hostname via sni_hostname (and the Host header is preserved).
        assert captured["host"] == "93.184.216.34"
        assert captured["sni"] == "example.com"
        assert captured["host_header"] == "example.com"

    @pytest.mark.asyncio
    async def test_pinned_transport_blocks_rebind(self):
        import httpx

        transport = _PinnedTransport()
        req = httpx.Request("GET", "https://rebind.example.com/")
        with patch("socket.getaddrinfo", _fake_getaddrinfo("169.254.169.254")):
            with pytest.raises(ValueError):
                await transport.handle_async_request(req)
