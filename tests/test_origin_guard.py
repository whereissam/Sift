"""Other websites must not be able to change data through the local API.

Regression tests for the security audit: with API_KEY unset, a page on any
site could delete every job with a form POST to /api/cleanup, start
downloads with an <img> pointing at /api/add, and open the live WebSocket.
"""

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.origin_guard import (
    LOOPBACK_HOSTS,
    OriginGuardMiddleware,
    OriginPolicy,
    loopback_only_hosts,
)
from app.main import app as sift_app

EVIL = "https://evil.example"
SPA = "http://localhost:5173"


def _guarded_app(allowed_hosts=LOOPBACK_HOSTS):
    app = FastAPI()

    @app.get("/read")
    async def read():
        return {"ok": True}

    @app.post("/write")
    async def write():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.add_middleware(
        OriginGuardMiddleware,
        policy=OriginPolicy([SPA]),
        allowed_hosts=allowed_hosts,
    )
    return TestClient(app, base_url="http://localhost:8000")


class TestOriginGuard:
    def test_cross_site_post_is_refused(self):
        client = _guarded_app()
        assert client.post("/write", headers={"Origin": EVIL}).status_code == 403

    def test_cross_site_post_without_origin_is_refused(self):
        client = _guarded_app()
        r = client.post("/write", headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403

    def test_opaque_origin_is_refused(self):
        client = _guarded_app()
        assert client.post("/write", headers={"Origin": "null"}).status_code == 403

    @pytest.mark.parametrize(
        "origin",
        [
            SPA,
            "http://localhost:8000",  # same origin
            "chrome-extension://abcdefghijklmnop",
            "moz-extension://1234-5678",
            "tauri://localhost",
        ],
    )
    def test_first_party_origins_may_write(self, origin):
        client = _guarded_app()
        assert client.post("/write", headers={"Origin": origin}).status_code == 200

    def test_non_browser_clients_are_unaffected(self):
        client = _guarded_app()
        assert client.post("/write").status_code == 200

    def test_api_key_header_is_not_ambient(self):
        client = _guarded_app()
        r = client.post("/write", headers={"Origin": EVIL, "X-API-Key": "k"})
        assert r.status_code == 200

    def test_cross_site_reads_still_reach_cors(self):
        client = _guarded_app()
        assert client.get("/read", headers={"Origin": EVIL}).status_code == 200

    def test_cross_site_websocket_is_refused(self):
        client = _guarded_app()
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws", headers={"Origin": EVIL, "Host": "localhost:8000"}) as ws:
                ws.receive_text()
        assert exc.value.code == 1008
        assert exc.value.reason == "Cross-origin request rejected"

    def test_first_party_websocket_connects(self):
        client = _guarded_app()
        with client.websocket_connect("/ws", headers={"Origin": SPA, "Host": "localhost:8000"}) as ws:
            assert ws.receive_text() == "hi"

    def test_rebound_host_is_refused(self):
        client = _guarded_app()
        r = client.get("/read", headers={"Host": "rebind.evil.example:8000"})
        assert r.status_code == 400

    def test_any_host_when_not_restricted(self):
        client = _guarded_app(allowed_hosts=None)
        r = client.get("/read", headers={"Host": "sift.lan:8000"})
        assert r.status_code == 200


class TestLoopbackOnlyHosts:
    def test_loopback_bind_restricts_hosts(self):
        assert loopback_only_hosts("127.0.0.1", None) == LOOPBACK_HOSTS

    def test_public_bind_allows_any_host(self):
        assert loopback_only_hosts("0.0.0.0", None) is None

    def test_explicit_hosts_extend_loopback(self):
        hosts = loopback_only_hosts("127.0.0.1", "sift.lan, Box.local")
        assert {"sift.lan", "box.local", "localhost"} <= hosts

    def test_star_allows_any_host(self):
        assert loopback_only_hosts("127.0.0.1", "*") is None


class TestSiftRoutes:
    @pytest.fixture
    def client(self):
        return TestClient(sift_app, base_url="http://localhost")

    def test_cross_site_cleanup_is_refused(self, client):
        r = client.post(
            "/api/cleanup?delete_all=true&max_age_hours=1",
            headers={"Origin": EVIL},
        )
        assert r.status_code == 403

    def test_negative_cleanup_age_is_rejected(self, client):
        r = client.post("/api/cleanup?max_age_hours=-876000")
        assert r.status_code == 422

    def test_cross_site_image_cannot_quick_add(self, client):
        r = client.get(
            "/api/add",
            params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"},
        )
        assert r.status_code == 403

    def test_cross_site_navigation_gets_confirmation_page(self, client):
        url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ"><script>x</script>'
        r = client.get(
            "/api/add",
            params={"url": url, "action": "download"},
            headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert '<form method=post action="/api/add">' in r.text
        assert "<script>" not in r.text

    def test_cross_site_confirm_post_is_refused(self, client):
        r = client.post(
            "/api/add",
            data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Origin": EVIL},
        )
        assert r.status_code == 403

    def test_unknown_quick_add_action_is_rejected(self, client):
        r = client.get(
            "/api/add",
            params={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "action": "x"},
        )
        assert r.status_code == 400
