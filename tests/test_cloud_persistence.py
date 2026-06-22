"""Cloud-provider credentials are persisted encrypted and reload across runs."""

import sqlite3

import pytest

from app.core.cloud.base import ProviderConfig, ProviderType
from app.core.cloud.export_manager import ExportManager


@pytest.fixture
def job_db(monkeypatch, tmp_path):
    """Point the job store (which owns the cloud_providers table) at a temp DB."""
    import app.core.job_store as job_store

    db_path = tmp_path / "jobs.db"

    # Force a fresh JobStore singleton bound to the temp DB so the schema (and
    # the cloud_providers table) is created there.
    store = job_store.JobStore(db_path=db_path)
    monkeypatch.setattr(job_store, "_job_store", store, raising=False)
    return db_path


def _s3_config():
    return ProviderConfig(
        id="s3-test",
        provider_type=ProviderType.S3,
        name="Test S3",
        credentials={"access_key": "AKIA-SECRET", "secret_key": "topsecret"},
    )


def test_credentials_persist_encrypted_and_reload(job_db):
    manager = ExportManager()
    manager.register_provider(_s3_config())

    # Stored ciphertext must not contain the plaintext secret.
    with sqlite3.connect(str(job_db)) as conn:
        row = conn.execute(
            "SELECT credentials FROM cloud_providers WHERE id = ?", ("s3-test",)
        ).fetchone()
    assert row is not None
    assert "topsecret" not in row[0]
    assert "AKIA-SECRET" not in row[0]

    # A brand-new manager (simulating a restart) reloads and decrypts it.
    reloaded = ExportManager()
    provider = reloaded.get_provider("s3-test")
    assert provider is not None
    assert provider.config.credentials["secret_key"] == "topsecret"


def test_unregister_removes_persisted_row(job_db):
    manager = ExportManager()
    manager.register_provider(_s3_config())
    assert manager.unregister_provider("s3-test") is True

    with sqlite3.connect(str(job_db)) as conn:
        row = conn.execute(
            "SELECT 1 FROM cloud_providers WHERE id = ?", ("s3-test",)
        ).fetchone()
    assert row is None
