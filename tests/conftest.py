"""Shared test setup."""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_encryption_key_file(tmp_path_factory, monkeypatch):
    """Keep the generated secrets-at-rest key out of the real home directory."""
    key_file = str(tmp_path_factory.getbasetemp() / "secret.key")
    monkeypatch.setenv("ENCRYPTION_KEY_FILE", key_file)
    monkeypatch.setattr(get_settings(), "encryption_key_file", key_file)
