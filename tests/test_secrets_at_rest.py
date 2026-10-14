"""Stored secrets cannot be read from a copy of the database.

Regression tests for the security audit: without ENCRYPTION_KEY the key
was sha256(DOWNLOAD_DIR) — the same public value on every Docker install —
and cloud export would upload jobs.db itself to a caller-chosen provider.
"""

import base64
import hashlib
import sqlite3
import stat

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.delivery.cloud.export_manager import ExportManager, _is_internal_state
from app.store import _crypto
from app.store._store import JobStore


def _legacy_fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().download_dir.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


@pytest.fixture
def no_env_key(monkeypatch, tmp_path):
    key_file = tmp_path / "keys" / "secret.key"
    monkeypatch.setattr(get_settings(), "encryption_key", None)
    monkeypatch.setattr(get_settings(), "encryption_key_file", str(key_file))
    return key_file


class TestKey:
    def test_generated_key_is_random_and_private(self, no_env_key):
        stored = _crypto._encrypt_secret("sk-DUMMY")
        assert no_env_key.exists()
        assert stat.S_IMODE(no_env_key.stat().st_mode) == 0o600
        with pytest.raises(InvalidToken):
            _legacy_fernet().decrypt(stored[4:].encode())
        assert _crypto._decrypt_secret(stored) == "sk-DUMMY"

    def test_env_key_takes_precedence(self, no_env_key, monkeypatch):
        monkeypatch.setattr(get_settings(), "encryption_key", "operator-secret")
        stored = _crypto._encrypt_secret("sk-DUMMY")
        assert not no_env_key.exists()
        expected = Fernet(_crypto._derive("operator-secret"))
        assert expected.decrypt(stored[4:].encode()) == b"sk-DUMMY"

    def test_legacy_values_still_decrypt(self, no_env_key):
        legacy = "enc:" + _legacy_fernet().encrypt(b"sk-OLD").decode()
        assert _crypto._decrypt_secret(legacy) == "sk-OLD"


class TestRotation:
    def test_store_reencrypts_legacy_secrets_on_open(self, no_env_key, tmp_path):
        db = tmp_path / "jobs.db"
        store = JobStore(db_path=db)
        store.save_ai_settings(provider="openai", model="m", api_key="sk-NEW")
        legacy = "enc:" + _legacy_fernet().encrypt(b"sk-OLD").decode()
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE ai_settings SET api_key = ?", (legacy,))
            conn.execute(
                "INSERT INTO cloud_providers (id, provider_type, name, credentials, "
                "created_at, updated_at) VALUES ('p', 's3', 'p', ?, 'now', 'now')",
                (legacy,),
            )

        JobStore(db_path=db)  # reopening runs the rotation

        with sqlite3.connect(db) as conn:
            api_key, = conn.execute("SELECT api_key FROM ai_settings").fetchone()
            creds, = conn.execute("SELECT credentials FROM cloud_providers").fetchone()
        for value in (api_key, creds):
            assert value != legacy
            with pytest.raises(InvalidToken):
                _legacy_fernet().decrypt(value[4:].encode())
            assert _crypto._decrypt_secret(value) == "sk-OLD"

    def test_current_values_are_left_alone(self, no_env_key):
        stored = _crypto._encrypt_secret("sk-NEW")
        assert _crypto.rotate_secret(stored) is None
        assert _crypto.rotate_secret("b64:eA==") is None
        assert _crypto.rotate_secret(None) is None


class TestExportConfinement:
    @pytest.mark.parametrize(
        "rel",
        [
            "jobs.db",
            "jobs.db-wal",
            "subscriptions.db",
            "backups/jobs_20260101.db",
            "backups/notes.txt",
            "checkpoints/abc.json",
            "data.sqlite3",
        ],
    )
    def test_internal_state_is_not_exportable(self, rel, tmp_path):
        assert _is_internal_state(tmp_path / rel, tmp_path)

    @pytest.mark.parametrize("rel", ["episode.m4a", "subscriptions/s1/ep.mp3", "x/clip.mp4"])
    def test_media_is_exportable(self, rel, tmp_path):
        assert not _is_internal_state(tmp_path / rel, tmp_path)

    async def test_create_export_refuses_the_database(self, tmp_path, monkeypatch):
        monkeypatch.setattr(get_settings(), "download_dir", str(tmp_path))
        (tmp_path / "jobs.db").write_bytes(b"SQLite format 3\0")
        manager = ExportManager.__new__(ExportManager)
        manager._providers = {}
        manager._export_jobs = {}
        monkeypatch.setattr(manager, "get_provider", lambda pid: object(), raising=False)
        with pytest.raises(ValueError, match="internal application state"):
            await manager.create_export(str(tmp_path / "jobs.db"), provider_id="p")
