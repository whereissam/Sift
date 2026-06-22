"""Tests for SSRF URL validation and safe fetch helpers."""

from unittest.mock import patch

import pytest

from app.core.url_validator import safe_get, safe_stream, validate_url_ssrf


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
