"""Outbound requests built from API input must not reach internal addresses.

Regression tests for the security audit: webhooks validated the URL and
then reconnected through a fresh DNS lookup (DNS rebinding reached
loopback, and /api/webhooks/test echoed the internal response), and an S3
provider's endpoint_url was never validated at all.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.delivery.cloud.s3 import validate_endpoint_url
from app.delivery.webhook_notifier import WebhookNotifier

_real_getaddrinfo = socket.getaddrinfo


@pytest.fixture
def internal_server():
    """A loopback service that answers 500 with a secret body."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = b"INTERNAL-ONLY marker"
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], hits
    server.shutdown()


def _rebinding_resolver(monkeypatch):
    """rebind.test answers a public IP once, then loopback (TTL 0)."""
    calls = []

    def resolver(host, *args, **kwargs):
        if host == "rebind.test":
            calls.append(host)
            ip = "93.184.216.34" if len(calls) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
        return _real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    return calls


class TestWebhookRebinding:
    async def test_rebound_name_never_reaches_loopback(self, monkeypatch, internal_server):
        port, hits = internal_server
        calls = _rebinding_resolver(monkeypatch)

        notifier = WebhookNotifier()
        notifier._retry_delay = 0
        ok, error = await notifier.send_test(f"http://rebind.test:{port}/internal/admin")

        assert ok is False
        assert len(calls) >= 2  # validated once, re-resolved at connect
        assert hits == []
        assert "INTERNAL-ONLY" not in (error or "")

    async def test_error_reports_status_not_body(self, monkeypatch, internal_server):
        port, hits = internal_server
        # Pretend loopback is public so the request is delivered.
        monkeypatch.setattr(
            "sift_core.fetch.url_validator._ip_block_reason", lambda ip: None
        )
        monkeypatch.setattr(
            "app.delivery.webhook_notifier._validate_webhook_url", lambda url: (True, None)
        )

        notifier = WebhookNotifier()
        notifier._retry_delay = 0
        ok, error = await notifier.send_test(f"http://127.0.0.1:{port}/hook")

        assert ok is False
        assert hits and set(hits) == {"/hook"}
        assert error == "HTTP 500"


class TestS3Endpoint:
    @pytest.fixture(autouse=True)
    def _allowlist(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "s3_allowed_endpoints", "minio:9000")

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://127.0.0.1:9000",
            "http://169.254.169.254",
            "http://10.0.0.5:9000",
            "file:///etc/passwd",
            "minio:9000",  # no scheme
        ],
    )
    def test_private_or_malformed_endpoints_are_refused(self, endpoint):
        with pytest.raises(ValueError):
            validate_endpoint_url(endpoint)

    def test_operator_allowlisted_private_endpoint_is_allowed(self):
        validate_endpoint_url("http://minio:9000")

    def test_no_endpoint_means_aws(self):
        validate_endpoint_url(None)

    def test_create_provider_rejects_internal_endpoint(self):
        from app.api.cloud_routes import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        r = TestClient(app).post(
            "/api/cloud/providers",
            json={
                "id": "evil",
                "provider_type": "s3",
                "name": "evil",
                "credentials": {"access_key_id": "A", "secret_access_key": "B"},
                "settings": {"bucket": "b", "endpoint_url": "http://127.0.0.1:9000"},
            },
        )
        assert r.status_code == 400
        assert "endpoint_url" in r.json()["detail"]
