"""Tests for API hardening: auth, SSRF, path containment, column allowlists."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import auth as auth_module
from app.api import obsidian_routes
from app.api import ai_settings_routes
from app.api import realtime_routes
from app.core.subscription_store import SubscriptionStore


class _FakeSettings:
    """Minimal stand-in for app settings used by hardened routes."""

    def __init__(self, api_key=None, download_dir="/tmp/sift-test-downloads"):
        self.api_key = api_key
        self.download_dir = download_dir


@pytest.fixture
def api_key_settings(monkeypatch):
    """Force auth ON by making get_settings return a configured api_key."""
    fake = _FakeSettings(api_key="secret-key")
    monkeypatch.setattr(auth_module, "get_settings", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# 1. realtime router now requires the API key
# ---------------------------------------------------------------------------

def test_realtime_websocket_requires_api_key(api_key_settings):
    app = FastAPI()
    app.include_router(realtime_routes.router)
    client = TestClient(app)

    # Without the key, the websocket dependency rejects the handshake.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/transcribe/live"):
            pass


def test_realtime_status_requires_api_key(api_key_settings):
    app = FastAPI()
    app.include_router(realtime_routes.router)
    client = TestClient(app)

    resp = client.get("/transcribe/live/status")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. ai_settings base_url SSRF rejection
# ---------------------------------------------------------------------------

def _ai_app(monkeypatch):
    # Auth disabled for these tests so we exercise the handler directly.
    monkeypatch.setattr(
        ai_settings_routes, "verify_api_key", lambda: None, raising=False
    )
    app = FastAPI()
    app.include_router(ai_settings_routes.router)
    app.dependency_overrides[ai_settings_routes.verify_api_key] = lambda: None
    return app


def test_ai_settings_rejects_ssrf_base_url(monkeypatch):
    app = _ai_app(monkeypatch)
    client = TestClient(app)

    resp = client.post(
        "/ai/settings",
        json={
            "provider": "custom",
            "model": "gpt-x",
            "api_key": "k",
            "base_url": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"].lower()


def test_ai_test_rejects_ssrf_base_url(monkeypatch):
    app = _ai_app(monkeypatch)
    client = TestClient(app)

    resp = client.post(
        "/ai/test",
        json={
            "provider": "custom",
            "model": "gpt-x",
            "base_url": "http://127.0.0.1:8000/",
        },
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. obsidian vault_path containment rejection
# ---------------------------------------------------------------------------

def _obsidian_app(monkeypatch, download_dir):
    fake = _FakeSettings(download_dir=download_dir)
    monkeypatch.setattr(obsidian_routes, "get_settings", lambda: fake)
    app = FastAPI()
    app.include_router(obsidian_routes.router)
    app.dependency_overrides[obsidian_routes.verify_api_key] = lambda: None
    return app


def test_obsidian_validate_rejects_out_of_scope_path(monkeypatch, tmp_path):
    app = _obsidian_app(monkeypatch, download_dir=str(tmp_path / "downloads"))
    client = TestClient(app)

    resp = client.post("/obsidian/validate", params={"vault_path": "/etc"})
    assert resp.status_code == 400


def test_obsidian_settings_rejects_out_of_scope_path(monkeypatch, tmp_path):
    app = _obsidian_app(monkeypatch, download_dir=str(tmp_path / "downloads"))
    client = TestClient(app)

    resp = client.post(
        "/obsidian/settings",
        json={
            "vault_path": "/etc/cron.d",
            "subfolder": "Sift",
            "template": None,
            "default_tags": ["sift"],
        },
    )
    assert resp.status_code == 400


def test_obsidian_validate_allows_home_path(monkeypatch, tmp_path):
    app = _obsidian_app(monkeypatch, download_dir=str(tmp_path / "downloads"))
    client = TestClient(app)

    # A path under the home dir passes the scope check (may still fail the
    # writable check, but must not be a 400 scope rejection).
    from pathlib import Path

    home_sub = str(Path.home() / "definitely-not-a-real-vault-xyz")
    resp = client.post("/obsidian/validate", params={"vault_path": home_sub})
    assert resp.status_code == 200  # scope OK -> validate_vault runs, returns valid=False


# ---------------------------------------------------------------------------
# 7. subscription_store.update_item rejects unknown columns
# ---------------------------------------------------------------------------

def test_update_item_rejects_unknown_column(tmp_path):
    store = SubscriptionStore(db_path=tmp_path / "subs.db")
    with pytest.raises(ValueError):
        store.update_item("nonexistent-id", evil_column="x")


def test_update_item_allows_known_column(tmp_path):
    store = SubscriptionStore(db_path=tmp_path / "subs.db")
    # Known column should not raise (item doesn't exist, returns None).
    result = store.update_item("nonexistent-id", title="ok")
    assert result is None


# ---------------------------------------------------------------------------
# 8. subscription output_dir path containment (store layer)
# ---------------------------------------------------------------------------

def test_create_subscription_rejects_out_of_scope_output_dir(monkeypatch, tmp_path):
    from app.core import subscription_store as ss
    from app.core.subscription_store import (
        SubscriptionType,
        SubscriptionPlatform,
    )

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    fake = _FakeSettings(download_dir=str(download_dir))
    monkeypatch.setattr(ss, "get_settings", lambda: fake, raising=False)
    # _validate_output_dir imports get_settings from ..config inside the func.
    import app.config as config_module
    monkeypatch.setattr(config_module, "get_settings", lambda: fake)

    store = SubscriptionStore(db_path=tmp_path / "subs.db")
    with pytest.raises(ValueError):
        store.create_subscription(
            subscription_id="s1",
            name="bad",
            subscription_type=SubscriptionType.RSS,
            platform=SubscriptionPlatform.PODCAST,
            output_dir="/etc",
        )


def test_update_subscription_output_dir_scope(monkeypatch, tmp_path):
    """A valid output_dir update is allowed; an out-of-scope one is rejected."""
    from app.core import subscription_store as ss
    from app.core.subscription_store import (
        SubscriptionType,
        SubscriptionPlatform,
    )

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    fake = _FakeSettings(download_dir=str(download_dir))
    monkeypatch.setattr(ss, "get_settings", lambda: fake, raising=False)
    import app.config as config_module
    monkeypatch.setattr(config_module, "get_settings", lambda: fake)

    store = SubscriptionStore(db_path=tmp_path / "subs.db")
    store.create_subscription(
        subscription_id="s1",
        name="ok",
        subscription_type=SubscriptionType.RSS,
        platform=SubscriptionPlatform.PODCAST,
    )

    # A path under the download dir is accepted.
    good = download_dir / "podcasts"
    good.mkdir()
    updated = store.update_subscription("s1", output_dir=str(good))
    assert updated is not None

    # An out-of-scope path is rejected.
    with pytest.raises(ValueError):
        store.update_subscription("s1", output_dir="/etc")
