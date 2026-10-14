"""S3 requests connect only to the address that passed the SSRF check.

Validating endpoint_url once left a DNS-rebinding window: botocore resolved
the name again for every connection. Requests to a caller-supplied endpoint
now go through a pinned client from botocore's before-send hook.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("boto3")

from app.config import get_settings  # noqa: E402
from app.delivery.cloud.base import ProviderConfig, ProviderType  # noqa: E402
from app.delivery.cloud.s3 import S3Provider, endpoint_needs_pinning  # noqa: E402

_real_getaddrinfo = socket.getaddrinfo

LIST_BUCKETS = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    b"<Owner><ID>o</ID></Owner><Buckets><Bucket><Name>media</Name>"
    b"<CreationDate>2026-01-01T00:00:00.000Z</CreationDate></Bucket></Buckets>"
    b"</ListAllMyBucketsResult>"
)


@pytest.fixture
def fake_s3():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, status, body=b"", headers=()):
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            hits.append(("GET", self.path, self.headers.get("Host"), self.headers.get("Authorization", "")))
            self._reply(200, LIST_BUCKETS, [("Content-Type", "application/xml")])

        def do_PUT(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            hits.append(("PUT", self.path, self.headers.get("Host"), body))
            self._reply(200, headers=[("ETag", '"abc"')])

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], hits
    server.shutdown()


def _resolve(monkeypatch, ip):
    def resolver(host, *args, **kwargs):
        if host == "s3.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
        return _real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolver)


def _provider(port):
    return S3Provider(
        ProviderConfig(
            id="p",
            provider_type=ProviderType.S3,
            name="p",
            credentials={"access_key_id": "AKIADUMMY", "secret_access_key": "x"},
            settings={"bucket": "media", "endpoint_url": f"http://s3.test:{port}"},
        )
    )


def test_requests_go_through_the_pinned_client(monkeypatch, fake_s3):
    port, hits = fake_s3
    _resolve(monkeypatch, "127.0.0.1")
    # Treat the loopback fixture as a public address for this test.
    monkeypatch.setattr("sift_core.fetch.url_validator._ip_block_reason", lambda ip: None)
    client = _provider(port)._get_client()

    buckets = client.list_buckets()["Buckets"]
    client.put_object(Bucket="media", Key="ep.m4a", Body=b"audio-bytes")

    assert [b["Name"] for b in buckets] == ["media"]
    (get, put) = hits
    assert get[2] == f"s3.test:{port}"  # hostname kept for SigV4 / virtual hosting
    assert get[3].startswith("AWS4-HMAC-SHA256 Credential=AKIADUMMY/")
    assert put[:2] == ("PUT", "/media/ep.m4a") and put[3] == b"audio-bytes"


def test_rebound_name_never_reaches_the_internal_address(monkeypatch, fake_s3):
    port, hits = fake_s3
    _resolve(monkeypatch, "93.184.216.34")  # public when the client is built
    client = _provider(port)._get_client()
    _resolve(monkeypatch, "127.0.0.1")  # then rebinds to loopback

    with pytest.raises(Exception, match="private/reserved"):
        client.list_buckets()
    assert hits == []


def test_operator_allowlisted_endpoint_is_not_pinned(monkeypatch):
    monkeypatch.setattr(get_settings(), "s3_allowed_endpoints", "minio:9000")
    assert not endpoint_needs_pinning("http://minio:9000")
    assert not endpoint_needs_pinning(None)
    assert endpoint_needs_pinning("https://s3.example.com")
