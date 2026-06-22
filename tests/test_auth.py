"""Tests for app/core/auth.py credential and bearer-token handling."""

from __future__ import annotations

import app.core.auth as auth_mod
from app.config import get_settings
from app.core.auth import AuthManager


def test_get_headers_uses_configured_bearer_token(monkeypatch):
    """The Authorization header must come from settings.twitter_bearer_token,
    not a hardcoded class constant, so it is env-overridable."""
    settings = get_settings()
    monkeypatch.setattr(settings, "twitter_bearer_token", "CUSTOM_TEST_TOKEN")

    mgr = AuthManager(auth_token="tok", ct0="csrf")
    headers = mgr.get_headers()

    assert headers["Authorization"] == "Bearer CUSTOM_TEST_TOKEN"


def test_default_bearer_token_matches_config():
    """When unset, behavior is identical to the default value in config.py."""
    settings = get_settings()
    mgr = AuthManager(auth_token="tok", ct0="csrf")
    headers = mgr.get_headers()

    assert headers["Authorization"] == f"Bearer {settings.twitter_bearer_token}"


def test_no_duplicate_hardcoded_constant():
    """The duplicate BEARER_TOKEN class constant must be removed."""
    assert not hasattr(auth_mod.AuthManager, "BEARER_TOKEN")
